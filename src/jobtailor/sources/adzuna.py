"""Adzuna job source adapter (free API, remote_only filter)."""

from __future__ import annotations

import urllib.parse

import httpx

from jobtailor.config import AdzunaConfig
from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class AdzunaSource(SourceAdapter):
    name = "adzuna"

    def __init__(self, config: AdzunaConfig, client: httpx.Client | None = None):
        self._config = config
        self._client = client or httpx.Client(timeout=30.0)

    def fetch(
        self, queries: list[str], companies: list[str], limit: int
    ) -> list[JobLead]:
        if not self._config.app_id or not self._config.app_key:
            raise RuntimeError(
                "Adzuna is enabled but adzuna.app_id / adzuna.app_key are not set in config.yaml. "
                "Register a free key at https://developer.adzuna.com/"
            )
        leads: list[JobLead] = []
        for query in queries + companies:
            leads.extend(self._search(query, limit=limit))
        return leads

    def _search(self, keyword: str, limit: int) -> list[JobLead]:
        params = {
            "app_id": self._config.app_id,
            "app_key": self._config.app_key,
            "what": keyword,
            "where": "remote",
            "max_days_old": 7,
            "results_per_page": limit,
            "content-type": "application/json",
        }
        url = ADZUNA_API.format(country=self._config.country, page=1)
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        leads = []
        for ad in data.get("results", []):
            location = ad.get("location", {}).get("display_name", "")
            remote = (
                "remote" in (ad.get("title", "") or "").lower()
                or "remote" in location.lower()
                or bool(ad.get("remote"))
            )
            if not remote:
                # Adzuna's API doesn't guarantee a remote flag; keep only
                # postings tagged remote to honor the strict remote policy.
                continue
            leads.append(
                JobLead(
                    url=ad["redirect_url"],
                    company=ad.get("company", {}).get("display_name", ""),
                    title=ad.get("title", ""),
                    source=self.name,
                    remote=True,
                    location=location,
                )
            )
        return leads