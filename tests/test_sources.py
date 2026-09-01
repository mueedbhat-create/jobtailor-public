"""Tests for the LinkedIn, DailyRemote, and SimplyHired source adapters."""

from __future__ import annotations

import pytest

from jobtailor.apply import NEVER_AUTO_SOURCES, split_never_auto
from jobtailor.models import JobLead, TailoredResume
from jobtailor.sources import build_source, enabled_sources
from jobtailor.sources.dailyremote import DailyRemoteSource
from jobtailor.sources.freehire import FreehireSource
from jobtailor.sources.linkedin import LinkedInSource
from jobtailor.sources.simplyhired import SimplyHiredSource


class FakeResp:
    def __init__(self, text="", status_code=200, json=None):
        self.text = text
        self.status_code = status_code
        self._json = json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, text="", status_code=200):
        self._text = text
        self._status = status_code
        self.urls: list[str] = []

    def get(self, url):
        self.urls.append(url)
        return FakeResp(self._text, self._status)


LINKEDIN_HTML = """
<html><body><ul>
<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:1">
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/ai-engineer-at-acme-111?position=1&pageNum=0&trackingId=abc&refId=xyz">
    <span class="sr-only">AI Automation Engineer</span>
  </a>
  <h3 class="base-search-card__title">AI Automation Engineer</h3>
  <div class="base-search-card__subtitle"><a>Acme Corp</a></div>
  <span class="job-search-card__location">Remote, US</span>
</div></li>
<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:2">
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/marketing-lead-at-beta-222?position=2&trackingId=def">
    <span class="sr-only">Performance Marketing Lead</span>
  </a>
  <h3 class="base-search-card__title">Performance Marketing Lead</h3>
  <div class="base-search-card__subtitle"><a>Beta LLC</a></div>
  <span class="job-search-card__location">New York, NY</span>
</div></li>
</ul></body></html>
"""


class TestLinkedIn:
    def test_parses_cards_and_strips_tracking(self):
        client = FakeClient(LINKEDIN_HTML)
        src = LinkedInSource(client)
        leads = src._search("AI Automation", limit=10)
        assert len(leads) == 2
        first = leads[0]
        assert first.title == "AI Automation Engineer"
        assert first.company == "Acme Corp"
        assert first.location == "Remote, US"
        assert first.source == "linkedin"
        assert first.remote is True
        assert "trackingId" not in first.url
        assert "position" not in first.url
        assert first.url.endswith("/ai-engineer-at-acme-111")

    def test_respects_limit(self):
        src = LinkedInSource(FakeClient(LINKEDIN_HTML))
        assert len(src._search("x", limit=1)) == 1

    def test_search_url_has_remote_filter(self):
        client = FakeClient(LINKEDIN_HTML)
        LinkedInSource(client)._search("AI Automation", limit=5)
        assert "f_WT=2" in client.urls[0]
        assert "keywords=AI+Automation" in client.urls[0]

    def test_non_200_raises(self):
        src = LinkedInSource(FakeClient("authwall", status_code=999))
        with pytest.raises(RuntimeError):
            src._search("x", limit=5)

    def test_malformed_cards_skipped(self):
        html = '<div class="base-search-card"><h3 class="base-search-card__title">NoLink</h3></div>'
        assert LinkedInSource(FakeClient(html))._parse(html, limit=5) == []


DAILYREMOTE_HTML = """
<html><body>
<article class="lst-card">
  <h2><a href="/remote-job/ai-automation-specialist-5499514" target="_blank">AI Automation Specialist</a></h2>
  <div class="lst-card__byline">
    <span class="lst-card__locked">Company hidden</span>
    <span class="lst-card__dot">&middot;</span>
    <span>Full Time</span>
  </div>
</article>
<article class="lst-card">
  <h2><a href="/remote-job/growth-marketer-9999" target="_blank">Growth Marketer</a></h2>
  <div class="lst-card__byline">
    <span>Acme Growth Co</span>
    <span class="lst-card__dot">&middot;</span>
    <span>Full Time</span>
  </div>
</article>
</body></html>
"""


class TestDailyRemote:
    def test_parses_jobs_and_tolerates_hidden_company(self):
        src = DailyRemoteSource(FakeClient(DAILYREMOTE_HTML))
        leads = src._search("ai automation", limit=10)
        assert len(leads) == 2
        assert leads[0].company == ""
        assert leads[0].title == "AI Automation Specialist"
        assert leads[0].url == "https://dailyremote.com/remote-job/ai-automation-specialist-5499514"
        assert leads[1].company == "Acme Growth Co"

    def test_dedupes_repeat_links(self):
        html = DAILYREMOTE_HTML.replace(
            "/remote-job/growth-marketer-9999", "/remote-job/ai-automation-specialist-5499514"
        )
        src = DailyRemoteSource(FakeClient(html))
        assert len(src._search("x", limit=10)) == 1


