"""Stage 5: the application queue with ego-browser auto-fill.

Modes:
- `open` / human_in_the_loop: opens the job page for the user to submit.
- `pre_fill`: fills the form (name/email/phone/links) + attaches the tailored
  PDF, but does NOT click submit — the user reviews and submits.
- `full_auto`: fills the form, attaches the PDF, and clicks submit.

Form filling is done by an ego-browser Node script that:
  1. opens the job's application page,
  2. snapshots the DOM inputs/selects/textareas,
  3. matches each field to the applicant profile by name/id/placeholder/label,
  4. fills what it can (native setter + input/change events so React/Vue state
     updates),
  5. uploads the tailored PDF to the resume/file input,
  6. optionally clicks the apply/submit button.

Per-job status (prepared / submitted / skipped / failed) is tracked in a state
file so nothing is applied twice.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from jobtailor.config import ApplyConfig
from jobtailor.models import TailoredResume


class ApplyError(Exception):
    """Raised when the application queue fails."""


NEVER_AUTO_SOURCES = frozenset({"linkedin"})
"""Sources whose applications must never be auto-submitted (ToS risk).
In full_auto mode these are opened for manual review instead."""


def split_never_auto(
    resumes: list[TailoredResume], source_by_url: dict[str, str]
) -> tuple[list[TailoredResume], list[TailoredResume]]:
    """Partition tailored resumes into (auto_ok, manual_only)."""
    auto: list[TailoredResume] = []
    manual: list[TailoredResume] = []
    for r in resumes:
        if source_by_url.get(r.job_url, "") in NEVER_AUTO_SOURCES:
            manual.append(r)
        else:
            auto.append(r)
    return auto, manual


@dataclass
class ApplicantProfile:
    """Contact details used to fill application forms."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    website: str = ""
    headline: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            k: v
            for k, v in {
                "full_name": self.full_name,
                "email": self.email,
                "phone": self.phone,
                "location": self.location,
                "linkedin": self.linkedin,
                "website": self.website,
                "headline": self.headline,
            }.items()
            if v
        }


