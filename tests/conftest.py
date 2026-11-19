"""Test-wide safety net: no test may ever open a real browser.

An old smoke test sent https://x.com/job/0 to macOS `open`, which popped
X tabs in the user's Chrome every time the suite ran. These autouse guards
make any real browser launch fail the test instead.
"""

from __future__ import annotations

import subprocess

import pytest

_BLOCKED = {"open", "ego-browser", "osascript", "xdg-open"}


def _first_arg(args, kwargs):
    cmd = args[0] if args else kwargs.get("args")
    if isinstance(cmd, (list, tuple)) and cmd:
        return str(cmd[0]).rsplit("/", 1)[-1]
    if isinstance(cmd, str):
        return cmd.split()[0].rsplit("/", 1)[-1] if cmd.strip() else ""
    return ""


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    real_run, real_popen = subprocess.run, subprocess.Popen

    def guarded_run(*args, **kwargs):
        if _first_arg(args, kwargs) in _BLOCKED:
            raise AssertionError(f"test tried to launch a real browser: {args[:1]}")
        return real_run(*args, **kwargs)

    class GuardedPopen(real_popen):
        def __init__(self, *args, **kwargs):
            if _first_arg(args, kwargs) in _BLOCKED:
                raise AssertionError(f"test tried to launch a real browser: {args[:1]}")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)

    import webbrowser

    def no_webbrowser(*a, **k):
        raise AssertionError("test tried to open a real browser via webbrowser")

    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, no_webbrowser)


@pytest.fixture(autouse=True)
def _no_real_ai(monkeypatch):
    """No test may spend the user's free AI allowance."""
    from jobtailor import llm

    def blocked(self, *a, **k):
        raise llm.LLMError("real AI call blocked in tests")

    for name in ("_via_zen", "_via_opencode", "_via_ollama", "_via_openai_compatible"):
        monkeypatch.setattr(llm.LLMClient, name, blocked)
    monkeypatch.setattr(llm, "_QUOTA_EXHAUSTED", False)
    llm.set_budget(0)
