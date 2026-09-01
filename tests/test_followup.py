"""Tests for the quiet-application follow-up feature."""

from __future__ import annotations

from datetime import date, timedelta

from jobtailor.followup import (
    MAX_FOLLOWUPS,
    draft_followup,
    find_quiet,
    QuietApplication,
)


def _apps(*dates):
    return [
        {"url": f"https://example.com/jobs/{i}", "company": f"Co{i}", "applied_at": d, "status": "submitted"}
        for i, d in enumerate(dates)
    ]


class TestFindQuiet:
    def test_only_returns_apps_past_threshold(self):
        today = date(2026, 8, 27)
        apps = _apps(
            (today - timedelta(days=15)).isoformat(),  # quiet
            (today - timedelta(days=2)).isoformat(),   # not yet quiet
        )
        quiet = find_quiet(apps, quiet_days=10, today=today)
        assert len(quiet) == 1
        assert quiet[0].company == "Co0"
        assert quiet[0].days_since == 15

    def test_excludes_non_submitted(self):
        today = date(2026, 8, 27)
        apps = [{"url": "u", "company": "c", "applied_at": (today - timedelta(days=20)).isoformat(), "status": "skipped"}]
        assert find_quiet(apps, quiet_days=10, today=today) == []

    def test_skips_missing_or_malformed_dates(self):
        today = date(2026, 8, 27)
        apps = [
            {"url": "u1", "company": "c", "applied_at": "", "status": "submitted"},
            {"url": "u2", "company": "c", "applied_at": "not-a-date", "status": "submitted"},
        ]
        assert find_quiet(apps, quiet_days=10, today=today) == []

    def test_sorts_oldest_first(self):
        today = date(2026, 8, 27)
        apps = _apps(
            (today - timedelta(days=12)).isoformat(),
            (today - timedelta(days=30)).isoformat(),
            (today - timedelta(days=20)).isoformat(),
        )
        quiet = find_quiet(apps, quiet_days=10, today=today)
        assert [q.days_since for q in quiet] == [30, 20, 12]

    def test_carries_followup_count(self):
        today = date(2026, 8, 27)
        apps = [{"url": "u", "company": "c", "applied_at": (today - timedelta(days=20)).isoformat(),
                 "status": "submitted", "followups_sent": 1}]
        quiet = find_quiet(apps, quiet_days=10, today=today)
        assert quiet[0].followups_sent == 1


class TestDraftFollowup:
    def test_includes_company_and_url(self):
        q = QuietApplication(url="https://example.com/jobs/1", company="Acme", applied_at="2026-01-01", days_since=20)
        msg = draft_followup(q, name="Mueed")
        assert "Acme" in msg
        assert "https://example.com/jobs/1" in msg
        assert "Mueed" in msg

    def test_graceful_without_company(self):
        q = QuietApplication(url="https://example.com/jobs/1", company="", applied_at="2026-01-01", days_since=20)
        msg = draft_followup(q)
        assert msg.startswith("Hi there,")

    def test_never_invents_claims(self):
        q = QuietApplication(url="https://example.com/jobs/1", company="Acme", applied_at="2026-01-01", days_since=20)
        msg = draft_followup(q)
        assert "my application" in msg.lower()
        assert "salary" not in msg.lower()


def test_max_followups_constant():
    assert MAX_FOLLOWUPS == 2