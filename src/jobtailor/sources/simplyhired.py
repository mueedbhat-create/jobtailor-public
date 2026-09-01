"""SimplyHired job source adapter.

Scrapes the public search results page (server-rendered Chakra UI).
Cards carry data-testid attributes: companyName / searchSerpJobLocation.
The `l=Remote` parameter biases results but is not a strict filter, so a
client-side remote check is applied like on Wellfound.
"""

from __future__ import annotations

import urllib.parse

import httpx
from bs4 import BeautifulSoup

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

SIMPLYHIRED_SEARCH = "https://www.simplyhired.com/search"


class SimplyHiredSource(SourceAdapter):
    name = "simplyhired"

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
        url = f"{SIMPLYHIRED_SEARCH}?" + urllib.parse.urlencode({"q": keyword, "l": "Remote"})
        resp = self._client.get(url)
        resp.raise_for_status()
        return self._parse(resp.text, limit=limit)

    def _parse(self, html: str, limit: int) -> list[JobLead]:
        soup = BeautifulSoup(html, "html.parser")
        leads: list[JobLead] = []
        seen: set[str] = set()
        for anchor in soup.select("h2 a[href^='/job/']"):
            if len(leads) >= limit:
                break
            href = anchor.get("href", "").split("?")[0]
            if href in seen:
                continue
            card = anchor.find_parent(
                name=lambda tag: tag and tag.has_attr("data-testid")
            ) or anchor.find_parent("div")
            text = card.get_text(" ", strip=True).lower() if card else anchor.get_text(" ", strip=True).lower()
            if "remote" not in text:
                continue
            seen.add(href)
            leads.append(
                JobLead(
                    url="https://www.simplyhired.com" + href,
                    company=self._testid_text(card, "companyName")[:80],
                    title=anchor.get_text(" ", strip=True)[:120],
                    source=self.name,
                    remote=True,
                    location=self._testid_text(card, "searchSerpJobLocation")[:80],
                )
            )
        return leads

    @staticmethod
    def _testid_text(card, testid: str) -> str:
        if card is None:
            return ""
        el = card.select_one(f"[data-testid='{testid}']")
        return el.get_text(" ", strip=True) if el else ""
