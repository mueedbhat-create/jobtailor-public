"""Webhook integrations for n8n, Zapier, and custom endpoints.

Sends pipeline events to external automation tools via HTTP webhooks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


@dataclass
class WebhookConfig:
    enabled: bool = False
    endpoints: list[dict[str, str]] = field(default_factory=list)
    # Each endpoint: {"url": "...", "events": "daily_summary,new_jobs,interview,offer", "secret": ""}
    secret: str = ""
    timeout: int = 10


class WebhookSender:
    """Send events to configured webhook endpoints."""

    def __init__(self, config: WebhookConfig | None = None):
        self._config = config or WebhookConfig()

    def send(self, event_type: str, payload: dict) -> list[dict]:
        """Send an event to all matching webhook endpoints.

        Returns a list of {url, status, error} for each endpoint.
        """
        if not self._config.enabled:
            return []

        results: list[dict] = []
        for endpoint in self._config.endpoints:
            url = endpoint.get("url", "")
            events = endpoint.get("events", "").split(",")
            events = [e.strip() for e in events if e.strip()]

            if events and event_type not in events:
                continue

            success = self._post_webhook(url, event_type, payload, endpoint.get("secret", ""))
            results.append({
                "url": url,
                "event": event_type,
                "status": "ok" if success else "failed",
            })

        return results

    def _post_webhook(self, url: str, event_type: str, payload: dict, secret: str = "") -> bool:
        body = json.dumps({
            "event": event_type,
            "source": "jobtailor",
            "data": payload,
        }).encode()

        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Webhook-Secret"] = secret

        try:
            req = Request(url, data=body, headers=headers)
            with urlopen(req, timeout=self._config.timeout) as resp:
                return 200 <= resp.status < 300
        except (URLError, OSError, TimeoutError):
            return False

    def notify_new_jobs(self, jobs: list[dict]) -> list[dict]:
        """Send new jobs discovered event."""
        return self.send("new_jobs", {"count": len(jobs), "jobs": jobs[:50]})

    def notify_application(self, app: dict) -> list[dict]:
        """Send application event."""
        return self.send("application", app)

    def notify_status_change(self, url: str, old_status: str, new_status: str) -> list[dict]:
        """Send status change event."""
        return self.send("status_change", {
            "url": url,
            "old_status": old_status,
            "new_status": new_status,
        })

    def notify_daily_summary(self, summary: dict) -> list[dict]:
        """Send daily summary event."""
        return self.send("daily_summary", summary)


def load_webhook_config(config_path: str | Path = "config.yaml") -> WebhookConfig:
    """Load webhook config from the main config file."""
    import yaml

    try:
        raw = yaml.safe_load(Path(config_path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return WebhookConfig()

    wh = raw.get("webhooks") or {}
    return WebhookConfig(
        enabled=bool(wh.get("enabled", False)),
        endpoints=wh.get("endpoints", []),
        secret=wh.get("secret", ""),
        timeout=int(wh.get("timeout", 10)),
    )
