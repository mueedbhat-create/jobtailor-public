"""Tests for the LLM engineer-specificity fit gate."""

from __future__ import annotations

from jobtailor.config import load_config
from jobtailor.fit import _DEFAULT_PROFILE, fit_verdict, gate_jds
from jobtailor.models import JobDescription


def _jd(title="AI Automation Engineer", company="Acme", desc="Build n8n workflows."):
    return JobDescription(url="https://x.com/1", company=company, title=title, description=desc)


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def generate(self, system, user, workdir="."):
        self.calls.append(user)
        return self.reply


class BoomLLM:
    def generate(self, system, user, workdir="."):
        raise RuntimeError("llm down")


class TestFitVerdict:
    def test_skip(self):
        v, reason = fit_verdict(FakeLLM("SKIP - requires 5 years of Kubernetes platform engineering."), "jd")
        assert v == "skip"
        assert "Kubernetes" in reason

    def test_apply(self):
        v, _ = fit_verdict(FakeLLM("APPLY - the role builds n8n workflows with LLM APIs."), "jd")
        assert v == "apply"

    def test_apply_with_leading_whitespace(self):
        v, _ = fit_verdict(FakeLLM("  APPLY — marketing automation role."), "jd")
        assert v == "apply"

    def test_garbage_defaults_to_apply(self):
        v, _ = fit_verdict(FakeLLM("This job seems... maybe?"), "jd")
        assert v == "apply"

    def test_empty_reply_defaults_to_apply(self):
        v, _ = fit_verdict(FakeLLM(""), "jd")
        assert v == "apply"

    def test_prompt_contains_rule_and_profile(self):
        llm = FakeLLM("APPLY")
        fit_verdict(llm, "the jd text", "MY PROFILE")
        assert "SKIP only if" in llm.calls[0]
        assert "MY PROFILE" in llm.calls[0]
        assert "the jd text" in llm.calls[0]

    def test_prompt_contains_location(self):
        llm = FakeLLM("APPLY")
        fit_verdict(llm, "jd", "profile", location="Srinagar, India")
        assert "Srinagar, India" in llm.calls[0]

    def test_location_rule_in_prompt(self):
        llm = FakeLLM("APPLY")
        fit_verdict(llm, "jd", "profile")
        assert "restricts where applicants can be based" in llm.calls[0]

    def test_default_profile_used_when_empty(self):
        llm = FakeLLM("APPLY")
        fit_verdict(llm, "jd", "")
        assert _DEFAULT_PROFILE in llm.calls[0]


class TestGateJds:
    def test_partitions(self):
        class ScriptedLLM:
            def __init__(self, replies):
                self.replies = list(replies)

            def generate(self, system, user, workdir="."):
                return self.replies.pop(0)

        llm = ScriptedLLM(["SKIP - pure SDE role.", "APPLY - marketing ops with LLM workflows."])
        jds = [_jd("Software Engineer", "Keeper"), _jd("Marketing Ops", "Matthews")]
        keep, skipped = gate_jds(jds, llm, "profile")
        assert [j.title for j in keep] == ["Marketing Ops"]
        assert len(skipped) == 1
        assert skipped[0][0].title == "Software Engineer"

    def test_gate_error_defaults_to_apply(self):
        keep, skipped = gate_jds([_jd()], BoomLLM(), "profile")
        assert len(keep) == 1
        assert skipped == []

    def test_echo_lines(self):
        lines = []
        gate_jds([_jd()], FakeLLM("APPLY - fits."), "p", echo=lines.append)
        assert any("[apply  ]" in l for l in lines)

    def test_gate_passes_location(self):
        seen = {}
        class Capture:
            def generate(self, system, user, workdir="."):
                seen["u"] = user
                return "APPLY"
        gate_jds([_jd()], Capture(), "p", location="Srinagar, India")
        assert "Srinagar, India" in seen["u"]


class TestConfig:
    def test_gate_flags_parse(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(
            "discovery:\n"
            "  queries:\n"
            "    - keyword: X\n"
            "  skip_engineer_specific: false\n"
            "applicant:\n"
            "  fit_profile: my summary\n"
        )
        cfg = load_config(p)
        assert cfg.discovery.skip_engineer_specific is False
        assert cfg.applicant.fit_profile == "my summary"

    def test_defaults(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("discovery:\n  queries:\n    - keyword: X\n")
        cfg = load_config(p)
        assert cfg.discovery.skip_engineer_specific is True
        assert cfg.applicant.fit_profile == ""