class Browser:
    """Opens job URLs in a browser. Thin wrapper for testability."""

    def __init__(self, mode: str = "open"):
        self._mode = mode

    def open(self, url: str) -> None:
        if self._mode == "open":
            if not shutil.which("open"):
                raise ApplyError("'open' not available on this system")
            subprocess.run(["open", url], check=True)
        elif self._mode == "ego":
            self._ego(f"await openOrReuseTab({url!r}, {{ wait: true, timeout: 20 }})")
        else:
            raise ApplyError(f"Unknown browser mode: {self._mode}")

    @staticmethod
    def _ego(script: str) -> str:
        if not shutil.which("ego-browser"):
            raise ApplyError("ego-browser not found on PATH")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(script)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as fh:
                proc = subprocess.run(
                    ["ego-browser", "nodejs"],
                    stdin=fh,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        if proc.returncode != 0:
            raise ApplyError(f"ego-browser failed: {proc.stderr[-500:]}")
        return proc.stdout or proc.stderr


class AutoSubmitter:
    """Fills job application forms with ego-browser (pre-fill or full_auto)."""

    FILL_SKILLS = ("automation", "performance marketing", "ai", "prompt engineering")

    def __init__(self, profile: ApplicantProfile | None = None):
        self._profile = profile or ApplicantProfile()
        base = self._profile.as_dict()
        parts = base.get("full_name", "").split()
        if parts:
            base["first_name"] = parts[0]
            base["last_name"] = " ".join(parts[1:]) or parts[0]
        self._fields_json = json.dumps(base)
        self.last_result: dict | None = None

    def apply(self, url: str, pdf_path: str, submit: bool = False) -> str:
        """Fill the application form for `url`, attach `pdf_path`, optionally submit.

        Returns a short human-readable summary of what happened.
        """
        result = self.apply_structured(url, pdf_path, submit=submit)
        if result.get("error"):
            raise ApplyError(result["error"])
        return self._format_note(result)

    def apply_structured(self, url: str, pdf_path: str, submit: bool = False) -> dict:
        """Same as apply() but returns the raw structured ego-browser result."""
        pdf = Path(pdf_path).expanduser().resolve()
        if not pdf.exists():
            return {"error": f"Tailored PDF not found: {pdf}", "url": url}

        script = self._build_script(url, str(pdf), submit)
        out = Browser._ego(script)
        result = self._parse_result_dict(out)
        self.last_result = result
        return result

    def _build_script(self, url: str, pdf: str, submit: bool) -> str:
        return f"""
const task = await useOrCreateTaskSpace('jobtailor-apply');
await openOrReuseTab({url!r}, {{ wait: true, timeout: 30 }});
await waitForLoad();

// 0. some boards (Wellfound etc.) gate the form behind an "Apply Now" button
await js(`(() => {{
  const re = /^(apply now|apply|apply for this job|easy apply|start application|apply to job)$/i;
  const els = [...document.querySelectorAll('button, a[role=button]')];
  const hit = els.find(e => re.test((e.innerText||'').trim()));
if (hit) hit.click();
}})()`);
await waitForElement('input[name="name"], input[type="file"], form input, form textarea', {{ timeout: 15 }});
await wait(1);

const profile = {self._fields_json};

// 1+2+3. collect fields, match against profile, and fill — all browser-side
const matched = await js(`(() => {{
  const profile = {self._fields_json};
  const FILLS = {{
    first_name: ['first_name','first-name','firstname','given_name','givenname'],
    last_name: ['last_name','last-name','lastname','surname','family_name','familyname'],
    full_name: ['full_name','full-name','fullname','your_name','applicant_name'],
    email: ['email','e_mail','email_address','emailaddress'],
    phone: ['phone','phone_number','phonenumber','mobile','contact_number','contactnumber'],
    location: ['location','city','state','country','address','current_location','currentlocation'],
    linkedin: ['linkedin','linkedin_url','linkedinurl','linkedin_profile','linkedinprofile','linkedin_handle'],
    website: ['website','portfolio','personal_website','portfolio_url','portfoliourl','url','github'],
    headline: ['headline','title','current_title','position_title','desired_role','job_title','current_role'],
  }};
  const seen = new Set();
  const matched = [];
  const fill = (el, val) => {{
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  for (const el of document.querySelectorAll('input, textarea, select')) {{
    const t = (el.type || 'text').toLowerCase();
    if (['hidden','submit','button','reset','checkbox','radio','file'].includes(t)) continue;
    if (el.disabled) continue;
    const rawName = (el.name || el.id || '').toLowerCase();
    if (!rawName || seen.has(rawName)) continue;
    seen.add(rawName);
    const label = (el.closest('label')?.innerText || el.getAttribute('aria-label') || '')
      .trim().toLowerCase();
    const hay = [rawName, (el.placeholder||'').toLowerCase(), label].join(' ');
    let key = null;
    if (rawName === 'name' && profile.full_name) {{
      key = 'full_name';
    }} else {{
      for (const [k, keys] of Object.entries(FILLS)) {{
        if (keys.some(kk => hay.includes(kk))) {{ key = k; break; }}
      }}
    }}
    if (key && profile[key]) {{
      fill(el, profile[key]);
      matched.push([rawName, profile[key]]);
    }}
  }}
  return matched;
}})()`);

// 4. upload the tailored PDF to the resume input
const fileInputs = await js(`(() => {{ const els = document.querySelectorAll('input[type="file"]'); return els.length; }})()`);
let uploaded = false;
if (fileInputs > 0) {{
  await uploadFile('input[type="file"]', {pdf!r});
  uploaded = true;
}}

// 5. submit (only in full_auto)
let submitted = false;
let submitHref = '';
if ({1 if submit else 0}) {{
  const btn = await js(`(() => {{
    const els = [...document.querySelectorAll('button, input[type=submit], a')];
    const re = /(submit|apply|send application|apply now|continue|next)/i;
    const hit = els.filter(e => {{ const t = (e.innerText||'').trim().toLowerCase(); return re.test(t) && !e.disabled; }});
    return hit.length ? {{ sel: hit[hit.length-1].tagName === 'A' ? hit[hit.length-1].href : hit[hit.length-1].outerHTML.split('>')[0]+'>' }} : null;
  }})()`);
  if (btn) {{
    if (btn.href) {{ submitHref = btn.href; }}
    else {{
      await js(`(() => {{ const els=[...document.querySelectorAll('button')]; const re=/submit|apply|send application/i; const hit=els.filter(e=>re.test((e.innerText||'').trim().toLowerCase())); if(hit.length) hit[hit.length-1].click(); }})()`);
    }}
    submitted = true;
  }}
}}

cliLog(JSON.stringify({{
  url: {url!r},
  matched_fields: matched,
  pdf_uploaded: uploaded,
  file_inputs_found: fileInputs,
  submitted,
  submit_href: submitHref,
}}));
"""

    @staticmethod
    def _extract_result_json(out: str) -> dict:
        for line in out.strip().splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _parse_result_dict(out: str) -> dict:
        result = AutoSubmitter._extract_result_json(out)
        if not result:
            return {
                "error": f"ego-browser produced no result. Output: {out.strip()[-300:]}",
                "url": "",
                "matched_fields": [],
                "pdf_uploaded": False,
                "file_inputs_found": 0,
                "submitted": False,
                "submit_href": "",
            }
        result.setdefault("matched_fields", [])
        result.setdefault("pdf_uploaded", False)
        result.setdefault("file_inputs_found", 0)
        result.setdefault("submitted", False)
        result.setdefault("submit_href", "")
        return result

    @staticmethod
    def _format_note(result: dict) -> str:
        status = "submitted" if result.get("submitted") else "pre-filled (not submitted)"
        fields = ", ".join(f"{k}={v}" for k, v in result.get("matched_fields", [])) or "none"
        return (
            f"{status}; matched fields: {fields}; "
            f"PDF uploaded: {result.get('pdf_uploaded')} ({result.get('file_inputs_found')} file input(s) found)"
        )

    @staticmethod
    def _parse_result(out: str) -> str:
        result = AutoSubmitter._parse_result_dict(out)
        if result.get("error"):
            return result["error"]
        return AutoSubmitter._format_note(result)

    @staticmethod
    def fields_from_result(result: dict) -> dict[str, str]:
        pairs = result.get("matched_fields") or []
        fields: dict[str, str] = {}
        for pair in pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0]:
                fields[str(pair[0])] = str(pair[1])
            elif isinstance(pair, dict):
                name = pair.get("name")
                if name:
                    fields[str(name)] = str(pair.get("value", ""))
        return fields


