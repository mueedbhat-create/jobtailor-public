"""freehire.me job source adapter.

Queries freehire.me's public, keyless JSON API (an open-source IT job
aggregator that normalizes postings from many ATS platforms into one
schema). Structured results come back with the full description inline, so
no per-hit follow-up is needed. Geographic filtering is via structured
facets; we request fully-remote work mode only.

Scope note: freehire's faceted filtering is tuned tech-first, but its corpus
crawls whole company career pages and includes marketing / growth roles. We
still run everything through the fit gate upstream, so a marketing lead that
sneaks through here is handled there.
"""

from __future__ import annotations

import httpx

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

FREEHIRE_API = "https://freehire.me/api/v1/agent/jobs/search"
FREEHIRE_URL = "https://freehire.me/jobs"


class FreehireSource(SourceAdapter):
    name = "freehire"

    def __init__(self, base_url: str = FREEHIRE_API, client: httpx.Client | None = None):
        self._base_url = base_url
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(
        self, queries: list[str], companies: list[str], limit: int
    ) -> list[JobLead]:
        leads: list[JobLead] = []
        seen: set[str] = set()
        # Union all queries into one remote-mode call; dedupe across them.
        for keyword in queries + companies:
            for item in self._search(keyword, limit=limit):
                url = item.get("url") or (
                    f"{FREEHIRE_URL}/{item.get('public_slug')}" if item.get("public_slug") else ""
                )
                if not url or url in seen:
                    continue
                seen.add(url)
                leads.append(self._to_job_lead(item, url))
        return leads

    def _search(self, keyword: str, limit: int) -> list[dict]:
        params = {
            "q": keyword,
            "work_mode": "remote",
            "limit": limit,
        }
        resp = self._client.get(self._base_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("data", [])
        if isinstance(results, list):
            return [r for r in results if isinstance(r, dict)]
        return []

    def _to_job_lead(self, item: dict, url: str) -> JobLead:
        work_mode = str(item.get("work_mode") or "").lower()
        remote = work_mode == "remote"
        return JobLead(
            url=url,
            company=str(item.get("company") or ""),
            title=str(item.get("title") or ""),
            source=self.name,
            remote=remote,
            location=str(item.get("location") or ""),
        )