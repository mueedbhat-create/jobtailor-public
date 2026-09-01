"""LinkedIn job source adapter (guest access).

Uses LinkedIn's public guest search endpoint — no login, no API key.
Remote roles are filtered server-side via f_WT=2.

LinkedIn jobs are NEVER auto-submitted downstream: see
jobtailor.apply.NEVER_AUTO_SOURCES.
"""

from __future__ import annotations

import urllib.parse

import httpx
from bs4 import BeautifulSoup

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

LINKEDIN_SEARCH = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)


class LinkedInSource(SourceAdapter):
    name = "linkedin"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    def fetch(
        self, queries: list[str], companies: list[str], limit: int
    ) -> list[JobLead]:
        leads: list[JobLead] = []
        for query in queries:
            leads.extend(self._search(query, limit=limit))
        return leads

    def _search(self, keyword: str, limit: int) -> list[JobLead]:
        url = f"{LINKEDIN_SEARCH}?" + urllib.parse.urlencode(
            {"keywords": keyword, "f_WT": "2", "start": "0"}
        )
        resp = self._client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"LinkedIn guest search returned {resp.status_code}")
        return self._parse(resp.text, limit=limit)

    def _parse(self, html: str, limit: int) -> list[JobLead]:
        soup = BeautifulSoup(html, "html.parser")
        leads: list[JobLead] = []
        for card in soup.select("div.base-search-card"):
            if len(leads) >= limit:
                break
            anchor = card.select_one("a.base-card__full-link")
            title_el = card.select_one("h3.base-search-card__title")
            if not anchor or not title_el:
                continue
            company_el = card.select_one(".base-search-card__subtitle")
            location_el = card.select_one(".job-search-card__location")
            leads.append(
                JobLead(
                    url=self._clean_url(anchor.get("href", "")),
                    company=(company_el.get_text(" ", strip=True) if company_el else "")[:80],
                    title=title_el.get_text(" ", strip=True)[:120],
                    source=self.name,
                    remote=True,
                    location=(location_el.get_text(" ", strip=True) if location_el else "")[:80],
                )
            )
        return leads

    @staticmethod
    def _clean_url(href: str) -> str:
        """Keep scheme+host+path; drop tracking params (position/refId/trackingId)."""
        parts = urllib.parse.urlsplit(href)
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
