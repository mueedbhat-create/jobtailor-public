"""Tests for the separate internship pipeline track."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobtailor.config import InternshipConfig, load_config


@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("""
applicant:
  full_name: "Mueed"
  email: "m@x.com"
  phone: "+91 6006628812"
  fit_profile: "marketing & AI automation"
  location: "Srinagar, India"
resume:
  source: "~/resume"
discovery:
  queries:
    - keyword: "AI Automation"
      filters: { remote: true }
  skip_engineer_specific: true
internships:
  enabled: true
  queries:
    - "paid internship AI automation"
    - "paid internship digital marketing"
  jobs_per_run: 7
  output_base: "output/internships"
llm:
  provider: "opencode"
""")
    return p


class TestInternshipConfig:
    def test_parses_internship_section(self, config_file):
        cfg = load_config(config_file)
        assert cfg.internships.enabled is True
        assert cfg.internships.queries == [
            "paid internship AI automation",
            "paid internship digital marketing",
        ]
        assert cfg.internships.jobs_per_run == 7
        assert cfg.internships.output_base == "output/internships"

    def test_defaults_disabled(self):
        cfg = InternshipConfig()
        assert cfg.enabled is False
        assert cfg.queries == []
        assert cfg.jobs_per_run == 10

    def test_disabled_when_missing(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text("resume: { source: '~/resume' }")
        cfg = load_config(p)
        assert cfg.internships.enabled is False


def test_run_pipeline_isolates_output(tmp_path, monkeypatch):
    """run_pipeline writes to the given output_base, not the default output."""
    from jobtailor.cli import run_pipeline

    captured: dict[str, object] = {}
    logs: list[str] = []

    class FakeLeadBatch:
        leads = []
        source_counts = {}

    monkeypatch.setattr("jobtailor.fetch.LeadFetcher", lambda cfg, output_dir: FakeLead())
    monkeypatch.setattr("jobtailor.cli.extract_all", lambda *a, **k: [])
    monkeypatch.setattr("jobtailor.cli._write_tailored", lambda *a, **k: None)
    monkeypatch.setattr("jobtailor.cli.tailor_all", lambda *a, **k: [])

    class FakeLead:
        def run(self, queries=None):
            captured["queries"] = queries
            return FakeLeadBatch()

    from jobtailor.config import Config, QueryConfig

    cfg = Config()
    cfg.discovery.queries = [QueryConfig(keyword="full time")]
    run_pipeline(cfg, limit=3, mode="pre_fill", queries=["paid internship AI"], output_base=str(tmp_path / "intern"), echo=logs.append)
    # fetch ran with the internship queries
    assert captured["queries"] == ["paid internship AI"]


def test_run_pipeline_passes_queries_none_for_default(monkeypatch, tmp_path):
    from jobtailor.cli import run_pipeline

    captured: dict[str, object] = {}

    class FakeLeadBatch:
        leads = []
        source_counts = {}

    class FakeLead:
        def run(self, queries=None):
            captured["queries"] = queries
            return FakeLeadBatch()

    monkeypatch.setattr("jobtailor.fetch.LeadFetcher", lambda cfg, output_dir: FakeLead())
    monkeypatch.setattr("jobtailor.cli.extract_all", lambda *a, **k: [])
    monkeypatch.setattr("jobtailor.cli._write_tailored", lambda *a, **k: None)
    monkeypatch.setattr("jobtailor.cli.tailor_all", lambda *a, **k: [])

    from jobtailor.config import Config, QueryConfig

    cfg = Config()
    cfg.discovery.queries = [QueryConfig(keyword="full time")]
    run_pipeline(cfg, limit=3, mode="pre_fill", queries=None, output_base=str(tmp_path / "out"), echo=lambda m: None)
    assert captured["queries"] is None


def test_server_applications_track_param(tmp_path, monkeypatch):
    """?track=internships reads output/internships, not output."""
    from jobtailor import server

    out = tmp_path / "output"
    intern_apps = out / "internships" / "applications"
    intern_apps.mkdir(parents=True)
    (intern_apps / "2026-08-28.json").write_text(json.dumps({
        "https://internship.example.com/1": {"status": "submitted", "branch": "apply/intern-x", "applied_at": "2026-08-28"},
    }))

    monkeypatch.setattr(server, "OUTPUT", out)

    res = server.applications(track="internships")
    flat = [a for day in res["days"].values() for a in day]
    assert len(flat) == 1
    assert flat[0]["url"] == "https://internship.example.com/1"
    assert flat[0]["status"] == "submitted"

    # default track reads the (empty) jobs base
    res2 = server.applications(track="jobs")
    flat2 = [a for day in res2["days"].values() for a in day]
    assert flat2 == []