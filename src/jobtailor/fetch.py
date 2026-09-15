"""Lead fetching orchestration: run sources, merge, dedupe, filter remote."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from jobtailor.config import Config
from jobtailor.models import JobLead, JobLeadBatch
from jobtailor.sources import enabled_sources, build_source


class FetchError(Exception):
    """Raised when a fetch run fails entirely."""


class LeadFetcher:
    def __init__(self, config: Config, output_dir: str | Path = "output/leads"):
        self._config = config
        self._output = Path(output_dir).expanduser()

    def run(self, cache: bool = True, queries: list[str] | None = None) -> JobLeadBatch:
        """Fetch leads from all enabled sources, dedupe, filter remote.

        `queries` overrides the config's discovery queries when provided
        (used by the internships track to fetch internship-specific roles).
        """
        query_kw = queries if queries is not None else [q.keyword for q in self._config.discovery.queries]
        companies = self._config.discovery.companies

        if not query_kw and not companies:
            raise FetchError("No discovery queries or companies configured.")

        batch = JobLeadBatch()
        for name in enabled_sources(self._config):
            try:
                adapter = build_source(name, self._config)
                leads = adapter.fetch(query_kw, companies, limit=self._config.discovery.max_per_query)
                batch.merge(JobLeadBatch(leads=[*leads], source_counts={name: len(leads)}))
            except Exception as exc:  # noqa: BLE001 - per-source isolation
                batch.source_counts[name] = 0
                print(f"[warn] source '{name}' failed: {exc}")

        batch.dedupe()
        batch.filter_remote()

        # Cross-day duplicate detection
        from jobtailor.dedup import dedupe_against_history
        historical_removed = dedupe_against_history(batch, self._output)
        if historical_removed:
            print(f"  [dedup] removed {historical_removed} lead(s) seen in previous runs")

        excluded = self._exclude_unmatched(batch)
        if excluded:
            print(f"  [filter] dropped {excluded} lead(s) matching exclude_title_keywords")

        if cache and batch.leads:
            self._write_cache(batch)

        return batch

    def _exclude_unmatched(self, batch: JobLeadBatch) -> int:
        """Drop leads whose title contains an excluded keyword (case-insensitive)."""
        patterns = self._config.discovery.exclude_title_keywords
        if not patterns:
            return 0
        kept: list[JobLead] = []
        dropped = 0
        for lead in batch.leads:
            title = lead.title.lower()
            if any(p in title for p in patterns):
                dropped += 1
            else:
                kept.append(lead)
        batch.leads = kept
        return dropped

    def _write_cache(self, batch: JobLeadBatch) -> None:
        self._output.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        path = self._output / f"{today}.json"
        payload = {
            "date": today,
            "source_counts": batch.source_counts,
            "leads": [self._lead_to_dict(lead) for lead in batch.leads],
        }
        path.write_text(json.dumps(payload, indent=2))

    @staticmethod
    def _lead_to_dict(lead: JobLead) -> dict:
        return {
            "url": lead.url,
            "company": lead.company,
            "title": lead.title,
            "source": lead.source,
            "remote": lead.remote,
            "location": lead.location,
        }


def load_leads_from_cache(path: str | Path) -> list[JobLead]:
    """Load previously cached leads (used by later pipeline stages)."""
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return [
        JobLead(
            url=item["url"],
            company=item["company"],
            title=item["title"],
            source=item["source"],
            remote=item.get("remote", True),
            location=item.get("location", ""),
        )
        for item in data.get("leads", [])
    ]