class ApplicationQueue:
    """Tracks which jobs have been prepared / submitted / skipped."""

    def __init__(
        self,
        apply_config: ApplyConfig | None = None,
        state_dir: str | Path = "output/applications",
        browser: Browser | None = None,
        profile: ApplicantProfile | None = None,
    ):
        self._config = apply_config or ApplyConfig()
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._browser = browser or Browser()
        self._profile = profile or ApplicantProfile()

    # -- state persistence -------------------------------------------------

    def _state_path(self) -> Path:
        return self._state_dir / f"{date.today().isoformat()}.json"

    def _load_state(self) -> dict[str, dict]:
        """Load ALL state files across all dates for proper dedup."""
        merged: dict[str, dict] = {}
        for f in sorted(self._state_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict):
                for url, entry in data.items():
                    if isinstance(entry, dict):
                        merged[url] = entry
        return merged

    def _save_state(self, state: dict[str, dict]) -> None:
        self._state_path().write_text(json.dumps(state, indent=2))

    def _status_of(self, state: dict[str, dict], url: str) -> str:
        return state.get(url, {}).get("status", "pending")

    # -- queue ops ---------------------------------------------------------

    def prepare(self, resumes: list[TailoredResume]) -> list[str]:
        """Open each job's page (human-in-the-loop) and mark it prepared.

        Returns the URLs that were actually opened (skips already-submitted).
        """
        state = self._load_state()
        opened: list[str] = []
        for resume in resumes:
            status = self._status_of(state, resume.job_url)
            if status == "submitted":
                continue
            self._browser.open(resume.job_url)
            state[resume.job_url] = {
                "status": "prepared",
                "branch": resume.branch,
                "pdf": str(resume.pdf_path) if resume.pdf_path else "",
                "opened_at": date.today().isoformat(),
            }
            opened.append(resume.job_url)
        self._save_state(state)
        return opened

    def auto_apply(self, resumes: list[TailoredResume], submit: bool = False) -> list[dict]:
        """Fill each application form with ego-browser.

        `submit=False` -> pre-fill only (user clicks submit).
        `submit=True`  -> full auto-submit.
        Returns one summary dict per job.
        """
        sub = AutoSubmitter(self._profile)
        state = self._load_state()
        results: list[dict] = []
        for resume in resumes:
            if not resume.pdf_path:
                results.append({"url": resume.job_url, "status": "failed", "note": "no PDF"})
                continue
            try:
                fields: dict[str, str] = {}
                structured = getattr(sub, "apply_structured", None)
                if structured is not None:
                    res = structured(resume.job_url, str(resume.pdf_path), submit=submit)
                    if res.get("error"):
                        raise ApplyError(res["error"])
                    note = AutoSubmitter._format_note(res)
                    fields = AutoSubmitter.fields_from_result(res)
                else:
                    note = sub.apply(resume.job_url, str(resume.pdf_path), submit=submit)
                status = "submitted" if submit else "prepared"
                state[resume.job_url] = {
                    "status": status,
                    "branch": resume.branch,
                    "pdf": str(resume.pdf_path),
                    "note": note,
                    "fields": fields,
                    "applied_at": date.today().isoformat(),
                }
                results.append({"url": resume.job_url, "status": status, "note": note})
            except Exception as exc:  # noqa: BLE001 - per-job isolation
                state[resume.job_url] = {
                    "status": "failed",
                    "branch": resume.branch,
                    "pdf": str(resume.pdf_path),
                    "note": str(exc),
                    "fields": {},
                    "applied_at": date.today().isoformat(),
                }
                results.append({"url": resume.job_url, "status": "failed", "note": str(exc)})
        self._save_state(state)
        return results

    def mark_submitted(self, job_url: str) -> None:
        state = self._load_state()
        entry = state.get(job_url)
        if entry is None:
            raise ApplyError(f"Job not in queue: {job_url}")
        entry["status"] = "submitted"
        self._save_state(state)

    def mark_skipped(self, job_url: str) -> None:
        state = self._load_state()
        entry = state.get(job_url)
        if entry is None:
            raise ApplyError(f"Job not in queue: {job_url}")
        entry["status"] = "skipped"
        self._save_state(state)

    def status(self) -> list[dict]:
        state = self._load_state()
        return [{"url": url, **entry} for url, entry in state.items()]


def queue_resumes(
    resumes: list[TailoredResume],
    apply_config: ApplyConfig | None = None,
    state_dir: str = "output/applications",
) -> list[str]:
    """Convenience wrapper: prepare the queue for a list of tailored resumes."""
    queue = ApplicationQueue(apply_config, state_dir)
    return queue.prepare(resumes)