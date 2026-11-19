"""Internshala internship source adapter.

Scrapes Internshala's public keyword search pages (server-rendered, no login
or API key needed). Only Work-from-Home listings are returned: the applicant
is based in Pune, so city-based Internshala roles are not actionable.
Unpaid listings are dropped at the source (user policy: paid internships
only) — the stipend appears inline on each search card.

Scope: this adapter targets the internships track. Enable it via
`internships.sources.internshala: true` (merged over discovery.sources) so
the full-time jobs track is unaffected.
"""

from __future__ import annotations

import time
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

INTERNSHALA_SEARCH = "https://internshala.com/internships/keywords-{query}/"


class InternshalaSource(SourceAdapter):
    name = "internshala"

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
        seen: set[str] = set()
        for keyword in queries + companies:
            for lead in self._search(keyword, limit=limit):
                if lead.url in seen:
                    continue
                seen.add(lead.url)
                leads.append(lead)
            # be polite: one search page per keyword, small gap between hits
            time.sleep(0.2)
        return leads

    def _search(self, keyword: str, limit: int) -> list[JobLead]:
        url = INTERNSHALA_SEARCH.format(query=urllib.parse.quote(keyword.strip()))
        resp = self._client.get(url)
        resp.raise_for_status()
        return self._parse(resp.text, limit=limit)

    def _parse(self, html: str, limit: int) -> list[JobLead]:
        soup = BeautifulSoup(html, "html.parser")
        leads: list[JobLead] = []
        for card in soup.select("div.container-fluid.individual_internship"):
            if len(leads) >= limit:
                break
            anchor = card.select_one("a.job-title-href")
            if not anchor:
                continue
            location = self._text(card.select_one("div.row-1-item.locations"))
            if "work from home" not in location.lower():
                continue  # city/hybrid roles are not actionable from Pune
            stipend = self._text(card.select_one("span.stipend"))
            if not stipend or "unpaid" in stipend.lower():
                continue  # paid internships only
            company_el = card.select_one("p.company-name")
            href = card.get("data-href") or anchor.get("href") or ""
            if not href:
                continue
            leads.append(
                JobLead(
                    url=href if href.startswith("http") else "https://internshala.com" + href,
                    company=self._text(company_el)[:80],
                    title=self._text(anchor)[:120],
                    source=self.name,
                    remote=True,
                    location="Work from home",
                )
            )
        return leads

    @staticmethod
    def _text(el) -> str:
        return el.get_text(" ", strip=True) if el else ""
