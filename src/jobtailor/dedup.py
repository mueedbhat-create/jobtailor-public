"""Cross-day duplicate detection.

Loads all historical lead cache files and identifies jobs that have been
seen before, preventing duplicate applications across runs.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from jobtailor.models import JobLead, JobLeadBatch


def load_all_historical_urls(
    leads_dir: str | Path, days: int = 30
) -> dict[str, dict]:
    """Load canonical URLs from the last N days of lead cache files.

    Returns a dict of canonical_url -> {url, company, title, source, first_seen}.
    """
    leads_path = Path(leads_dir)
    if not leads_path.exists():
        return {}

    historical: dict[str, dict] = {}
    cutoff = date.today() - timedelta(days=days)

    for path in sorted(leads_path.glob("*.json")):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for lead in data.get("leads", []):
            if not isinstance(lead, dict) or not lead.get("url"):
                continue
            temp = JobLead(
                url=lead["url"],
                company=lead.get("company", ""),
                title=lead.get("title", ""),
                source=lead.get("source", ""),
            )
            canonical = temp.canonical_url()
            if canonical not in historical:
                historical[canonical] = {
                    "url": lead["url"],
                    "company": lead.get("company", ""),
                    "title": lead.get("title", ""),
                    "source": lead.get("source", ""),
                    "first_seen": path.stem,
                }
    return historical


def dedupe_against_history(
    batch: JobLeadBatch,
    leads_dir: str | Path,
    days: int = 30,
) -> int:
    """Remove leads already seen in historical cache files.

    Returns the number of duplicates removed.
    """
    historical = load_all_historical_urls(leads_dir, days)
    if not historical:
        return 0

    kept: list[JobLead] = []
    removed = 0
    for lead in batch.leads:
        canonical = lead.canonical_url()
        if canonical in historical:
            removed += 1
        else:
            kept.append(lead)

    batch.leads = kept
    return removed
