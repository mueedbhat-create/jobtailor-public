"""Cover letter generation.

Generates tailored cover letters for each job using the same LLM
pipeline as resume tailoring. Produces both LaTeX and plain-text versions.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from jobtailor.llm import LLMClient, LLMConfig
from jobtailor.models import JobDescription

COVER_LETTER_SYSTEM = """You are an expert cover letter writer. You will be given a JOB DESCRIPTION and a CANDIDATE PROFILE.

Write a concise, professional cover letter (max 350 words) that:
1. Opens with a specific hook about why this role at this company excites the candidate.
2. Maps 2-3 of the candidate's most relevant experiences to the job's requirements.
3. Shows genuine knowledge of the company's mission/product (if mentioned in the JD).
4. Closes with a clear call to action.
5. Uses a confident but not arrogant tone.

RULES:
- Only reference experiences and skills the candidate actually has (from the profile).
- Do NOT fabricate metrics, company names, or achievements.
- Keep the letter under 350 words.
- Respond with ONLY the cover letter text. No markdown fences, no explanation."""


class CoverLetterGenerator:
    """Generate cover letters for job descriptions."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        llm_config: LLMConfig | None = None,
        output_dir: str | Path = "output/cover_letters",
    ):
        self._llm = llm or LLMClient(llm_config or LLMConfig(provider="opencode"))
        self._output_dir = Path(output_dir)

    def generate(self, jd: JobDescription, profile: str = "") -> str:
        """Generate a plain-text cover letter for one job."""
        prompt = (
            f"CANDIDATE PROFILE:\n{profile}\n\n"
            f"JOB DESCRIPTION:\n{jd.description[:8000]}\n\n"
            f"JOB TITLE: {jd.title}\nCOMPANY: {jd.company}\n\n"
            f"Write the cover letter."
        )
        letter = self._llm.generate(COVER_LETTER_SYSTEM, prompt)
        if not letter or len(letter) < 50:
            raise ValueError("Cover letter generation produced unusable output")
        return letter.strip()

    def generate_and_save(
        self,
        jd: JobDescription,
        profile: str = "",
        slug: str = "",
    ) -> Path:
        """Generate and save a cover letter to the output directory."""
        letter = self.generate(jd, profile)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        if not slug:
            slug = re.sub(r"[^a-z0-9]+", "-", jd.title.lower()).strip("-")[:30]
            company = re.sub(r"[^a-z0-9]+", "-", jd.company.lower()).strip("-")[:20]
            slug = f"{slug}-{company}"[:60] or "untitled"

        path = self._output_dir / f"{slug}.txt"
        path.write_text(letter)
        return path

    def generate_batch(
        self,
        jds: list[JobDescription],
        profile: str = "",
    ) -> list[dict]:
        """Generate cover letters for multiple jobs, isolating failures."""
        results: list[dict] = []
        for jd in jds:
            try:
                path = self.generate_and_save(jd, profile)
                results.append({
                    "company": jd.company,
                    "title": jd.title,
                    "url": jd.url,
                    "path": str(path),
                    "ok": True,
                })
            except Exception as exc:  # noqa: BLE001 - per-job isolation
                results.append({
                    "company": jd.company,
                    "title": jd.title,
                    "url": jd.url,
                    "path": "",
                    "ok": False,
                    "error": str(exc),
                })
        return results
