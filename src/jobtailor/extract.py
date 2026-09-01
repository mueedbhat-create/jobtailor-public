"""Stage 2: JD extraction from job URLs using Scrapling.

Takes a list of JobLead objects and extracts the full job description
from each URL, along with key skills/requirements.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jobtailor.models import JobDescription, JobLead


class ExtractionError(Exception):
    """Raised when a job page cannot be extracted."""


class ScraplingExtractor:
    """Extract job descriptions using the scrapling CLI.

    Uses the command-line interface so it inherits anti-bot bypass,
    stealth headers, and AI-targeted content sanitization without
    needing to manage browser sessions in-process.
    """

    def __init__(self, binary: str | None = None, timeout: int = 90):
        self._binary = binary or self._default_binary()
        self._timeout = timeout

    @staticmethod
    def _default_binary() -> str:
        """Resolve the scrapling CLI, preferring the venv it ships in.

        LaunchAgent jobs run with a minimal PATH, so 'scrapling' alone is
        not found even though it's installed next to this interpreter.
        """
        here = Path(sys.executable).parent / "scrapling"
        if here.exists():
            return str(here)
        found = shutil.which("scrapling")
        if found:
            return found
        raise ExtractionError("scrapling CLI not found — run 'uv sync' to install it")

    def extract(self, lead: JobLead) -> JobDescription:
        """Fetch a job page and extract its main text content."""
        try:
            text = self._fetch_content(lead.url)
        except subprocess.CalledProcessError as exc:
            raise ExtractionError(
                f"Failed to fetch {lead.url}: {exc.stderr.decode(errors='replace')[-300:]}"
            ) from exc

        keywords = self._extract_keywords(text)
        return JobDescription(
            url=lead.url,
            company=lead.company,
            title=lead.title,
            description=text,
            keywords=keywords,
        )

    def _fetch_content(self, url: str) -> str:
        """Fetch content, escalating get -> fetch when content is too thin.

        `get` is fast (static request). If it returns too little or only
        navigation chrome, escalate to `fetch` which renders the page in a
        headless browser (needed for JS-heavy job boards like Monks,
        Greenhouse, Lever, Ashby).
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = self._run_extract("get", url, tmp)
            if len(text) >= 400:
                return text
            text = self._run_extract("fetch", url, tmp, extra=["--network-idle", "--wait", "2000"])
            if len(text) < 400:
                raise ExtractionError(f"Insufficient content extracted from {url}")
            return text

    def _run_extract(
        self, command: str, url: str, tmpdir: str, extra: list[str] | None = None
    ) -> str:
        out = Path(tmpdir) / "job.txt"
        cmd = [
            self._binary,
            "extract",
            command,
            url,
            str(out),
            "--ai-targeted",
        ]
        if extra:
            cmd += extra
        subprocess.run(cmd, check=True, capture_output=True, timeout=self._timeout)
        if not out.exists():
            raise ExtractionError(f"No content extracted from {url}")
        return out.read_text(errors="replace").strip()

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Pull likely skill keywords from the job description text."""
        if not text:
            return []
        skills = [
            "AI", "Automation", "Marketing", "Performance Marketing", "SEO",
            "Content", "Copywriting", "Strategy", "Analytics", "Growth",
            "n8n", "Zapier", "Make", "WordPress", "Shopify", "Google Ads",
            "Meta Ads", "Email Marketing", "CRM", "Salesforce", "HubSpot",
            "LLM", "Prompt Engineering", "Python", "SQL", "Data Analysis",
            "A/B Testing", "Conversion", "Funnel", "Lead Generation",
            "Brand", "Social Media", "Paid Ads", "ROI", "KPI",
        ]
        found = []
        lowered = text.lower()
        for skill in skills:
            if skill.lower() in lowered and skill not in found:
                found.append(skill)
        return found


def extract_all(
    leads: list[JobLead], extractor: ScraplingExtractor | None = None
) -> list[JobDescription]:
    """Extract JDs for all leads, isolating failures per lead."""
    extractor = extractor or ScraplingExtractor()
    results: list[JobDescription] = []
    for lead in leads:
        try:
            results.append(extractor.extract(lead))
        except Exception as exc:  # noqa: BLE001 - per-lead isolation
            print(f"[warn] extraction failed for {lead.url}: {exc}")
    return results