SIMPLYHIRED_HTML = """
<html><body>
<div data-testid="serp-card-1">
  <h2><a href="/job/abc123?xkcb=track">Remote AI Automation Engineer</a></h2>
  <p><span data-testid="companyName">Acme AI</span> —
     <span data-testid="searchSerpJobLocation">Remote</span></p>
</div>
<div data-testid="serp-card-2">
  <h2><a href="/job/def456">Onsite Dev</a></h2>
  <p><span data-testid="companyName">Beta</span> —
     <span data-testid="searchSerpJobLocation">Austin, TX</span></p>
</div>
</body></html>
"""


class TestSimplyHired:
    def test_parses_and_filters_remote(self):
        src = SimplyHiredSource(FakeClient(SIMPLYHIRED_HTML))
        leads = src._search("AI", limit=10)
        assert len(leads) == 1
        lead = leads[0]
        assert lead.title == "Remote AI Automation Engineer"
        assert lead.company == "Acme AI"
        assert lead.location == "Remote"
        assert lead.url == "https://www.simplyhired.com/job/abc123"

    def test_non_200_raises(self):
        src = SimplyHiredSource(FakeClient("blocked", status_code=403))
        with pytest.raises(Exception):
            src._search("x", limit=5)


class TestNeverAutoPartition:
    def test_linkedin_goes_to_manual(self):
        resumes = [
            TailoredResume(job_url="https://www.linkedin.com/jobs/view/1", branch="apply/a"),
            TailoredResume(job_url="https://wellfound.com/jobs/2", branch="apply/b"),
            TailoredResume(job_url="", branch="apply/c"),
        ]
        sources = {"https://www.linkedin.com/jobs/view/1": "linkedin", "https://wellfound.com/jobs/2": "wellfound"}
        auto, manual = split_never_auto(resumes, sources)
        assert [r.branch for r in auto] == ["apply/b", "apply/c"]
        assert [r.branch for r in manual] == ["apply/a"]

    def test_linkedin_in_blocked_set(self):
        assert "linkedin" in NEVER_AUTO_SOURCES


class FakeJsonClient:
    """A fake httpx.Client that returns a JSON payload."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status = status_code
        self.urls: list[str] = []
        self.params: list[dict] = []

    def get(self, url, params=None):
        self.urls.append(url)
        self.params.append(params or {})
        resp = FakeResp(json=self._payload if self._status < 400 else None, status_code=self._status)
        return resp


FREEHIRE_PAYLOAD = {
    "meta": {"count": 2, "page": 1, "total": 2},
    "data": [
        {
            "public_slug": "ai-automation-specialist-acme-abc123",
            "title": "AI Automation Specialist",
            "company": "Acme AI",
            "location": "Remote",
            "posted_at": "2026-08-25",
            "work_mode": "remote",
            "url": "https://freehire.me/jobs/ai-automation-specialist-acme-abc123",
            "description": "Build AI automation workflows with n8n.",
        },
        {
            "public_slug": "performance-marketer-beta-def456",
            "title": "Performance Marketer",
            "company": "Beta Growth",
            "location": "Remote",
            "posted_at": "2026-08-24",
            "work_mode": "remote",
            "url": "https://freehire.me/jobs/performance-marketer-beta-def456",
            "description": "Run paid funnels and SEO.",
        },
    ],
}


class TestFreehire:
    def test_parses_structured_results(self):
        client = FakeJsonClient(FREEHIRE_PAYLOAD)
        src = FreehireSource(client=client)
        leads = src._search("AI Automation", limit=10)
        assert len(leads) == 2
        assert leads[0]["title"] == "AI Automation Specialist"
        assert leads[0]["company"] == "Acme AI"
        assert leads[0]["location"] == "Remote"

    def test_fetch_maps_to_jobleads_and_dedupes(self):
        client = FakeJsonClient(FREEHIRE_PAYLOAD)
        src = FreehireSource(client=client)
        leads = src.fetch(["AI Automation"], ["Acme AI"], limit=5)
        assert len(leads) == 2
        first = leads[0]
        assert isinstance(first, JobLead)
        assert first.source == "freehire"
        assert first.remote is True
        assert first.url.endswith("/jobs/ai-automation-specialist-acme-abc123")
        # duplicate across query + company collapses
        assert len({l.canonical_url() for l in leads}) == 2

    def test_requests_remote_mode(self):
        client = FakeJsonClient(FREEHIRE_PAYLOAD)
        FreehireSource(client=client)._search("x", limit=5)
        assert client.params[0].get("work_mode") == "remote"
        assert client.params[0].get("q") == "x"

    def test_registered_in_registry(self):
        from jobtailor.config import Config

        assert isinstance(build_source("freehire", Config()), FreehireSource)
        assert "freehire" in enabled_sources(Config())


class TestRegistry:
    def test_new_sources_registered(self):
        from jobtailor.config import Config

        cfg = Config()
        for name, cls in (
            ("linkedin", LinkedInSource),
            ("dailyremote", DailyRemoteSource),
            ("simplyhired", SimplyHiredSource),
            ("freehire", FreehireSource),
        ):
            assert isinstance(build_source(name, cfg), cls)

    def test_enabled_sources_respects_config(self):
        from jobtailor.config import Config

        cfg = Config()
        cfg.discovery.sources = {"linkedin": True, "wellfound": True, "dailyremote": False, "simplyhired": False}
        names = enabled_sources(cfg)
        assert "linkedin" in names
        assert "dailyremote" not in names
