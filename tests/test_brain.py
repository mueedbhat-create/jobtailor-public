"""One-call engine: JD compaction, hard rules, JSON parsing, budget, metering."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from jobtailor import llm as llm_mod
from jobtailor.brain import (ResumeBank, _parse_json, build_prompt, compact_jd, hard_skip,
                             plain_to_tex, render, Plan)
from jobtailor.models import JobDescription

EXP = r"""\begin{cventries}
\cventry
    {Marketing Strategist \& Copywriter}
    {Northwind Paints}
    {Pune, India}
    {2022 - 2026}
    {
      \begin{cvitems}
        \item{Lifted \textbf{brand visibility by 35\%} with data-driven strategies.}
        \item{Ran \textbf{market research} and competitor analysis.}
        \item{Built n8n automations for lead capture.}
      \end{cvitems}
    }
\end{cventries}
"""
SKILLS = "\\begin{cvskills}\n\n\\cvskill\n    {Marketing}\n    {Market Research, SEO, Content Strategy}\n\n\\end{cvskills}\n"


@pytest.fixture
def bank(tmp_path):
    root = tmp_path / "r"
    (root / "resume").mkdir(parents=True)
    (root / "resume.tex").write_text("main")
    (root / "resume" / "experience.tex").write_text(EXP)
    (root / "resume" / "skills.tex").write_text(SKILLS)
    return ResumeBank.load(root)


def jd(desc, title="Marketing Manager"):
    return JobDescription("https://j/1", "Acme", title, desc, [])


def test_bank_parses_and_renders_identically(bank):
    assert [b.id for b in bank.entries[0].bullets] == ["E1.1", "E1.2", "E1.3"]
    assert bank.skills[0].items == ["Market Research", "SEO", "Content Strategy"]
    exp, sk, rep = render(bank, Plan())
    assert exp == bank.experience_tex and sk == bank.skills_tex and not rep.changed


def test_prompt_is_small(bank):
    p = build_prompt(jd("x " * 5000), bank, "profile " * 200, "Pune, India", want_note=True)
    assert len(p) < 5500  # JD capped, profile capped: ~1.4k tokens


def test_rewrite_must_keep_numbers_and_tools(bank):
    plan = Plan(rewrite={
        "E1.1": "Lifted brand visibility by 50% with data-driven strategies.",
        "E1.3": "Built automations for lead capture and nurturing.",  # dropped n8n
        "E1.2": "Led **market research** and competitor analysis for campaigns.",
    })
    exp, _, rep = render(bank, plan)
    assert rep.rewritten == ["E1.2"]
    assert "\\textbf{market research} and competitor analysis for campaigns" in exp
    assert "35\\%" in exp


def test_compact_jd_drops_boilerplate():
    page = "\n".join([
        "Acme - Careers", "Sign in", "About us", "We are a fun company founded in 1999.",
        "Responsibilities", "Run paid campaigns on Meta.", "Write landing page copy.",
        "Requirements", "3 years of performance marketing.", "Strong copywriting.",
        "Benefits", "Free snacks", "Unlimited PTO",
        "Equal opportunity employer. We value diversity.",
    ] + [f"Own the growth funnel and report weekly on metric number {i}." for i in range(10)])
    out = compact_jd(page)
    assert "Run paid campaigns" in out and "Strong copywriting" in out
    assert "snacks" not in out and "Sign in" not in out and "Equal opportunity" not in out


def test_hard_skip_engineering_and_location():
    assert hard_skip(jd("You have 5+ years of software development experience.")) != ""
    assert hard_skip(jd("US only. Remote marketing role."), "Pune, India") != ""
    assert hard_skip(jd("Remote, worldwide. US only payroll is not required."), "Pune, India") == ""
    assert hard_skip(jd("Must be based in the US or India."), "Pune, India") == ""
    assert hard_skip(jd("3 years of performance marketing."), "Pune, India") == ""


def test_parse_json_tolerates_fences_think_and_trailing_commas():
    assert _parse_json('<think>hmm</think>```json\n{"apply": true, "order": ["E1.1",],}\n```') == {
        "apply": True, "order": ["E1.1"]}
    with pytest.raises(ValueError):
        _parse_json("no json here")


def test_plain_to_tex_escapes():
    assert plain_to_tex("ROI up 15% & **CTR** $5") == "ROI up 15\\% \\& \\textbf{CTR} \\$5"


# -- llm: direct free endpoint, metering, budget ----------------------------


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _unblock(monkeypatch):
    monkeypatch.setattr(llm_mod.LLMClient, "_via_zen", _REAL_ZEN)


_REAL_ZEN = llm_mod.LLMClient._via_zen


def test_zen_meters_real_usage(monkeypatch):
    _unblock(monkeypatch)
    body = {"choices": [{"message": {"content": '{"apply":true}'}}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 300}}
    sent = {}

    def fake_urlopen(req, timeout=0):
        sent["auth"] = req.headers.get("Authorization")
        sent["model"] = json.loads(req.data)["model"]
        return _Resp(json.dumps(body).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    llm_mod.set_budget(10_000)
    c = llm_mod.LLMClient(llm_mod.LLMConfig(provider="zen", model="opencode/deepseek-v4.1-flash-free"))
    assert c.generate("s", "u") == '{"apply":true}'
    assert sent == {"auth": "Bearer public", "model": "deepseek-v4.1-flash-free"}
    assert llm_mod.USAGE.total == 1800 and llm_mod.USAGE.calls == 1


def test_zen_refuses_paid_models():
    c = llm_mod.LLMClient(llm_mod.LLMConfig(provider="zen", model="claude-sonnet"))
    with pytest.raises(llm_mod.LLMError):
        _REAL_ZEN(c, "s", "u", "claude-sonnet")


def test_zen_free_limit_stops_run(monkeypatch):
    _unblock(monkeypatch)
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b'{"type":"FreeUsageLimitError"}'))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    c = llm_mod.LLMClient(llm_mod.LLMConfig(provider="zen"))
    for _ in range(3):
        with pytest.raises(llm_mod.QuotaExhausted):
            c.generate("s", "u")
    assert len(calls) == 1  # later calls fail fast, no request sent


def test_budget_cap_blocks_before_sending(monkeypatch):
    _unblock(monkeypatch)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("should not send"))
    llm_mod.set_budget(100)
    c = llm_mod.LLMClient(llm_mod.LLMConfig(provider="zen"))
    with pytest.raises(llm_mod.BudgetExceeded):
        c.generate("s", "x" * 2000)


def test_only_listings_first_seen_today(tmp_path):
    import datetime as dt

    from jobtailor.cli import _urls_seen_before_today

    leads = tmp_path / "leads"
    leads.mkdir()
    old = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    today = dt.date.today().isoformat()
    (leads / f"{old}.json").write_text(json.dumps({"leads": [{"url": "https://j/old"}]}))
    (leads / f"{today}.json").write_text(json.dumps({"leads": [{"url": "https://j/new"}]}))
    (leads / "fresh.json").write_text("not a dated file")
    assert _urls_seen_before_today(leads) == {"https://j/old"}


def test_listing_age_checks():
    import datetime as dt

    from jobtailor.models import JobLead
    from jobtailor.prefilter import stale_text, too_old

    today = dt.date(2026, 11, 20)
    lead = lambda posted: JobLead("u", "c", "Marketing Manager", "s", posted=posted)  # noqa: E731
    assert too_old(lead("2026-10-01"), 21, today)
    assert too_old(lead("2026-11-10"), 21, today) == ""
    assert too_old(lead(""), 21, today) == ""  # unknown date: keep, check text later
    assert stale_text("cancan on May 1, 2024 | parent", 21, today)
    assert stale_text("Posted November 12, 2026. Founded 2019.", 21, today) == ""
    assert stale_text("no dates here", 21, today) == ""


def test_himalayas_lead_parsing():
    from jobtailor.sources.himalayas import HimalayasSource

    lead = HimalayasSource()._to_lead({
        "title": "Digital Marketing Manager", "companyName": "Acme", "pubDate": 1795046400,
        "applicationLink": "https://himalayas.app/companies/acme/jobs/dmm",
        "locationRestrictions": ["India"], "description": "<p>Run campaigns</p>"})
    assert lead.posted == "2026-11-19" and lead.location == "India"
    assert lead.description.startswith("<p>")
    assert HimalayasSource()._to_lead({"title": "x"}) is None
