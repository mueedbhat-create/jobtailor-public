"""Telegram and Slack notification integrations.

Sends daily summaries and real-time alerts for pipeline events.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


@dataclass
class NotificationConfig:
    enabled: bool = False
    provider: str = ""  # "telegram" or "slack"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    slack_webhook_url: str = ""
    notify_on: list[str] = field(
        default_factory=lambda: ["daily_summary", "interview", "offer"]
    )


class Notifier:
    """Send notifications via Telegram or Slack."""

    def __init__(self, config: NotificationConfig | None = None):
        self._config = config or NotificationConfig()

    def send(self, title: str, body: str, event_type: str = "daily_summary") -> bool:
        """Send a notification. Returns True on success."""
        if not self._config.enabled:
            return False
        if event_type not in self._config.notify_on:
            return False

        if self._config.provider == "telegram":
            return self._send_telegram(title, body)
        elif self._config.provider == "slack":
            return self._send_slack(title, body)
        return False

    def _send_telegram(self, title: str, body: str) -> bool:
        token = self._config.telegram_bot_token
        chat_id = self._config.telegram_chat_id
        if not token or not chat_id:
            return False

        text = f"*{title}*\n\n{body}"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode()

        try:
            req = Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except (URLError, OSError):
            return False

    def _send_slack(self, title: str, body: str) -> bool:
        webhook = self._config.slack_webhook_url
        if not webhook:
            return False

        payload = json.dumps({
            "text": f"*{title}*\n{body}",
        }).encode()

        try:
            req = Request(webhook, data=payload, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except (URLError, OSError):
            return False

    def notify_daily_summary(self, summary: dict) -> bool:
        """Send a daily pipeline summary."""
        lines = [
            f"Jobs found: {summary.get('leads_found', 0)}",
            f"Applied: {summary.get('applied', 0)}",
            f"Interviews: {summary.get('interviews', 0)}",
            f"Offers: {summary.get('offers', 0)}",
        ]
        if summary.get("errors"):
            lines.append(f"Errors: {summary['errors']}")
        body = "\n".join(lines)
        return self.send("JobTailor Daily Summary", body, "daily_summary")

    def notify_event(self, event_type: str, company: str, title: str, detail: str = "") -> bool:
        """Send a real-time event notification."""
        body = f"Company: {company}\nRole: {title}"
        if detail:
            body += f"\n{detail}"
        return self.send(f"JobTailor: {event_type}", body, event_type)


def load_notification_config(config_path: str | Path = "config.yaml") -> NotificationConfig:
    """Load notification config from the main config file."""
    from jobtailor.config import load_config

    try:
        cfg = load_config(config_path)
    except Exception:  # noqa: BLE001
        return NotificationConfig()

    # Check if notifications config exists in config data
    import yaml
    raw = yaml.safe_load(Path(config_path).read_text()) or {}
    notif = raw.get("notifications") or {}
    return NotificationConfig(
        enabled=bool(notif.get("enabled", False)),
        provider=notif.get("provider", ""),
        telegram_bot_token=notif.get("telegram_bot_token", ""),
        telegram_chat_id=notif.get("telegram_chat_id", ""),
        slack_webhook_url=notif.get("slack_webhook_url", ""),
        notify_on=notif.get("notify_on", ["daily_summary", "interview", "offer"]),
    )
