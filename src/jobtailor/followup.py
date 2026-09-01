"""Quiet-application follow-up.

Surfaces submitted applications that have gone silent past a threshold and
drafts a short, channel-appropriate follow-up message in the candidate's
voice. Follow-ups are DRAFT ONLY — this module never sends anything. It
uses only claims already present in the submitted application materials so
a draft never introduces new, unverifiable facts.

Borrowed pattern from the ai-job-search framework: surface quiet apps,
draft a nudge, never auto-send, and never nudge an application more than
twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

DEFAULT_QUIET_DAYS = 10
MAX_FOLLOWUPS = 2


@dataclass
class QuietApplication:
    """A submitted application that has not heard back."""

    url: str
    company: str
    applied_at: str
    days_since: int
    followups_sent: int = 0


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    return None


def _days_since(value: str | None, today: date | None = None) -> int:
    d = _parse_date(value)
    if d is None:
        return 0
    return (today or date.today()) - d


def find_quiet(
    apps: list[dict],
    quiet_days: int = DEFAULT_QUIET_DAYS,
    today: date | None = None,
) -> list[QuietApplication]:
    """Return submitted applications silent for >= quiet_days, sorted oldest first."""
    quiet: list[QuietApplication] = []
    for app in apps:
        if not isinstance(app, dict) or not app.get("url"):
            continue
        if app.get("status") not in (None, "", "submitted"):
            continue
        applied = _parse_date(str(app.get("applied_at") or ""))
        if applied is None:
            continue
        age = (today or date.today()) - applied
        if age >= timedelta(days=quiet_days):
            quiet.append(
                QuietApplication(
                    url=str(app["url"]),
                    company=str(app.get("company") or ""),
                    applied_at=applied.isoformat(),
                    days_since=age.days,
                    followups_sent=int(app.get("followups_sent", 0) or 0),
                )
            )
    quiet.sort(key=lambda q: q.days_since, reverse=True)
    return quiet


def draft_followup(q: QuietApplication, name: str = "") -> str:
    """Draft a short, channel-appropriate follow-up message (never sends).

    Uses only the application URL and company already on file; never
    introduces new claims. The user reviews and adapts before sending.
    """
    greeting = f"Hi {q.company} team," if q.company else "Hi there,"
    closing = f"- {name}" if name else "- <your name>"
    return (
        f"{greeting}\n\n"
        f"I applied for the role I found at {q.url} and I wanted to check in "
        f"on the status of my application. I am still very interested in the "
        f"opportunity and happy to provide anything that would help your review.\n\n"
        f"Thank you for your time.\n\n{closing}"
    )