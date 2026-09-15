"""Core data models for JobTailor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class JobLead:
    """A single job posting discovered from a source."""

    url: str
    company: str
    title: str
    source: str
    remote: bool = True
    location: str = ""
    salary_raw: str = ""

    def canonical_url(self) -> str:
        """Strip common tracking params for dedup purposes."""
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(self.url)
        keep = [
            (q, v)
            for q, v in parse_qsl(parts.query)
            if not q.startswith(("utm_", "tracking", "position", "gh_src"))
        ]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(keep), parts.fragment)
        )


@dataclass
class JobDescription:
    """A job posting with its full extracted description."""

    url: str
    company: str
    title: str
    description: str
    keywords: list[str] = field(default_factory=list)
    salary_raw: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""


@dataclass
class TailoredResume:
    """A resume tailored to a specific job, ready for export.

    `branch` is kept as the field name for compatibility but holds a plain
    slug naming the tailored directory (output/tailored/<slug>/) and PDF.
    """

    job_url: str
    branch: str
    pdf_path: Path | None = None


@dataclass
class ApplicationStatus:
    """Result of preparing (and optionally submitting) an application."""

    job_url: str
    prepared: bool
    submitted: bool
    note: str = ""


@dataclass
class JobLeadBatch:
    """Results of a fetch run across sources."""

    leads: list[JobLead] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)

    def merge(self, other: "JobLeadBatch") -> None:
        self.leads.extend(other.leads)
        for source, count in other.source_counts.items():
            self.source_counts[source] = self.source_counts.get(source, 0) + count

    def dedupe(self) -> None:
        seen: set[str] = set()
        unique: list[JobLead] = []
        for lead in self.leads:
            key = lead.canonical_url()
            if key not in seen:
                seen.add(key)
                unique.append(lead)
        self.leads = unique

    def filter_remote(self) -> None:
        self.leads = [lead for lead in self.leads if lead.remote]

    def filter_salary(self, min_salary: float = 0, max_salary: float = 0) -> int:
        """Remove leads without salary info or outside the given range.

        Returns the number of leads removed.
        """
        if min_salary <= 0 and max_salary <= 0:
            return 0
        kept: list[JobLead] = []
        removed = 0
        for lead in self.leads:
            if not lead.salary_raw:
                kept.append(lead)  # unknown salary passes filter
                continue
            # Simple check on raw text
            from jobtailor.salary import extract_salary
            sr = extract_salary(lead.salary_raw)
            if sr is None or sr.midpoint is None:
                kept.append(lead)
            elif min_salary <= 0 and sr.midpoint <= max_salary:
                kept.append(lead)
            elif max_salary <= 0 and sr.midpoint >= min_salary:
                kept.append(lead)
            elif min_salary <= sr.midpoint <= max_salary:
                kept.append(lead)
            else:
                removed += 1
        self.leads = kept
        return removed