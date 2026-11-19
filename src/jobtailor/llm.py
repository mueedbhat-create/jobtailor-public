"""LLM provider abstraction.

Default provider "zen": calls OpenCode Zen's free models over HTTPS directly.
That skips the opencode CLI, which wraps every call in its own system prompt
and tool list (~20k extra tokens per call), and returns exact token counts.

Every call is metered (``USAGE``) and capped per run (``set_budget``): a run
can never spend more than its budget, whatever goes wrong.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

# The opencode CLI is NOT safe to run concurrently: parallel `opencode run`
# processes contend for the same session/db, all but one fail, and LLMClient
# silently falls back to Ollama (2026-11-18: tailor_all uses a thread pool, so
# every batch after the first ran on local qwen2.5 at ~1/20th the speed).
_OPENCODE_LOCK = threading.Lock()

# Set once opencode reports the account's free quota is used up. Every later
# call in this run fails fast instead of spawning opencode again, and there is
# NO automatic Ollama fallback (user rule 2026-11-18: ask first).
_QUOTA_EXHAUSTED = False


class QuotaExhausted(Exception):
    """opencode's free usage limit is reached; stop the run."""


class BudgetExceeded(QuotaExhausted):
    """This run's token budget is spent; stop the run."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False  # True when a provider gave no counts
    budget: int = 0  # 0 = no cap

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def summary(self) -> str:
        est = "~" if self.estimated else ""
        cap = f" of {self.budget:,} budget" if self.budget else ""
        return (f"{self.calls} AI call(s), {est}{self.total:,} tokens{cap} "
                f"({est}{self.input_tokens:,} in / {est}{self.output_tokens:,} out)")


USAGE = Usage()
_USAGE_LOCK = threading.Lock()


def set_budget(tokens: int) -> None:
    """Start a fresh meter for a run with a hard token cap (0 = no cap)."""
    global USAGE
    with _USAGE_LOCK:
        USAGE = Usage(budget=max(0, int(tokens or 0)))


def _check_budget(prompt_chars: int) -> None:
    if USAGE.budget and USAGE.total + prompt_chars // 4 > USAGE.budget:
        raise BudgetExceeded(f"token budget reached ({USAGE.summary()}) - stopping this run")


def _record(inp: int, out: int, estimated: bool = False) -> None:
    with _USAGE_LOCK:
        USAGE.calls += 1
        USAGE.input_tokens += int(inp or 0)
        USAGE.output_tokens += int(out or 0)
        USAGE.estimated |= estimated


class LLMError(Exception):
    """Raised when the LLM provider fails."""


def _resolve_opencode() -> str:
    """Find the opencode CLI, tolerating LaunchAgent's minimal PATH."""
    candidates = [
        Path(sys.executable).parent / "opencode",
        Path.home() / ".opencode" / "bin" / "opencode",
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand)
    found = shutil.which("opencode")
    if found:
        return found
    raise LLMError("opencode not found on PATH. Install it or set llm.provider in config.yaml.")


@dataclass
class LLMConfig:
    provider: str = "zen"  # "zen" (default), "opencode", "openai-compatible"
    model: str = ""
    agent: str = ""  # opencode agent (default: the lean "jobtailor" agent)
    fallback: str = ""  # provider to retry on when the primary fails, e.g. "ollama"
    fallback_model: str = ""


# Isolated opencode config: no MCP servers, skills, plugins or global AGENTS.md,
# and a tool-less agent. Cuts each call from ~17k prompt tokens to ~500, so the
# free quota isn't burned by the daily runs.
_LEAN_CONFIG_HOME = Path(__file__).resolve().parents[2] / ".opencode-lean"


