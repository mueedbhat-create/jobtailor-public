"""Tests for the setup wizard and auto-sync wiring."""

from __future__ import annotations

from pathlib import Path

import yaml

from jobtailor.config import load_config
from jobtailor.init_setup import DepCheck, build_config, check_dependencies, validate_resume_dir
from jobtailor.tracking import maybe_auto_sync


class TestValidateResumeDir:
    def test_missing_dir(self, tmp_path):
        p, err = validate_resume_dir(str(tmp_path / "nope"))
        assert p is None
        assert "does not exist" in err

    def test_missing_resume_tex(self, tmp_path):
        p, err = validate_resume_dir(str(tmp_path))
        assert p is None
        assert "resume.tex" in err

    def test_valid(self, tmp_path):
        (tmp_path / "resume.tex").write_text("\\cvsection{X}\n")
        p, err = validate_resume_dir(str(tmp_path))
        assert p == tmp_path
        assert err == ""

    def test_expands_home(self):
        p, err = validate_resume_dir("~")
        assert err == "" or p is None
        if err == "":
            assert "~" not in str(p)


class TestCheckDependencies:
    def test_reports_all_three(self, monkeypatch):
        monkeypatch.setattr(
            "jobtailor.init_setup.shutil.which",
            lambda name: "/usr/bin/" + name if name == "tectonic" else None,
        )
        checks = check_dependencies()
        names = [c.name for c in checks]
        assert len(checks) == 3
        assert any("tectonic" in n for n in names)
        tectonic = next(c for c in checks if "tectonic" in c.name)
        assert tectonic.ok is True
        others = [c for c in checks if not c.ok]
        assert all(c.hint for c in others)

    def test_all_missing(self, monkeypatch):
        monkeypatch.setattr("jobtailor.init_setup.shutil.which", lambda _: None)
        assert all(not c.ok for c in check_dependencies())


class TestBuildConfig:
    def _answers(self) -> dict:
        return {
            "resume_source": "/Users/x/resume",
            "keywords": ["AI Automation Engineer", "Performance Marketing"],
            "companies": ["Anarchy Labs"],
            "jobs_per_run": 20,
            "times": ["07:00", "12:30"],
            "apply_mode": "full_auto",
            "adzuna_id": "id123",
            "adzuna_key": "key456",
            "gmail": {
                "enabled": True,
                "client_secrets_file": "client_secret.json",
                "token_file": "gmail_token.json",
                "auto_sync": True,
                "sync_interval_minutes": 30,
            },
        }

    def test_roundtrip_parses_and_loads(self, tmp_path):
        text = build_config(self._answers())
        data = yaml.safe_load(text)
        assert data["apply"]["mode"] == "full_auto"
        assert data["schedule"]["times"] == ["07:00", "12:30"]

        p = tmp_path / "config.yaml"
        p.write_text(text)
        cfg = load_config(p)
        assert cfg.apply.mode == "full_auto"
        assert cfg.gmail.auto_sync is True
        assert cfg.gmail.sync_interval_minutes == 30
        assert cfg.schedule.jobs_per_run == 20
        assert cfg.discovery.queries[0].keyword == "AI Automation Engineer"
        assert cfg.discovery.queries[0].filters == {"remote": True}

    def test_minimal_answers_defaults(self):
        text = build_config({"resume_source": "~/resume"})
        data = yaml.safe_load(text)
        assert data["apply"]["mode"] == "full_auto"
        assert data["gmail"] == {"enabled": False}
        assert data["schedule"]["times"] == ["07:00"]
        assert data["adzuna"]["app_id"] == ""


class TestMaybeAutoSync:
    def _cfg(self, tmp_path, enabled=True, auto=True):
        from jobtailor.config import GmailConfig

        return GmailConfig(
            enabled=enabled,
            auto_sync=auto,
            token_file=str(tmp_path / "t.json"),
        )

    def test_disabled_returns_none(self, tmp_path):
        assert maybe_auto_sync(self._cfg(tmp_path, enabled=False), []) is None
        assert maybe_auto_sync(self._cfg(tmp_path, auto=False), []) is None

    def test_enabled_runs_sync(self, tmp_path, monkeypatch):
        calls = []

        class FakeTracker:
            def __init__(self, cfg, **kw):
                calls.append("init")

            def sync(self, apps):
                calls.append(apps)
                return {"status": "ok", "message": "Tracked 1", "updated": 1, "entries": [], "last_synced": None}

        monkeypatch.setattr("jobtailor.tracking.GmailTracker", FakeTracker)
        lines = []
        result = maybe_auto_sync(
            self._cfg(tmp_path), [{"url": "https://x", "status": "submitted"}], echo=lines.append
        )
        assert result["status"] == "ok"
        assert calls[1] == [{"url": "https://x", "status": "submitted"}]
        assert any("Tracked 1" in l for l in lines)

    def test_unconfigured_sync_returns_unconfigured(self, tmp_path):
        from jobtailor.tracking import GmailTracker

        tracker = GmailTracker(self._cfg(tmp_path), output_dir=tmp_path / "tr")
        result = maybe_auto_sync(self._cfg(tmp_path), [{"url": "https://x", "status": "submitted"}])
        assert result is not None
        assert result["status"] == "unconfigured"


class TestServerAutoSync:
    def test_auto_sync_once_disabled(self, tmp_path, monkeypatch):
        from jobtailor import server

        cfg = tmp_path / "config.yaml"
        cfg.write_text("gmail:\n  enabled: false\n")
        monkeypatch.chdir(tmp_path)
        assert server._auto_sync_once() is None

    def test_auto_sync_once_no_config(self, tmp_path, monkeypatch):
        from jobtailor import server

        monkeypatch.chdir(tmp_path)
        assert server._auto_sync_once() is None

    def test_auto_sync_once_enabled(self, tmp_path, monkeypatch):
        from jobtailor import server

        (tmp_path / "output" / "applications").mkdir(parents=True)
        (tmp_path / "output" / "applications" / "d.json").write_text(
            '{"https://jobs.acme.com/1": {"status": "submitted", "applied_at": "2026-08-24"}}'
        )
        (tmp_path / "config.yaml").write_text(
            "gmail:\n  enabled: true\n  auto_sync: true\n  token_file: t.json\n"
        )
        (tmp_path / "t.json").write_text("{}")
        monkeypatch.chdir(tmp_path)

        seen = {}

        def fake_sync(self, apps):
            seen["apps"] = apps
            return {"status": "ok", "message": "m", "updated": 1, "entries": [], "last_synced": None}

        monkeypatch.setattr("jobtailor.tracking.GmailTracker.sync", fake_sync)
        result = server._auto_sync_once()
        assert result["status"] == "ok"
        assert seen["apps"][0]["url"] == "https://jobs.acme.com/1"
