"""Stage 3: resume tailoring per job description.

For each JobDescription:
  1. Copies the resume directory into a temp workspace — the original
     resume folder is never written to.
  2. Calls the LLM (opencode by default) to rewrite resume sections
     in the copy to match the JD, honoring the guardrail: only rephrase/
     reorder/emphasize what's genuinely on the resume. Nothing invented.
  3. Saves the tailored copy to output/tailored/<slug>/ for PDF export.

No git branches are involved. ``TailoredResume.branch`` is kept as the
field name for compatibility but now holds a plain slug that names the
tailored directory (and later the PDF file).
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from jobtailor.llm import LLMClient, LLMConfig
from jobtailor.models import JobDescription, TailoredResume

SYSTEM_PROMPT = """You are an expert resume tailor. You will be given a JOB DESCRIPTION and the current RESUME (LaTeX Awesome-CV template).

Your task: rewrite the resume so it matches the job description and has a higher chance of passing ATS screening.

STRICT RULES (non-negotiable):
1. ONLY rephrase, reorder, and emphasize information that is ALREADY on the resume. NEVER invent skills, tools, experience, metrics, or achievements that are not present.
2. If the job asks for something not on the resume, leave it out. Do not fabricate.
3. Preserve the LaTeX structure and all commands exactly (\\cventry, \\cvsection, \\cvskill, \\cvitems, \\item, bold \\textbf, \\href). Do not change formatting commands or template syntax.
4. Keep every real fact, number, date, company name, and metric unchanged.
5. Reorder skills so the most job-relevant ones appear first.
6. Reword experience bullets to surface job-relevant keywords, keeping them truthful.
7. Keep the output to the same overall length as the input.
8. Respond with ONLY the complete rewritten LaTeX file content. No explanation, no markdown fences."""

_SECTIONS = ("experience", "skills", "education")


class TailorError(Exception):
    """Raised when tailoring fails."""


class ResumeTailor:
    def __init__(
        self,
        resume_dir: str | Path,
        llm: LLMClient | None = None,
        llm_config: LLMConfig | None = None,
        tailored_dir: str | Path = "output/tailored",
    ):
        self._resume_dir = Path(resume_dir).expanduser()
        if not (self._resume_dir / "resume.tex").exists():
            raise TailorError(f"resume.tex not found in {self._resume_dir}")
        self._llm = llm or LLMClient(llm_config or LLMConfig(provider="opencode"))
        self._tailored_dir = Path(tailored_dir)

    def tailor(self, jd: JobDescription) -> TailoredResume:
        """Tailor the resume to one job on an isolated copy."""
        slug = self._slug_for(jd)
        workspace = Path(tempfile.mkdtemp(prefix="jobtailor-tailor-"))
        work = workspace / "resume"
        try:
            shutil.copytree(
                self._resume_dir,
                work,
                ignore=shutil.ignore_patterns(".git", "resume.pdf", "__pycache__"),
            )
            changed = False
            for section in _SECTIONS:
                changed |= self._tailor_section(jd, section, work)
            if not changed:
                raise TailorError("Tailoring produced identical content.")

            dest = self._tailored_dir / slug
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(work, dest)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

        return TailoredResume(job_url=jd.url, branch=slug)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _slug_for(jd: JobDescription) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", jd.title.lower()).strip("-")[:30]
        company = re.sub(r"[^a-z0-9]+", "-", jd.company.lower()).strip("-")[:20]
        base = f"apply/{slug}-{company}".strip("-")
        return base[:60] or "apply/untitled"

    def _tailor_section(self, jd: JobDescription, section: str, work: Path) -> bool:
        path = work / "resume" / f"{section}.tex"
        current = path.read_text(errors="replace")
        prompt = (
            f"JOB DESCRIPTION:\n{jd.description[:12000]}\n\n"
            f"JOB TITLE: {jd.title}\nCOMPANY: {jd.company}\n"
            f"KEY SKILLS REQUESTED: {', '.join(jd.keywords)}\n\n"
            f"CURRENT RESUME SECTION ({section}.tex):\n{current}\n\n"
            f"Rewrite ONLY this section file ({section}.tex) following the strict rules."
        )
        new_text = self._llm.generate(SYSTEM_PROMPT, prompt, workdir=str(work))
        if not new_text or len(new_text) < len(current) * 0.3:
            raise TailorError(f"Tailoring produced unusable output for {section}.tex")
        path.write_text(new_text)
        return new_text != current


def tailor_all(
    jds: list[JobDescription],
    resume_dir: str | Path,
    llm_config: LLMConfig | None = None,
    tailored_dir: str | Path = "output/tailored",
) -> list[TailoredResume]:
    """Tailor resume for all JDs, isolating failures per job."""
    tailor = ResumeTailor(resume_dir, llm_config=llm_config, tailored_dir=tailored_dir)
    results: list[TailoredResume] = []
    for jd in jds:
        try:
            results.append(tailor.tailor(jd))
        except Exception as exc:  # noqa: BLE001 - per-job isolation
            print(f"[warn] tailoring failed for {jd.url}: {exc}")
    return results
