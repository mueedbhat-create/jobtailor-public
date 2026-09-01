"""Tests for Gmail application tracking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobtailor.config import GmailConfig
from jobtailor.tracking import (
    CONFIRMATION,
    INTERVIEW,
    NO_RESPONSE,
    OFFER,
    OTHER,
    REJECTED,
    GmailTracker,
    classify,
    is_configured,
    query_for,
    resolve_status,
)


def _kind(subject: str, body: str = "") -> str:
    return classify(subject, body)


class TestClassifyRejection:
    def test_unable_to_offer(self):
        assert _kind(
            "Your application to Acme",
            "We regret to inform you that we are unable to offer you the position at this time.",
        ) == REJECTED

    def test_regret_unable_to_offer(self):
        assert _kind(
            "Update on your application",
            "We regret to inform you that we are unable to extend an offer.",
        ) == REJECTED

    def test_not_offering_you_the_position(self):
        assert _kind("Application update", "We will not be offering you the role.") == REJECTED

    def test_moving_forward_with_other_candidates(self):
        assert _kind(
            "Your application",
            "After careful consideration, we have decided to move forward with other candidates.",
        ) == REJECTED

    def test_position_filled(self):
        assert _kind("Role update", "The position has been filled.") == REJECTED

    def test_cannot_offer_interview_is_rejection(self):
        assert _kind("Sorry", "We cannot offer you an interview at this time.") == REJECTED

    def test_will_not_be_progressing(self):
        assert _kind("Outcome", "You will not be progressing to the next round.") == REJECTED

    def test_rejection_survives_offer_substring(self):
        assert _kind(
            "Decision",
            "Unfortunately we are unable to offer you the position. Visit our careers page for other openings.",
        ) == REJECTED

    def test_all_caps_rejection(self):
        assert _kind("UPDATE", "WE REGRET TO INFORM YOU THAT WE ARE UNABLE TO OFFER YOU THE POSITION.") == REJECTED


class TestClassifyOffer:
    def test_pleased_to_offer(self):
        assert _kind("Offer!", "We are pleased to offer you the position of Engineer.") == OFFER

    def test_extend_an_offer(self):
        assert _kind("Next steps", "We'd like to extend an offer for you to join our team.") == OFFER

    def test_offer_letter_attached(self):
        assert _kind("Welcome aboard", "Your offer letter is attached. Congratulations!") == OFFER

    def test_welcome_to_the_team(self):
        assert _kind("Great news", "Welcome to the team! We will share your start date shortly.") == OFFER


class TestClassifyInterview:
    def test_schedule_a_call(self):
        assert _kind("Invitation", "Would you like to schedule a call next week?") == INTERVIEW

    def test_phone_screen(self):
        assert _kind("Next step", "We'd like to invite you to a phone screen.") == INTERVIEW

    def test_next_steps(self):
        assert _kind("Your application", "We were impressed and want to discuss next steps.") == INTERVIEW

    def test_coding_round(self):
        assert _kind("Assessment", "Please complete the coding challenge within 5 days.") == INTERVIEW


class TestClassifyConfirmation:
    def test_application_received(self):
        assert _kind("Application received", "Thank you for applying to Acme.") == CONFIRMATION

    def test_thanks_for_your_interest(self):
        assert _kind("Got it", "Thanks for your interest in Acme. We have received your application.") == CONFIRMATION


class TestClassifyNoiseAndEdges:
    def test_out_of_office_with_unfortunately_is_other(self):
        assert _kind("Out of office", "Unfortunately, I am out of the office until Monday.") == OTHER

    def test_newsletter_footer_offer_is_other(self):
        assert _kind(
            "Weekly digest",
            "Top stories this week. Special offer inside. Unsubscribe here.",
        ) == OTHER

    def test_keep_resume_on_file_is_other(self):
        assert _kind("Thanks", "We will keep your resume on file for future roles.") == OTHER

    def test_job_alert_is_other(self):
        assert _kind("New jobs", "Job alert: 10 new AI roles matching your search.") == OTHER

    def test_auto_reply_with_strong_reject_still_rejected(self):
        assert _kind(
            "Automatic reply: Decision",
            "I am out of the office. We regret to inform you that we are unable to offer you the position.",
        ) == REJECTED

    def test_empty_inputs(self):
        assert _kind("", "") == OTHER
        assert _kind("", None) == OTHER  # type: ignore[arg-type]

    def test_unicode_and_whitespace(self):
        assert _kind("  Décision  ", "  Hélas, nous ne pouvons pas offrir… unable to offer  ") == REJECTED

    def test_no_match_is_other(self):
        assert _kind("Random", "The weather is nice today.") == OTHER


class TestResolveStatus:
    def test_precedence_order(self):
        assert resolve_status([CONFIRMATION, OFFER]) == OFFER
        assert resolve_status([REJECTED, INTERVIEW]) == INTERVIEW
        assert resolve_status([CONFIRMATION, REJECTED]) == REJECTED
        assert resolve_status([CONFIRMATION]) == CONFIRMATION

    def test_empty_and_unknown(self):
        assert resolve_status([]) == NO_RESPONSE
        assert resolve_status([OTHER]) == NO_RESPONSE


class TestQueryFor:
    def test_company_and_domain(self):
        q = query_for("Acme AI", "acme.com")
        assert "from:acme.com" in q
        assert '"Acme AI"' in q

    def test_domain_base_included(self):
        q = query_for("", "jobs.acme.io")
        assert "from:acme" in q

    def test_empty_when_nothing_given(self):
        assert query_for("", "") == ""

    def test_dedupes_parts(self):
        assert query_for("Acme", "acme.com") == 'from:acme.com OR from:acme OR "Acme"'


class TestDomainFor:
    def test_strips_board_prefixes(self):
        from jobtailor.tracking import _domain_for

        assert _domain_for("https://jobs.acme.com/role/1", "Acme") == "acme.com"
        assert _domain_for("https://boards.greenhouse.io/acme/jobs/1", "") == ""

    def test_ignores_known_boards(self):
        from jobtailor.tracking import _domain_for

        assert _domain_for("https://www.linkedin.com/jobs/view/123", "Acme") == "acme.com"


class FakeMessagesEndpoint:
    def __init__(self, msgs: list[dict]):
        self._msgs = msgs

    def list(self, userId, q, maxResults):  # noqa: ARG002
        matched = [m for m in self._msgs if m["q"] in q] if q else []
        return FakeRequest({"messages": [{"id": m["id"]} for m in matched]})

    def get(self, userId, id, format, metadataHeaders):  # noqa: ARG002
        for m in self._msgs:
            if m["id"] == id:
                return FakeRequest({
                    "id": id,
                    "snippet": m.get("snippet", ""),
                    "payload": {"headers": [
                        {"name": "From", "value": m.get("from", "")},
                        {"name": "Subject", "value": m.get("subject", "")},
                        {"name": "Date", "value": m.get("date", "")},
                    ]},
                })
        return FakeRequest({})


class FakeService:
    def __init__(self, msgs: list[dict]):
        self.users = lambda: FakeUsers(msgs)  # noqa: E731


class FakeUsers:
    def __init__(self, msgs):
        self.messages = lambda: FakeMessagesEndpoint(msgs)  # noqa: E731


class FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


@pytest.fixture
def apps(tmp_path: Path) -> list[dict]:
    return [
        {
            "url": "https://jobs.acme.com/1",
            "company": "Acme",
            "status": "submitted",
            "applied_at": "2026-08-20",
        },
        {
            "url": "https:///careers/x",
            "company": "",
            "status": "submitted",
            "applied_at": "2026-08-20",
        },
        {"url": "https://pending.com/2", "company": "Pending", "status": "prepared"},
    ]


class TestGmailTrackerSync:
    def test_sync_classifies_and_writes_file(self, tmp_path, apps):
        msgs = [
            {"id": "m1", "q": "acme", "from": "hr@acme.com", "subject": "Application received",
             "snippet": "Thank you for applying to Acme.", "date": "Thu, 20 Aug 2026"},
            {"id": "m2", "q": "acme", "from": "noreply@acme.com", "subject": "Update",
             "snippet": "Unfortunately we are unable to offer you the position.", "date": "Fri, 21 Aug 2026"},
        ]
        tracker = GmailTracker(gmail_service=FakeService(msgs), output_dir=tmp_path / "tracking")
        result = tracker.sync(apps)

        assert result["status"] == "ok"
        assert result["updated"] == 2
        acme = next(e for e in result["entries"] if e["url"].endswith("/1"))
        assert acme["status"] == REJECTED
        assert len(acme["emails"]) == 2
        assert {e["kind"] for e in acme["emails"]} == {CONFIRMATION, REJECTED}

        files = list((tmp_path / "tracking").glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert any(e["url"].endswith("/1") for e in data["apps"])

    def test_sync_skips_api_for_domainless_apps(self, tmp_path, apps):
        called: list[str] = []
        service = FakeService([])
        orig_users = service.users

        def counting_users():
            called.append("hit")
            return orig_users()

        service.users = counting_users  # type: ignore[method-assign]
        tracker = GmailTracker(gmail_service=service, output_dir=tmp_path / "tracking")
        result = tracker.sync(apps)

        assert result["status"] == "ok"
        assert result["updated"] == 2
        assert len(called) == 1  # only the app with a usable domain hit the API
        domainless = next(e for e in result["entries"] if "/careers/x" in e["url"])
        assert domainless["emails"] == []
        assert domainless["source"] is None

    def test_sync_no_apps(self, tmp_path):
        tracker = GmailTracker(output_dir=tmp_path / "tracking")
        result = tracker.sync([{"url": "https://x", "status": "prepared"}])
        assert result["status"] == "no_apps"
        assert result["entries"] == []

    def test_sync_unconfigured_without_service(self, tmp_path):
        tracker = GmailTracker(config=GmailConfig(enabled=False), output_dir=tmp_path / "tracking")
        result = tracker.sync([
            {"url": "https://jobs.acme.com/1", "company": "Acme", "status": "submitted"},
        ])
        assert result["status"] == "unconfigured"
        assert "not configured" in result["message"]

    def test_per_app_failure_isolated(self, tmp_path, apps):
        class Exploding:
            def users(self):
                raise RuntimeError("boom")

        tracker = GmailTracker(gmail_service=Exploding(), output_dir=tmp_path / "tracking")
        result = tracker.sync(apps[:1])
        assert result["status"] == "ok"
        assert result["entries"][0]["status"] == NO_RESPONSE

    def test_load_latest(self, tmp_path, apps):
        tracker = GmailTracker(gmail_service=FakeService([]), output_dir=tmp_path / "tracking")
        tracker.sync(apps[:1])
        loaded = tracker.load_latest()
        assert "https://jobs.acme.com/1" in loaded


class TestIsConfigured:
    def test_disabled(self, tmp_path):
        assert is_configured(GmailConfig(enabled=False, token_file=str(tmp_path / "t.json"))) is False

    def test_enabled_missing_token(self, tmp_path):
        assert is_configured(GmailConfig(enabled=True, token_file=str(tmp_path / "missing.json"))) is False

    def test_enabled_with_token(self, tmp_path):
        token = tmp_path / "t.json"
        token.write_text("{}")
        assert is_configured(GmailConfig(enabled=True, token_file=str(token))) is True
