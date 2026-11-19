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
    """Opens job URLs in ego-browser. Thin wrapper for testability.

    JobTailor only ever uses ego-browser. There is deliberately no path to
    the system default browser (macOS `open` -> Chrome): the user's own
    Chrome must never get tabs opened by the pipeline.
    """

    def __init__(self, mode: str = "ego"):
        if mode == "open":
            raise ApplyError("Opening the system browser is disabled; JobTailor uses ego-browser only")
        self._mode = mode

    def open(self, url: str) -> None:
        if self._mode == "ego":
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
        loc = [p.strip() for p in base.get("location", "").split(",") if p.strip()]
        if loc:
            base["city"] = loc[0]
            base["country"] = loc[-1]
        self._base = base
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

    def apply_structured(
        self, url: str, pdf_path: str, submit: bool = False, note: str = ""
    ) -> dict:
        """Same as apply() but returns the raw structured ego-browser result.

        `note` fills a cover-note / "why this company" textarea if the form has one.
        """
        pdf = Path(pdf_path).expanduser().resolve()
        if not pdf.exists():
            return {"error": f"Tailored PDF not found: {pdf}", "url": url}

        script = self._build_script(url, str(pdf), submit, note=note)
        out = Browser._ego(script)
        result = self._parse_result_dict(out)
        self.last_result = result
        return result

    def _build_script(self, url: str, pdf: str, submit: bool, note: str = "") -> str:
        # Browser-side filler. Kept as a plain string (no f-string) so the JS
        # braces stay readable; values are injected with json.dumps below.
        fill_js = r"""
(() => {
  const profile = __PROFILE__;
  const vis = (el) => !!(el.offsetParent || el.getClientRects().length);
  // Same-origin iframes are searched too (cross-origin ATS iframes are
  // resolved earlier by the probe, which hands us the iframe's own URL).
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) {
    try { if (f.contentDocument && f.contentDocument.body) docs.push(f.contentDocument); } catch (e) {}
  }
  const labelOf = (el) => {
    const bits = [];
    if (el.labels) for (const l of el.labels) bits.push(l.innerText);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) for (const id of lb.split(/\s+/)) { const n = el.ownerDocument.getElementById(id); if (n) bits.push(n.innerText); }
    bits.push(el.getAttribute('aria-label') || '', el.placeholder || '');
    const wrap = el.closest('label');
    if (wrap) bits.push(wrap.innerText);
    if (!bits.join('').trim()) {
      const box = el.closest('div, fieldset, li, p, td');
      const cap = box && box.querySelector('label, legend, span, strong');
      if (cap) bits.push(cap.innerText);
    }
    return bits.join(' ').replace(/\s+/g, ' ').trim().toLowerCase().slice(0, 200);
  };
  // Order matters: first match wins.
  const RULES = [
    ['email',      /e-?mail/],
    ['first_name', /first[\s_-]?name|given[\s_-]?name|forename|\bfname\b/],
    ['last_name',  /last[\s_-]?name|surname|family[\s_-]?name|\blname\b/],
    ['full_name',  /full[\s_-]?name|your[\s_-]?name|applicant[\s_-]?name|^name\b|\bname\s*\*?$/],
    ['phone',      /phone|mobile|contact[\s_-]?number|whatsapp|\btel\b/],
    ['linkedin',   /linked[\s_-]?in/],
    ['website',    /website|portfolio|personal[\s_-]?site|github/],
    ['country',    /\bcountry\b/],
    ['city',       /\bcity\b|\btown\b/],
    ['location',   /location|address|where are you based|current[\s_-]?location|\bbased\b/],
  ];
  const fire = (el) => {
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
  };
  const setValue = (el, val) => {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
    fire(el);
  };
  const matched = [], used = new Set();
  let total = 0, i = 0;
  for (const doc of docs) {
    for (const el of doc.querySelectorAll('input, textarea, select')) {
      i++;
      const t = (el.type || 'text').toLowerCase();
      if (['hidden','submit','button','reset','checkbox','radio','file','image','password','search'].includes(t)) continue;
      if (el.disabled || el.readOnly || !vis(el)) continue;
      total++;
      if (el.tagName !== 'SELECT' && (el.value || '').trim()) continue;  // never overwrite
      const key = (el.name || el.id || ('field' + i));
      const hay = [(el.name || ''), (el.id || ''), (el.getAttribute('autocomplete') || ''), labelOf(el)]
        .join(' ').toLowerCase().replace(/[_-]+/g, ' ');
      let want = null;
      const NOTE = /cover|interest|why|motivat|\bnote\b|message|tell us|about you|about yourself|additional|anything else|introduc|stand out/;
      if (el.tagName === 'TEXTAREA') {
        if (profile.note && (NOTE.test(hay) || !hay.trim())) want = 'note';
        else if (!/address|location/.test(hay)) continue;  // unknown long-answer question: leave for the user
      }
      if (want) {}
      else if (t === 'email') want = 'email';
      else if (t === 'tel') want = 'phone';
      else for (const [k, re] of RULES) { if (re.test(hay)) { want = k; break; } }
      if (!want || !profile[want]) continue;
      if (['first_name','last_name','full_name','email','phone','note'].includes(want) && used.has(want)) continue;
      if (el.tagName === 'SELECT') {
        const target = String(profile[want]).toLowerCase();
        const opt = [...el.options].find((o) => o.text.trim().toLowerCase() === target)
                 || [...el.options].find((o) => o.text.toLowerCase().includes(target));
        if (!opt) continue;
        el.value = opt.value; fire(el);
      } else {
        setValue(el, profile[want]);
      }
      used.add(want);
      matched.push([key, want === 'note' ? '(note: ' + String(profile[want]).slice(0, 40) + '...)' : profile[want]]);
    }
  }
  // Mark the resume upload (not the cover-letter one) for uploadFile.
  const files = [...document.querySelectorAll('input[type=file]')];
  const resume = files.find((f) => /resume|cv|curriculum/i.test([f.name, f.id, labelOf(f), (f.closest('div,fieldset') || {}).innerText || ''].join(' ').slice(0, 300))) || files[0];
  if (resume) resume.setAttribute('data-jt-resume', '1');
  return { matched, total, fileInputs: files.length };
})()
""".replace("__PROFILE__", json.dumps({**self._base, **({"note": note} if note else {})}))
        apply_click_js = r"""
(() => {
  const vis = (el) => !!(el.offsetParent || el.getClientRects().length);
  const fields = [...document.querySelectorAll('input, textarea')].filter((el) => vis(el) && !['hidden','submit','button','checkbox','radio','search'].includes((el.type||'').toLowerCase()));
  if (fields.length >= 2 || document.querySelector('input[type=file]')) return 'form-present';
  const re = /^(apply now|apply|apply for this job|apply for this position|easy apply|start application|start your application|apply to job|i'?m interested|apply here)$/i;
  const hit = [...document.querySelectorAll('button, a, [role=button]')].filter(vis)
    .find((e) => re.test((e.innerText || '').trim().replace(/\s+/g, ' ')));
  if (hit) { hit.click(); return 'clicked'; }
  return 'none';
})()
"""
        submit_js = r"""
(() => {
  const vis = (el) => !!(el.offsetParent || el.getClientRects().length);
  const re = /^(submit|submit application|send application|apply|apply now|send)$/i;
  const btns = [...document.querySelectorAll('button, input[type=submit]')].filter((e) => vis(e) && !e.disabled)
    .filter((e) => re.test((e.innerText || e.value || '').trim()));
  if (!btns.length) return false;
  btns[btns.length - 1].click();
  return true;
})()
"""
        confirm_js = r"""
(() => /thank you|thanks for applying|application (has been )?(received|submitted|sent)|we('|’)ve received your application|successfully applied/i
  .test((document.body && document.body.innerText || '').slice(0, 20000)))()
"""
        return f"""
const task = await useOrCreateTaskSpace('jobtailor-apply');
await openOrReuseTab({json.dumps(url)}, {{ wait: true, timeout: 30 }});
await waitForLoad();
await wait(1.5);

// 0. Only if no form is showing yet: click an "Apply" control to reveal it.
const reveal = await js({json.dumps(apply_click_js)});
if (reveal === 'clicked') {{
  await wait(2.5);
  try {{ await waitForElement('form input, form textarea, input[type="file"]', {{ timeout: 15 }}); }} catch (e) {{}}
}}

// 1. Fill text fields / selects from the applicant profile.
const res = await js({json.dumps(fill_js)});
const matched = (res && res.matched) || [];

// 2. Attach the tailored PDF to the resume upload.
let uploaded = false;
if (res && res.fileInputs > 0) {{
  try {{ await uploadFile('input[data-jt-resume="1"]', {json.dumps(pdf)}); uploaded = true; }}
  catch (e) {{ try {{ await uploadFile('input[type="file"]', {json.dumps(pdf)}); uploaded = true; }} catch (e2) {{}} }}
}}

// 3. Submit only in full_auto, and only count it if the page confirms.
let submitted = false, clicked = false;
if ({1 if submit else 0} && (matched.length > 0 || uploaded)) {{
  clicked = await js({json.dumps(submit_js)});
  if (clicked) {{ await wait(4); submitted = await js({json.dumps(confirm_js)}); }}
}}

cliLog(JSON.stringify({{
  url: {json.dumps(url)},
  matched_fields: matched,
  fields_seen: (res && res.total) || 0,
  pdf_uploaded: uploaded,
  file_inputs_found: (res && res.fileInputs) || 0,
  submit_clicked: clicked,
  submitted,
  submit_href: '',
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
        if result.get("submitted"):
            status = "submitted"
        elif result.get("submit_clicked"):
            status = "submit clicked (no confirmation seen)"
        else:
            status = "pre-filled (not submitted)"
        fields = ", ".join(f"{k}={v}" for k, v in result.get("matched_fields", [])) or "none"
        seen = result.get("fields_seen")
        seen_txt = f" of {seen} visible" if seen else ""
        return (
            f"{status}; matched fields{seen_txt}: {fields}; "
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

    def auto_apply(
        self,
        resumes: list[TailoredResume],
        submit: bool = False,
        form_urls: dict[str, str] | None = None,
        notes: dict[str, str] | None = None,
    ) -> list[dict]:
        """Fill each application form with ego-browser.

        `submit=False` -> pre-fill only (user clicks submit).
        `submit=True`  -> full auto-submit.
        `form_urls` maps job URL -> the real form URL found by the probe.
        Statuses are honest: "prepared" only if a field was filled or the PDF
        attached ("no_form" otherwise); "submitted" only if the page confirmed.
        Returns one summary dict per job.
        """
        form_urls = form_urls or {}
        notes = notes or {}
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
                    target = form_urls.get(resume.job_url) or resume.job_url
                    extra = {"note": notes[resume.job_url]} if notes.get(resume.job_url) else {}
                    res = structured(target, str(resume.pdf_path), submit=submit, **extra)
                    if res.get("error"):
                        raise ApplyError(res["error"])
                    if (target != resume.job_url and not res.get("matched_fields")
                            and not res.get("pdf_uploaded")):
                        # Some boards (e.g. Shine) only show the form when reached
                        # by clicking Apply: retry from the job page.
                        res = structured(resume.job_url, str(resume.pdf_path), submit=submit, **extra)
                        if res.get("error"):
                            raise ApplyError(res["error"])
                    note = AutoSubmitter._format_note(res)
                    fields = AutoSubmitter.fields_from_result(res)
                    status = self._honest_status(res, submit)
                else:  # legacy submitter returning only a note
                    note = sub.apply(resume.job_url, str(resume.pdf_path), submit=submit)
                    status = "submitted" if submit and note.startswith("submitted") else "prepared"
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

    @staticmethod
    def _honest_status(res: dict, submit: bool) -> str:
        did_something = bool(res.get("matched_fields")) or bool(res.get("pdf_uploaded"))
        if not did_something:
            return "no_form"
        if submit:
            if res.get("submitted"):
                return "submitted"
            return "submit_unconfirmed" if res.get("submit_clicked") else "prepared"
        return "prepared"

    def record(self, job_url: str, status: str, note: str = "", **extra) -> None:
        """Record a job that never reached the form step (probe / pre-filter)."""
        state = self._load_state()
        if self._status_of(state, job_url) in ("submitted", "applied"):
            return
        state[job_url] = {"status": status, "note": note, "checked_at": date.today().isoformat(), **extra}
        self._save_state(state)

    def known_urls(self) -> set[str]:
        """Jobs already handled in any earlier run (don't spend tokens twice)."""
        return set(self._load_state())

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