class LLMClient:
    """Call an LLM to transform content (e.g. tailor a resume)."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self.last_provider = ""

    def generate(self, system_prompt: str, user_prompt: str, workdir: str = ".") -> str:
        """Run a prompt on the primary provider, falling back if it fails."""
        try:
            out = self._run(self._config.provider, self._config.model, system_prompt, user_prompt)
            self.last_provider = self._config.provider
            return out
        except QuotaExhausted:
            raise
        except LLMError as primary_exc:
            fb = self._config.fallback
            if not fb or fb == self._config.provider:
                raise
            if fb == "ollama":  # user rule 2026-11-18: never auto-use Ollama; ask first
                raise LLMError(f"{primary_exc} (Ollama fallback is disabled; ask the user)") from primary_exc
            print(f"[llm] {self._config.provider} failed, falling back to {fb}: {str(primary_exc)[:200]}", file=sys.stderr)
            try:
                out = self._run(fb, self._config.fallback_model, system_prompt, user_prompt)
            except LLMError as fb_exc:
                raise LLMError(f"{primary_exc} | fallback {fb} also failed: {fb_exc}") from fb_exc
            self.last_provider = fb
            return out

    def _run(self, provider: str, model: str, system_prompt: str, user_prompt: str) -> str:
        _check_budget(len(system_prompt) + len(user_prompt))
        if provider == "zen":
            return self._via_zen(system_prompt, user_prompt, model)
        if provider == "opencode":
            return self._via_opencode(system_prompt, user_prompt, model)
        if provider == "openai-compatible":
            return self._via_openai_compatible(system_prompt, user_prompt)
        if provider == "ollama":
            return self._via_ollama(system_prompt, user_prompt, model)
        raise LLMError(f"Unknown LLM provider: {provider}")

    def _via_zen(self, system_prompt: str, user_prompt: str, model: str = "") -> str:
        """OpenCode Zen free models, called directly (no opencode CLI overhead).

        Uses the anonymous "public" key, which only reaches free models, so it
        cannot be charged. Shares opencode's free daily allowance.
        """
        import os
        import re
        import urllib.error
        import urllib.request

        global _QUOTA_EXHAUSTED
        if _QUOTA_EXHAUSTED:
            raise QuotaExhausted("opencode free usage limit reached earlier in this run")
        model = (model or "deepseek-v4.1-flash-free").split("/", 1)[-1]
        if not model.endswith("-free"):
            raise LLMError(f"zen provider is limited to free models; '{model}' is not one")
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1200,
        }
        req = urllib.request.Request(
            os.environ.get("JOBTAILOR_ZEN_URL", "https://opencode.ai/zen/v1/chat/completions"),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer public",
                     "User-Agent": "jobtailor"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode(errors="replace")
            if exc.code == 429 or "FreeUsageLimit" in detail or "free-limit" in detail:
                _QUOTA_EXHAUSTED = True
                raise QuotaExhausted("opencode free usage limit reached - stopping. "
                                     "It resets at 00:00 UTC.") from exc
            raise LLMError(f"zen HTTP {exc.code}: {detail[:200]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"zen request failed: {exc}") from exc
        usage = data.get("usage") or {}
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        text = msg.get("content") or ""
        if usage:
            _record(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        else:
            _record((len(system_prompt) + len(user_prompt)) // 4, len(text) // 4, estimated=True)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        if not text:
            raise LLMError("zen returned empty output")
        return text

    def _via_opencode(self, system_prompt: str, user_prompt: str, model: str = "") -> str:
        import os
        import tempfile

        global _QUOTA_EXHAUSTED
        if _QUOTA_EXHAUSTED:
            raise QuotaExhausted("opencode free usage limit reached earlier in this run")
        binary = _resolve_opencode()

        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}\n\nRespond with ONLY the final output text. Do not wrap it in markdown code fences. Do not explain. Do not call tools. Output the raw result."
        # --agent jobtailor: tool-less agent defined in ~/.config/opencode/opencode.json.
        # Without it the default "build" agent ships every tool/MCP/skill
        # definition with each call (~25k tokens instead of ~500).
        # --archived keeps these one-shot sessions out of the session list.
        cmd = [binary, "run", "--format", "json", "--archived",
               "--agent", self._config.agent or "jobtailor", prompt]
        if model:
            cmd += ["--model", model]
        env = os.environ.copy()
        if _LEAN_CONFIG_HOME.is_dir():
            env["XDG_CONFIG_HOME"] = str(_LEAN_CONFIG_HOME)
        # NOTE: do NOT pass --standalone. Standalone runs route to the free-tier
        # endpoint, which returns 429 "provider.free-limit" for this account,
        # silently pushing every call onto Ollama (2026-11-18). Runs against the
        # normal config use the working provider route at cost 0.
        # The inline "Do not call tools" instruction replaces the old
        # .opencode-lean "jobtailor" agent, which is only visible to --standalone.

        # Empty cwd so no project AGENTS.md/CLAUDE.md is pulled into the prompt.
        with tempfile.TemporaryDirectory(prefix="jobtailor-llm-") as cwd:
            try:
                with _OPENCODE_LOCK:
                    proc = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=300, cwd=cwd, env=env
                    )
            except subprocess.TimeoutExpired as exc:
                raise LLMError("opencode timed out after 300s") from exc
        if "provider.free-limit" in (proc.stdout or "") or "Free usage limit reached" in (proc.stdout or ""):
            _QUOTA_EXHAUSTED = True
            raise QuotaExhausted("opencode free usage limit reached - stopping. Try again after it resets.")
        if proc.returncode != 0:
            raise LLMError(f"opencode failed: {self._error_detail(proc)}")

        # parse the last assistant text event
        try:
            text_parts: list[str] = []
            for line in proc.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "text":
                    text = event.get("part", {}).get("text") or ""
                    if text:
                        text_parts.append(text)
            if text_parts:
                out = "\n".join(text_parts).strip()
                # The CLI adds its own (unmeasured) system prompt; count ours.
                _record(len(prompt) // 4, len(out) // 4, estimated=True)
                return out
        except Exception:  # noqa: BLE001 - fall through to stderr
            pass
        raise LLMError(f"opencode produced no output: {proc.stderr[-500:]}")

    @staticmethod
    def _error_detail(proc: subprocess.CompletedProcess) -> str:
        """Extract a useful message: opencode reports errors in JSON stdout."""
        for line in (proc.stdout or "").strip().splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(event, dict) and event.get("type") == "error":
                err = event.get("error") or {}
                data = err.get("data") or {}
                return str(data.get("message") or err.get("name") or line)[:300]
        return (proc.stderr or "")[-500:] or "no error output"

    def _via_ollama(self, system_prompt: str, user_prompt: str, model: str = "") -> str:
        """Call a local Ollama model directly (free, no quota)."""
        import re
        import urllib.error
        import urllib.request

        body = {
            "model": model or "qwen2.5:7b-instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"num_ctx": 8192, "temperature": 0.2},
        }
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=1200) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"ollama request failed (is 'ollama serve' running?): {exc}") from exc
        text = (data.get("message") or {}).get("content") or ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        text = re.sub(r"^```[a-zA-Z]*\n|\n?```$", "", text).strip()
        if not text:
            raise LLMError("ollama returned empty output")
        return text

    def _via_openai_compatible(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise LLMError("pip install openai to use provider 'openai-compatible'")

        client = OpenAI()
        resp = client.chat.completions.create(
            model=self._config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""