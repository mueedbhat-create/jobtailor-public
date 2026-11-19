"""Tests for the token-waste fixes: free pre-filter, form probe, honest
statuses, and LaTeX auto-repair. No test here touches a real browser."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jobtailor.apply import ApplicationQueue
from jobtailor.models import JobLead, TailoredResume
from jobtailor.prefilter import classify, prefilter_leads
from jobtailor.probe import ProbeResult, _classify, probe_until

LOC = "Pune, India"


def lead(title, location="", url=None):
    return JobLead(url or f"https://jobs.example/{abs(hash(title + location))}", "Co", title, "src",
                   location=location)


class TestPrefilter:
    @pytest.mark.parametrize("title,location", [
        ("Performance Marketing Manager", "Remote"),
        ("Digital Marketing Intern", "Remote (worldwide)"),
        ("Marketing Intern", "India"),
        ("Marketing Ops & AI Automation Coordinator", "Gurugram, Haryana"),
        ("Social Media Intern", "Remote job"),
    ])
    def test_keeps(self, title, location):
        assert classify(lead(title, location), LOC) == ""

    @pytest.mark.parametrize("title,location,why", [
        ("Store Manager", "", "not a target role"),
        ("Plant Fitter", "Bedford", "not a target role"),
        ("Staff Software Engineer", "Remote", "not a target role"),
        ("AI Automation Engineer (n8n / APIs)", "", "engineering role"),
        ("GTM Engineer", "", "engineering role"),
        ("Machine Learning Engineer Intern - Marketing Data", "", "engineering role"),
        ("Paid Media Manager US", "", "region-locked title"),
        ("Product Support Engineer - NAMER", "", "not a target role"),
        ("Marketing Intern", "United States - Remote", "location-locked"),
        ("Content & Marketing Intern", "Remote in US", "location-locked"),
        ("Performance Marketing Manager", "New York, NY (Remote)", "location-locked"),
    ])
    def test_drops(self, title, location, why):
        assert classify(lead(title, location), LOC).startswith(why)

    def test_split(self):
        kept, dropped = prefilter_leads([lead("Growth Marketer", "Remote"), lead("Store Manager")], LOC)
        assert [k.title for k in kept] == ["Growth Marketer"]
        assert dropped[0][1] == "not a target role"


class TestProbe:
    def test_classify(self):
        assert _classify("u", {"fields": 6, "files": 1, "url": "f"}).status == "ready"
        assert _classify("u", {"fields": 0, "files": 1}).status == "ready"
        assert _classify("u", {"fields": 3, "password": True}).status == "needs_login"
        assert _classify("u", {"fields": 0, "loginUrl": True}).status == "needs_login"
        r = _classify("u", {"fields": 0, "files": 0, "emailApply": "hr@co.com"})
        assert (r.status, r.email) == ("email_apply", "hr@co.com")
        assert _classify("u", {"fields": 1, "files": 0}).status == "no_form"
        assert _classify("u", {"fields": 5, "captcha": True}).status == "no_form"
        assert _classify("u", {}).status == "error"

    def test_probe_until_stops_when_enough_ready(self):
        leads = [lead(f"Marketing {i}", url=f"https://j/{i}") for i in range(10)]
        calls = []

        def fake(url):
            calls.append(url)
            n = int(url.rsplit("/", 1)[1])
            return ProbeResult(url, "ready" if n % 2 else "no_form", form_url=url + "/apply")

        ready, not_ready = probe_until(leads, want=2, max_probes=10, prober=fake)
        assert [r.form_url for _, r in ready] == ["https://j/1/apply", "https://j/3/apply"]
        assert len(calls) == 4  # stopped as soon as 2 were ready

    def test_probe_until_respects_cap(self):
        leads = [lead(f"Marketing {i}", url=f"https://j/{i}") for i in range(10)]
        ready, not_ready = probe_until(leads, want=5, max_probes=3,
                                       prober=lambda u: ProbeResult(u, "no_form"))
        assert ready == [] and len(not_ready) == 3


class TestHonestStatus:
    @pytest.mark.parametrize("res,submit,expected", [
        ({"matched_fields": [], "pdf_uploaded": False}, False, "no_form"),
        ({"matched_fields": [["email", "x"]], "pdf_uploaded": False}, False, "prepared"),
        ({"matched_fields": [], "pdf_uploaded": True}, False, "prepared"),
        ({"matched_fields": [], "pdf_uploaded": False, "submitted": True}, True, "no_form"),
        ({"matched_fields": [["e", "x"]], "submit_clicked": True, "submitted": False}, True, "submit_unconfirmed"),
        ({"matched_fields": [["e", "x"]], "submit_clicked": True, "submitted": True}, True, "submitted"),
        ({"matched_fields": [["e", "x"]], "submit_clicked": False}, True, "prepared"),
    ])
    def test_status(self, res, submit, expected):
        assert ApplicationQueue._honest_status(res, submit) == expected

    def test_auto_apply_uses_form_url_and_honest_status(self, tmp_path, monkeypatch):
        seen = []

        class FakeSub:
            def __init__(self, profile):
                pass

            def apply_structured(self, url, pdf, submit=False, note=""):
                seen.append((url, note))
                return {"matched_fields": [], "pdf_uploaded": False, "file_inputs_found": 0}

        monkeypatch.setattr("jobtailor.apply.AutoSubmitter.__init__", FakeSub.__init__)
        monkeypatch.setattr("jobtailor.apply.AutoSubmitter.apply_structured", FakeSub.apply_structured)
        q = ApplicationQueue(state_dir=tmp_path)
        r = TailoredResume(job_url="https://j/1", branch="apply/j1", pdf_path=Path("/tmp/x.pdf"))
        out = q.auto_apply([r], submit=True, form_urls={"https://j/1": "https://ats/form/1"},
                           notes={"https://j/1": "I build n8n automations."})
        # form URL first; nothing filled there -> retry from the job page
        assert seen == [("https://ats/form/1", "I build n8n automations."),
                        ("https://j/1", "I build n8n automations.")]
        assert out[0]["status"] == "no_form"  # nothing filled -> never "submitted"

    def test_record_and_known_urls(self, tmp_path):
        q = ApplicationQueue(state_dir=tmp_path)
        q.record("https://j/9", "email_apply", note="hr@co.com", email="hr@co.com")
        assert "https://j/9" in q.known_urls()
        assert q.status()[0]["status"] == "email_apply"


class TestLatexRepair:
    def test_restores_only_the_broken_section(self, tmp_path, monkeypatch):
        from jobtailor.pdf import PdfExporter, PdfVerifier

        orig = tmp_path / "orig"
        (orig / "resume").mkdir(parents=True)
        for name in ("experience", "skills", "education"):
            (orig / "resume" / f"{name}.tex").write_text(f"ORIGINAL {name}")
        branch = tmp_path / "tailored" / "apply" / "j1"
        (branch / "resume").mkdir(parents=True)
        (branch / "resume.tex").write_text("main")
        for name in ("experience", "skills", "education"):
            (branch / "resume" / f"{name}.tex").write_text(f"TAILORED {name}")

        def fake_run(self, *cmd, cwd):
            edu = (Path(cwd) / "resume" / "education.tex").read_text()
            if edu.startswith("TAILORED"):
                raise subprocess.CalledProcessError(
                    1, cmd, output="warning resume/skills.tex:3: Underfull \\hbox",
                    stderr="error: resume/education.tex:32: Misplaced alignment tab character &")
            (Path(cwd) / "resume.pdf").write_bytes(b"%PDF")

        monkeypatch.setattr(PdfExporter, "_run", fake_run)
        monkeypatch.setattr(PdfExporter, "_verify", lambda self, d, r: None)
        monkeypatch.setattr("jobtailor.pdf._resolve_tectonic", lambda: "tectonic")
        ex = PdfExporter(tmp_path / "tailored", tmp_path / "out", verifier=PdfVerifier([]),
                         original_dir=orig)
        dest = ex.export(TailoredResume(job_url="u", branch="apply/j1"))
        assert dest.exists()
        assert ex.repaired["apply/j1"] == ["resume/education.tex"]
        assert (branch / "resume" / "education.tex").read_text() == "ORIGINAL education"
        assert (branch / "resume" / "experience.tex").read_text() == "TAILORED experience"
        assert (branch / "resume" / "skills.tex").read_text() == "TAILORED skills"


@pytest.mark.parametrize("title", [
    "Staff Web Engineer, Marketing",
    "Software Engineer – AI Automation (Internal Tools)",
    "Senior Data Engineer, Growth",
])
def test_hard_engineering_titles_dropped(title):
    assert classify(lead(title), LOC) == "engineering role"


@pytest.mark.parametrize("title", ["AI Automation Engineer", "Marketing Engineer", "GTM Engineer, Marketing",
                                   "Senior Technical Marketing Engineer"])
def test_engineering_titles_dropped_even_with_marketing_words(title):
    # 2026-11-18: user is not an engineer and does not want engineering roles.
    assert classify(lead(title), LOC) == "engineering role"


@pytest.mark.parametrize("title", ["AI Automation Specialist", "Marketing Automation Manager",
                                   "Growth Automation Lead", "Marketing Operations Coordinator"])
def test_non_engineering_automation_titles_kept(title):
    assert classify(lead(title), LOC) == ""


def test_note_rejects_placeholders_and_strips_greeting():
    from jobtailor.brain import check_note

    assert check_note("Dear [Hiring Manager], I am great.", "t", "c", "") == ""
    note = check_note("Dear Team,\nI built n8n automations at Acme Labs and ran campaigns.", "t", "c", "")
    assert note.startswith("I built n8n")


def test_probe_accepts_note_only_forms():
    assert _classify("u", {"fields": 1, "textareas": 1, "sendBtn": True}).status == "ready"
    assert _classify("u", {"fields": 1, "textareas": 1, "sendBtn": False}).status == "no_form"


def test_probe_location_locked_beats_ready():
    r = _classify("u", {"fields": 5, "textareas": 1, "sendBtn": True, "locked": True})
    assert r.status == "location_locked"
