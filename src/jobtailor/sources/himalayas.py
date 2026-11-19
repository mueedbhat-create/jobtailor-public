"""Himalayas (himalayas.app) remote jobs - free public JSON API, no key.

Strong for marketing / growth / operations roles. Each result carries the
posting date, the full description (so no page fetch is needed) and the
countries the employer accepts, so region-locked jobs are dropped for free.
"""

from __future__ import annotations

import datetime as dt

import httpx

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

SEARCH_URL = "https://himalayas.app/jobs/api/search"
PAGE_SIZE = 20


class HimalayasSource(SourceAdapter):
    name = "himalayas"

    def __init__(self, country: str = "", client: httpx.Client | None = None, max_pages: int = 2):
        self._country = country
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True,
                                              headers={"User-Agent": "jobtailor"})
        self._max_pages = max_pages

    def fetch(self, queries: list[str], companies: list[str], limit: int) -> list[JobLead]:
        leads: list[JobLead] = []
        seen: set[str] = set()
        for q in queries:
            got = 0
            for page in range(1, self._max_pages + 1):
                if got >= limit:
                    break
                params = {"q": q, "sort": "recent", "page": page}
                if self._country:
                    params["country"] = self._country
                else:
                    params["worldwide"] = "true"
                resp = self._client.get(SEARCH_URL, params=params)
                resp.raise_for_status()
                jobs = resp.json().get("jobs") or []
                for job in jobs:
                    lead = self._to_lead(job)
                    if lead and lead.url not in seen and got < limit:
                        seen.add(lead.url)
                        leads.append(lead)
                        got += 1
                if len(jobs) < PAGE_SIZE:
                    break
        return leads

    def _to_lead(self, job: dict) -> JobLead | None:
        url = job.get("applicationLink") or ""
        title = (job.get("title") or "").strip()
        if not url or not title:
            return None
        places = [p for p in (job.get("locationRestrictions") or []) if p]
        posted = ""
        if isinstance(job.get("pubDate"), (int, float)):
            posted = dt.datetime.fromtimestamp(job["pubDate"], dt.timezone.utc).date().isoformat()
        return JobLead(
            url=url,
            company=(job.get("companyName") or "")[:80],
            title=title[:120],
            source=self.name,
            remote=True,
            location=", ".join(places)[:80] or "Worldwide",
            posted=posted,
            description=job.get("description") or "",
        )
