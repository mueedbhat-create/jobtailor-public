"""Stage 3: tailor the resume for each job with ONE AI call per job.

For each JobDescription the model is asked once (see ``brain.py``) for:
fit (apply/skip), bullet and skill order, up to three reworded bullets,
skills to surface, and - only when the application form has a text box -
a short note. Code then rebuilds the resume from the user's own LaTeX into
output/tailored/<slug>/; the original resume folder is never written to.

Every reworded bullet, surfaced skill and note is fact-checked against the
real resume (``truth.violations``); anything that fails keeps the original.

``TailoredResume.branch`` keeps its historical name but holds the slug that
names the tailored folder (and later the PDF file).
"""

from __future__ import annotations

import re
from pathlib import Path

from jobtailor.brain import Plan, ResumeBank, build_resume, check_note, hard_skip, plan_job
from jobtailor.llm import LLMClient, LLMConfig, QuotaExhausted
from jobtailor.models import JobDescription, TailoredResume


class TailorError(Exception):
    """Raised when tailoring fails."""


class JobSkipped(TailorError):
    """The job is not a fit (decided in code or by the one AI call)."""


class ResumeTailor:
    def __init__(
        self,
        resume_dir: str | Path,
        llm: LLMClient | None = None,
        llm_config: LLMConfig | None = None,
        tailored_dir: str | Path = "output/tailored",
        profile: str = "",
        location: str = "",
        cache_dir: str | Path | None = None,
        skip_engineering: bool = True,
    ):
        self._resume_dir = Path(resume_dir).expanduser()
        if not (self._resume_dir / "resume.tex").exists():
            raise TailorError(f"resume.tex not found in {self._resume_dir}")
        self._llm = llm or LLMClient(llm_config or LLMConfig())
        self._tailored_dir = Path(tailored_dir)
        self._bank = ResumeBank.load(self._resume_dir)
        if not self._bank.entries:
            raise TailorError("no \\cventry bullets found in resume/experience.tex")
        self._profile = profile
        self._location = location
        self._skip_eng = skip_engineering
        self._cache_dir = Path(cache_dir) if cache_dir else self._tailored_dir.parent / "cache" / "plans"
        self.rejected: dict[str, list[str]] = {}  # slug -> fact-check notes
        self.notes: dict[str, str] = {}  # job url -> verified note
        self.plans: dict[str, Plan] = {}  # job url -> plan

    @property
    def reference(self) -> str:
        return self._bank.reference

    def tailor(self, jd: JobDescription, want_note: bool = False) -> TailoredResume:
        """Tailor the resume to one job. Raises JobSkipped if it isn't a fit."""
        reason = hard_skip(jd, self._location, self._skip_eng)
        if reason:
            raise JobSkipped(reason)
        plan = plan_job(self._llm, jd, self._bank, self._profile, self._location,
                        want_note=want_note, cache_dir=self._cache_dir,
                        skip_engineering=self._skip_eng)
        self.plans[jd.url] = plan
        if not plan.apply:
            raise JobSkipped(plan.why or "AI judged it not a fit")
        slug = self._slug_for(jd)
        report = build_resume(self._bank, plan, self._tailored_dir / slug)
        if report.rejected:
            self.rejected[slug] = report.rejected
        if want_note and plan.note:
            note = check_note(plan.note, jd.title, jd.company, self._bank.reference)
            if note:
                self.notes[jd.url] = note
            else:
                self.rejected.setdefault(slug, []).append("note: failed the fact-check, left blank")
        return TailoredResume(job_url=jd.url, branch=slug)

    @staticmethod
    def _slug_for(jd: JobDescription) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", jd.title.lower()).strip("-")[:30]
        company = re.sub(r"[^a-z0-9]+", "-", jd.company.lower()).strip("-")[:20]
        base = f"apply/{slug}-{company}".strip("-")
        return base[:60] or "apply/untitled"


def tailor_jobs(
    jds: list[JobDescription],
    resume_dir: str | Path,
    llm_config: LLMConfig | None = None,
    tailored_dir: str | Path = "output/tailored",
    *,
    llm: LLMClient | None = None,
    profile: str = "",
    location: str = "",
    want_note: set[str] | None = None,
    skip_engineering: bool = True,
    echo=print,
) -> tuple[list[TailoredResume], dict[str, str], list[tuple[JobDescription, str]], ResumeTailor]:
    """Tailor every job, one at a time. Returns (results, notes, skipped, tailor).

    Sequential on purpose: each job is one small call, and stopping the moment
    the free allowance or the run's token budget is gone wastes nothing.
    """
    tailor = ResumeTailor(resume_dir, llm=llm, llm_config=llm_config, tailored_dir=tailored_dir,
                          profile=profile, location=location, skip_engineering=skip_engineering)
    want_note = want_note or set()
    results: list[TailoredResume] = []
    skipped: list[tuple[JobDescription, str]] = []
    stop = ""
    for n, jd in enumerate(jds, start=1):
        tag = f"  [{n}/{len(jds)}]"
        if stop:
            echo(f"{tag} FAIL {jd.title} @ {jd.company}: {stop}")
            continue
        try:
            res = tailor.tailor(jd, want_note=jd.url in want_note)
        except JobSkipped as exc:
            skipped.append((jd, str(exc)))
            echo(f"{tag} skip {jd.title} @ {jd.company} - {str(exc)[:100]}")
            continue
        except QuotaExhausted as exc:
            stop = str(exc)
            echo(f"{tag} FAIL {jd.title} @ {jd.company}: {stop}")
            continue
        except Exception as exc:  # noqa: BLE001 - per-job isolation
            echo(f"{tag} FAIL {jd.title} @ {jd.company}: {str(exc)[:160]}")
            continue
        results.append(res)
        plan = tailor.plans.get(jd.url)
        cached = " (cached, 0 tokens)" if plan and plan.cached else ""
        echo(f"{tag} ok   {jd.title} @ {jd.company}{cached}")
        for why in tailor.rejected.get(res.branch, []):
            echo(f"         [fact-check] {why}")
    return results, tailor.notes, skipped, tailor


def tailor_all(
    jds: list[JobDescription],
    resume_dir: str | Path,
    llm_config: LLMConfig | None = None,
    tailored_dir: str | Path = "output/tailored",
    **kwargs,
) -> list[TailoredResume]:
    """Tailor resumes for all JDs (compatibility wrapper around tailor_jobs)."""
    kwargs.setdefault("echo", lambda m: print(m, flush=True))
    try:
        results, _, _, _ = tailor_jobs(jds, resume_dir, llm_config, tailored_dir, **kwargs)
    except TailorError as exc:
        print(f"  tailoring unavailable: {exc}", flush=True)
        return []
    return results
