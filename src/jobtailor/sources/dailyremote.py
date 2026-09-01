"""DailyRemote job source adapter.

Scrapes dailyremote.com's public search. Some listings hide the company
name ("Company hidden") — the parser tolerates that and leaves it empty.
"""

from __future__ import annotations

import urllib.parse

import httpx
from bs4 import BeautifulSoup

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

DAILYREMOTE_SEARCH = "https://dailyremote.com/remote-jobs"

_BYLINE_NOISE = {"company hidden", "full time", "part time", "contract", "internship", "·"}


class DailyRemoteSource(SourceAdapter):
    name = "dailyremote"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
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
        url = f"{DAILYREMOTE_SEARCH}?" + urllib.parse.urlencode({"search": keyword})
        resp = self._client.get(url)
        resp.raise_for_status()
        return self._parse(resp.text, limit=limit)

    def _parse(self, html: str, limit: int) -> list[JobLead]:
        soup = BeautifulSoup(html, "html.parser")
        leads: list[JobLead] = []
        seen: set[str] = set()
        for anchor in soup.select("h2 a[href^='/remote-job/']"):
            if len(leads) >= limit:
                break
            href = anchor.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            company = self._company_for(anchor)
            leads.append(
                JobLead(
                    url="https://dailyremote.com" + href,
                    company=company[:80],
                    title=anchor.get_text(" ", strip=True)[:120],
                    source=self.name,
                    remote=True,
                )
            )
        return leads

    @staticmethod
    def _company_for(anchor) -> str:
        card = anchor.find_parent(class_=lambda c: c and "card" in c) if anchor else None
        if card is None:
            return ""
        byline = card.select_one(".lst-card__byline")
        if byline is None:
            return ""
        for span in byline.find_all("span"):
            text = span.get_text(" ", strip=True).lower()
            if text and text not in _BYLINE_NOISE and not text.startswith("company hidden"):
                return span.get_text(" ", strip=True)
        return ""
