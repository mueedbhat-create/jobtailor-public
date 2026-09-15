"""Response rate analytics.

Aggregates application data across runs to compute response rates,
conversion funnels, and source effectiveness.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


class AnalyticsEngine:
    """Compute analytics from application state and tracking data."""

    def __init__(
        self,
        state_dir: str | Path = "output/applications",
        leads_dir: str | Path = "output/leads",
        tracking_dir: str | Path = "output/tracking",
    ):
        self._state_dir = Path(state_dir)
        self._leads_dir = Path(leads_dir)
        self._tracking_dir = Path(tracking_dir)

    def _load_all_applications(self) -> list[dict]:
        apps: list[dict] = []
        if not self._state_dir.exists():
            return apps
        for path in sorted(self._state_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            for url, entry in data.items():
                if isinstance(entry, dict) and url:
                    apps.append({"url": url, **entry})
        return apps

    def _load_leads_index(self) -> dict[str, dict]:
        idx: dict[str, dict] = {}
        if not self._leads_dir.exists():
            return idx
        for path in sorted(self._leads_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for lead in data.get("leads", []):
                if isinstance(lead, dict) and lead.get("url"):
                    idx[lead["url"]] = lead
        return idx

    def _load_tracking_index(self) -> dict[str, dict]:
        idx: dict[str, dict] = {}
        if not self._tracking_dir.exists():
            return idx
        for path in sorted(self._tracking_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for rec in data.get("apps", []):
                if isinstance(rec, dict) and rec.get("url"):
                    idx[rec["url"]] = rec
        return idx

    def overview(self) -> dict:
        """Full analytics overview."""
        apps = self._load_all_applications()
        leads = self._load_leads_index()
        tracking = self._load_tracking_index()

        total = len(apps)
        by_status: dict[str, int] = defaultdict(int)
        by_source: dict[str, dict] = defaultdict(lambda: {"applied": 0, "responses": 0})
        by_day: dict[str, int] = defaultdict(int)
        by_company: dict[str, dict] = defaultdict(lambda: {"applied": 0, "status": "unknown"})

        for app in apps:
            status = app.get("status", "pending")
            by_status[status] += 1

            url = app.get("url", "")
            day = app.get("applied_at", "")[:10] or app.get("opened_at", "")[:10]
            if day:
                by_day[day] += 1

            lead = leads.get(url, {})
            source = lead.get("source", "unknown")
            by_source[source]["applied"] += 1

            track = tracking.get(url, {})
            track_status = track.get("status", "no_response")
            if track_status not in ("no_response", "other"):
                by_source[source]["responses"] += 1

            company = lead.get("company", app.get("company", "unknown"))
            by_company[company]["applied"] += 1
            by_company[company]["status"] = status

        # Compute response rates per source
        source_rates = {}
        for src, data in by_source.items():
            total_applied = data["applied"]
            responses = data["responses"]
            rate = responses / total_applied if total_applied > 0 else 0.0
            source_rates[src] = {
                "applied": total_applied,
                "responses": responses,
                "response_rate": round(rate, 3),
            }

        # Funnel
        funnel = {
            "total_leads": sum(
                len(json.loads(p.read_text()).get("leads", []))
                for p in self._leads_dir.glob("*.json")
                if self._leads_dir.exists()
            ),
            "total_applied": total,
            "submitted": by_status.get("submitted", 0),
            "prepared": by_status.get("prepared", 0),
            "failed": by_status.get("failed", 0),
        }

        tracking_totals = {"confirmation": 0, "rejected": 0, "interview": 0, "offer": 0}
        for rec in tracking.values():
            st = rec.get("status", "")
            if st in tracking_totals:
                tracking_totals[st] += 1

        return {
            "total_applied": total,
            "by_status": dict(by_status),
            "by_source": source_rates,
            "by_day": dict(by_day),
            "funnel": funnel,
            "tracking": tracking_totals,
            "top_companies": dict(
                sorted(by_company.items(), key=lambda x: x[1]["applied"], reverse=True)[:10]
            ),
        }

    def daily_summary(self, target_date: str | None = None) -> dict:
        """Analytics for a single day."""
        day = target_date or date.today().isoformat()
        apps = self._load_all_applications()
        leads = self._load_leads_index()
        tracking = self._load_tracking_index()

        day_apps = [a for a in apps if (a.get("applied_at") or a.get("opened_at", ""))[:10] == day]
        day_leads = 0
        if self._leads_dir.exists():
            path = self._leads_dir / f"{day}.json"
            if path.exists():
                try:
                    day_leads = len(json.loads(path.read_text()).get("leads", []))
                except (json.JSONDecodeError, OSError):
                    pass

        return {
            "date": day,
            "leads_found": day_leads,
            "applications": len(day_apps),
            "statuses": {
                s: sum(1 for a in day_apps if a.get("status") == s)
                for s in ("submitted", "prepared", "failed")
            },
        }

    def source_effectiveness(self) -> list[dict]:
        """Rank sources by response rate."""
        overview = self.overview()
        sources = overview.get("by_source", {})
        ranked = [
            {"source": src, **data}
            for src, data in sorted(
                sources.items(), key=lambda x: x[1]["response_rate"], reverse=True
            )
        ]
        return ranked
