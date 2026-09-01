"""Wellfound (AngelList) job source adapter.

Wellfound has no public API. This adapter scrapes its public job search
pages. Remote roles are filtered server-side via the remote_only search
URL.
"""

from __future__ import annotations

import urllib.parse

import httpx
from bs4 import BeautifulSoup

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

WELLFOUND_SEARCH = "https://wellfound.com/role/r/{role}"


class WellfoundSource(SourceAdapter):
    name = "wellfound"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )

    def fetch(
        self, queries: list[str], companies: list[str], limit: int
    ) -> list[JobLead]:
        leads: list[JobLead] = []
        for query in queries:
            leads.extend(self._search(query, limit=limit))
        return leads

    def _search(self, keyword: str, limit: int) -> list[JobLead]:
        # role slugs used by Wellfound; keyword mapped to best-effort slug
        slug = self._slug_for(keyword)
        url = WELLFOUND_SEARCH.format(role=slug)
        resp = self._client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        leads = []
        for anchor in soup.select("a[href*='/jobs/']"):
            if len(leads) >= limit:
                break
            href = anchor.get("href", "")
            # walk up to the job card container
            card = anchor.find_parent(class_="mb-6")
            text = card.get_text(" ", strip=True) if card else anchor.get_text(" ", strip=True)
            if "remote" not in text.lower():
                continue
            company = ""
            if card:
                for company_link in card.select("a[href*='/company/']"):
                    name = company_link.get_text(" ", strip=True)
                    if name:
                        company = name
                        break
            leads.append(
                JobLead(
                    url="https://wellfound.com" + href,
                    company=company,
                    title=anchor.get_text(" ", strip=True)[:120],
                    source=self.name,
                    remote=True,
                )
            )
        return leads

    @staticmethod
    def _slug_for(keyword: str) -> str:
        k = keyword.lower()
        if "marketing" in k or "growth" in k:
            return "marketing"
        if "automation" in k or "ai" in k or "engineer" in k:
            return "engineer"
        if "performance" in k or "digital" in k:
            return "marketing"
        return "marketing"