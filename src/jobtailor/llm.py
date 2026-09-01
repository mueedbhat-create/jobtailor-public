"""LLM provider abstraction for the resume tailoring step.

Supports opencode (default) plus any OpenAI-compatible provider.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


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
    provider: str = "opencode"  # "opencode" or "openai-compatible"
    model: str = ""
    agent: str = ""  # opencode agent to use (default: "build")


class LLMClient:
    """Call an LLM to transform content (e.g. tailor a resume)."""

    def __init__(self, config: LLMConfig):
        self._config = config

    def generate(self, system_prompt: str, user_prompt: str, workdir: str = ".") -> str:
        """Run a prompt and return the model's text output."""
        if self._config.provider == "opencode":
            return self._via_opencode(system_prompt, user_prompt, workdir)
        if self._config.provider == "openai-compatible":
            return self._via_openai_compatible(system_prompt, user_prompt)
        raise LLMError(f"Unknown LLM provider: {self._config.provider}")

    def _via_opencode(self, system_prompt: str, user_prompt: str, workdir: str) -> str:
        binary = _resolve_opencode()

        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}\n\nRespond with ONLY the final output text. Do not wrap it in markdown code fences. Do not explain. Output the raw result."
        cmd = [binary, "run", "--format", "json", "--dir", workdir, prompt]
        if self._config.model:
            cmd += ["--model", self._config.model]
        if self._config.agent:
            cmd += ["--agent", self._config.agent]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
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
                return "\n".join(text_parts).strip()
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