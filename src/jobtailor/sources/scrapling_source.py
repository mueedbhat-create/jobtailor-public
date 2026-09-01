"""Scrapling-based job source adapter.

Uses Scrapling's StealthyFetcher for sites that need anti-bot bypass.
RemoteOK uses httpx directly (JSON API, no anti-bot needed).

Supported boards: remoteok, weworkremotely
"""

from __future__ import annotations

import json
import re
import urllib.parse

import httpx

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

# Lazy import — only load scrapling when the adapter is actually used
_scrapling_available = False
try:
    from scrapling.fetchers import StealthyFetcher as _StealthyFetcher

    _scrapling_available = True
except ImportError:
    pass


def _check_scrapling():
    if not _scrapling_available:
        raise ImportError(
            "scrapling is not installed. Run: pip install 'scrapling[all]' && scrapling install"
        )


# --- RemoteOK (JSON API, no anti-bot) ---


class RemoteOKSource(SourceAdapter):
    """Scrape RemoteOK (remote job board, JSON API — no anti-bot needed)."""

    name = "remoteok"
    API_URL = "https://remoteok.com/api"

    def fetch(self, queries: list[str], companies: list[str], limit: int) -> list[JobLead]:
        leads: list[JobLead] = []
        try:
            client = httpx.Client(
                timeout=15,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
            )
            resp = client.get(self.API_URL)
            resp.raise_for_status()
            text = resp.text
        except Exception as exc:
            print(f"[warn] remoteok fetch failed: {exc}")
            return []

        for query in queries:
            leads.extend(self._parse_json(text, query, limit=limit))
        return leads

    def _search(self, keyword: str, limit: int) -> list[JobLead]:
        return []

    def _parse_json(self, text: str, keyword: str, limit: int) -> list[JobLead]:
        leads: list[JobLead] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        if isinstance(data, list) and len(data) > 1:
            data = data[1:]

        kw_words = keyword.lower().split()
        kw_full = keyword.lower()

        for item in data:
            if len(leads) >= limit:
                break
            if not isinstance(item, dict):
                continue
            title = item.get("position", "")
            company = item.get("company", "")
            url = item.get("url", "")
            tags = " ".join(item.get("tags", [])).lower()
            searchable = f"{title} {tags} {company}".lower()

            if kw_full not in searchable and not any(w in searchable for w in kw_words if len(w) > 2):
                continue

            if url:
                leads.append(
                    JobLead(
                        url=url,
                        company=company[:80],
                        title=title[:120],
                        source=self.name,
                        remote=True,
                        location=item.get("location", "Remote"),
                    )
                )
        return leads


# --- We Work Remotely (Scrapling for anti-bot bypass) ---


class WeWorkRemotelySource(SourceAdapter):
    """Scrape We Work Remotely job listings via Scrapling."""

    name = "weworkremotely"
    SEARCH_URL = "https://weworkremotely.com/remote-jobs/search?term={query}"

    def fetch(self, queries: list[str], companies: list[str], limit: int) -> list[JobLead]:
        _check_scrapling()
        leads: list[JobLead] = []
        for query in queries:
            leads.extend(self._search(query, limit=limit))
        return leads

    def _search(self, keyword: str, limit: int) -> list[JobLead]:
        url = self.SEARCH_URL.format(query=urllib.parse.quote_plus(keyword))

        try:
            page = _StealthyFetcher.fetch(
                url,
                headless=True,
                network_idle=True,
                disable_resources=True,
                wait=2000,
                timeout=45000,
            )
        except Exception as exc:
            print(f"[warn] weworkremotely fetch failed for '{keyword}': {exc}")
            return []

        html = page.body.decode("utf-8", errors="replace") if isinstance(page.body, bytes) else page.text
        return self._parse(html, limit=limit)

    def _parse(self, html: str, limit: int) -> list[JobLead]:
        leads: list[JobLead] = []
        seen: set[str] = set()

        for match in re.finditer(
            r'href="(/remote-jobs/[^"]+)"[^>]*>\s*(?:<[^>]*>\s*)*([^<]{5,})',
            html,
        ):
            if len(leads) >= limit:
                break
            href = match.group(1)
            title = match.group(2).strip()
            if "find-your-plan" in href or "utm_" in href or len(title) < 5:
                continue
            full_url = "https://weworkremotely.com" + href
            if full_url in seen:
                continue
            seen.add(full_url)

            company = self._extract_company(html, match.start())
            leads.append(
                JobLead(
                    url=full_url,
                    company=company[:80],
                    title=title[:120],
                    source=self.name,
                    remote=True,
                )
            )
        return leads

    @staticmethod
    def _extract_company(html: str, pos: int) -> str:
        chunk = html[pos : pos + 1000]
        m = re.search(r'class="[^"]*company[^"]*"[^>]*>([^<]+)<', chunk, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r'alt="([^"]+?)(?:\s+logo)?"', chunk, re.I)
        if m:
            return m.group(1).strip()
        return ""
