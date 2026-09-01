"""Tests for the JobTailor dashboard API server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import jobtailor.server as server
from jobtailor.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def output(tmp_path: Path, monkeypatch):
    out = tmp_path / "output"
    monkeypatch.setattr(server, "OUTPUT", out)
    return out


def _seed_leads(out: Path):
    leads = out / "leads"
    leads.mkdir(parents=True)
    (leads / "2026-08-20.json").write_text(json.dumps({
        "date": "2026-08-20",
        "leads": [
            {"url": "https://jobs.acme.com/1", "company": "Acme", "title": "AI Engineer",
             "source": "adzuna", "remote": True, "location": "Remote (US)"},
        ],
    }))


def _seed_apps(out: Path):
    apps = out / "applications"
    apps.mkdir(parents=True)
    (apps / "2026-08-20.json").write_text(json.dumps({
        "https://jobs.acme.com/1": {
            "status": "submitted",
            "branch": "apply/ai-engineer-acme",
            "pdf": "/tmp/apply.pdf",
            "fields": {"email": "m@x.com", "full_name": "Mueed"},
            "note": "submitted; matched fields: email=m@x.com",
            "applied_at": "2026-08-20",
        },
    }))


def _seed_tracking(out: Path):
    tr = out / "tracking"
    tr.mkdir(parents=True)
    (tr / "2026-08-21.json").write_text(json.dumps({
        "date": "2026-08-21",
        "apps": [{
            "url": "https://jobs.acme.com/1",
            "status": "confirmation",
            "last_checked": "2026-08-21T07:30:00+00:00",
            "source": "gmail",
            "emails": [{"id": "m1", "from": "hr@acme.com", "subject": "Application received",
                        "snippet": "Thank you for applying.", "date": "Thu", "kind": "confirmation"}],
        }],
    }))


class TestApplicationsEndpoint:
    def test_enriched_join(self, client, output):
        _seed_leads(output)
        _seed_apps(output)
        _seed_tracking(output)
        res = client.get("/api/applications")
        assert res.status_code == 200
        entry = res.json()["days"]["2026-08-20"][0]
        assert entry["company"] == "Acme"
        assert entry["title"] == "AI Engineer"
        assert entry["pdf_url"] == "/api/resumes/apply/ai-engineer-acme"
        assert entry["fields"]["email"] == "m@x.com"
        assert entry["tracking"]["status"] == "confirmation"

    def test_full_contract_with_missing_data(self, client, output):
        output.mkdir(parents=True)
        (output / "applications").mkdir()
        (output / "applications" / "d1.json").write_text(json.dumps({
            "https://x.com/1": {"status": "prepared"},
        }))
        res = client.get("/api/applications")
        entry = res.json()["days"]["d1"][0]
        for key in ("url", "status", "branch", "pdf", "pdf_url", "opened_at",
                    "applied_at", "note", "fields", "company", "title", "source",
                    "location", "remote", "tracking"):
            assert key in entry, f"missing {key}"
        assert entry["fields"] == {}
        assert entry["tracking"] is None

    def test_skips_corrupt_entries_without_500(self, client, output):
        (output / "applications").mkdir(parents=True)
        (output / "applications" / "bad1.json").write_text('{"url": "this is not a dict"}')
        (output / "applications" / "bad2.json").write_text("not json at all")
        (output / "applications" / "bad3.json").write_text('[1, 2, 3]')
        res = client.get("/api/applications")
        assert res.status_code == 200
        assert res.json() == {"days": {}}

    def test_missing_dirs(self, client, output):
        assert client.get("/api/applications").json() == {"days": {}}
        summary = client.get("/api/tracking")
        assert summary.status_code == 200
        assert summary.json()["totals"]["applied"] == 0


class TestTrackingEndpoint:
    def test_totals(self, client, output):
        _seed_leads(output)
        _seed_apps(output)
        _seed_tracking(output)
        data = client.get("/api/tracking").json()
        assert data["totals"]["applied"] == 1
        assert data["totals"]["confirmation"] == 1
        assert data["by_status"]["submitted"] == 1
        assert data["last_synced"] == "2026-08-21T07:30:00+00:00"


class TestTrackingSync:
    def test_unconfigured_no_config_file(self, client, output, monkeypatch):
        output.mkdir(parents=True)
        monkeypatch.chdir(output)
        res = client.post("/api/tracking/sync")
        body = res.json()
        assert res.status_code == 200
        assert body["status"] == "unconfigured"
        for key in ("message", "updated", "entries", "last_synced"):
            assert key in body

    def test_disabled_in_config(self, client, output, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("gmail:\n  enabled: false\n")
        monkeypatch.chdir(tmp_path)
        body = client.post("/api/tracking/sync").json()
        assert body["status"] == "unconfigured"

    def test_enabled_but_token_missing(self, client, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("gmail:\n  enabled: true\n  token_file: missing-token.json\n")
        monkeypatch.chdir(tmp_path)
        body = client.post("/api/tracking/sync").json()
        assert body["status"] == "unconfigured"
        assert "token" in body["message"].lower()

    def test_runs_with_fake_service(self, client, tmp_path, monkeypatch):
        from test_tracking import FakeService

        cfg = tmp_path / "config.yaml"
        cfg.write_text("gmail:\n  enabled: true\n  token_file: t.json\n")
        (tmp_path / "t.json").write_text("{}")
        (tmp_path / "output" / "applications").mkdir(parents=True)
        (tmp_path / "output" / "applications" / "d.json").write_text(json.dumps({
            "https://jobs.acme.com/1": {
                "status": "submitted",
                "applied_at": "2026-08-20",
            },
        }))
        monkeypatch.chdir(tmp_path)

        msgs = [{"id": "m1", "q": "acme", "from": "hr@acme.com", "subject": "Received",
                 "snippet": "Thank you for applying to Acme."}]
        monkeypatch.setattr(
            "jobtailor.tracking.GmailTracker._build_service", lambda self: FakeService(msgs)
        )
        body = client.post("/api/tracking/sync").json()
        assert body["status"] == "ok"
        assert body["updated"] == 1
        assert body["entries"][0]["status"] == "confirmation"
        assert body["last_synced"]


class TestResumeTraversal:
    def _seed_pdf(self, output: Path) -> Path:
        resumes = output / "resumes"
        resumes.mkdir(parents=True, exist_ok=True)
        pdf = resumes / "apply-job.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return pdf

    def test_serves_valid_branch(self, client, output):
        self._seed_pdf(output)
        res = client.get("/api/resumes/apply-job")
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF")

    @pytest.mark.parametrize("branch", [
        "..%2F..%2Fsecret",
        "..",
        "a/../b",
        "%2e%2e%2fx",
        "~root",
    ])
    def test_rejects_traversal(self, client, output, branch):
        self._seed_pdf(output)
        secret = output / "secret.txt"
        secret.write_text("top secret")
        res = client.get(f"/api/resumes/{branch}")
        assert res.status_code in (400, 404), f"{branch} not rejected: {res.status_code}"

    def test_direct_handler_rejects_dotdot(self, client, output, monkeypatch):
        monkeypatch.setattr(server, "OUTPUT", output)
        with pytest.raises(Exception):
            server.resume_pdf("../../secret")

    def test_404_when_missing(self, client, output):
        res = client.get("/api/resumes/nope")
        assert res.status_code == 404


class TestExistingEndpoints:
    def test_health(self, client, output):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_jobs_empty(self, client, output):
        assert client.get("/api/jobs").json() == {"days": {}}

    def test_run_status_shape(self, client, output):
        body = client.get("/api/run/status").json()
        for key in ("running", "status", "output"):
            assert key in body
