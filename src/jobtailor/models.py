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