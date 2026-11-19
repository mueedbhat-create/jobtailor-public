"""Form probe: check in ego-browser whether a job has a fillable application
form BEFORE any AI tokens are spent tailoring a resume for it.

For each lead it opens the job page in a dedicated ego-browser task space
(one reused tab), follows an Apply link/button or an embedded ATS iframe to
the real form, and classifies the result:

  ready        fillable form found (>= 2 text fields, a file input, or a
               note box + Send button)
  location_locked  the site says it doesn't hire in the candidate's country
  needs_login  the form is behind a login wall
  email_apply  the posting asks for the resume by email
  no_form      nothing fillable reached

Only `ready` leads continue to the fit gate / tailoring. Probing never types
or submits anything. It never touches the user's Chrome.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from jobtailor.models import JobLead

PROBE_SPACE = "jobtailor-probe"
_MARK = "JT_PROBE "


@dataclass
class ProbeResult:
    url: str
    status: str  # ready | needs_login | email_apply | no_form | error
    form_url: str = ""
    fields: int = 0
    file_inputs: int = 0
    textareas: int = 0
    email: str = ""
    note: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "ready"


# Runs inside the page. Returns a JSON-able summary of what's on it.
_INSPECT = r"""
() => {
  const vis = (el) => !!(el.offsetParent || el.getClientRects().length);
  const textLike = [...document.querySelectorAll('input, textarea, select')].filter((el) => {
    const t = (el.type || 'text').toLowerCase();
    if (['hidden','submit','button','reset','checkbox','radio','file','image','search','password'].includes(t)) return false;
    if (el.disabled || !vis(el)) return false;
    const hay = ((el.name||'') + ' ' + (el.id||'') + ' ' + (el.placeholder||'') + ' ' + (el.getAttribute('aria-label')||'')).toLowerCase();
    if (/search|newsletter|subscribe|coupon|promo/.test(hay)) return false;
    if (el.closest('header, nav, footer')) return false;
    return true;
  });
  const files = document.querySelectorAll('input[type=file]').length;
  const textareas = textLike.filter((el) => el.tagName === 'TEXTAREA').length;
  const sendBtn = [...document.querySelectorAll('button, input[type=submit]')].filter(vis)
    .some((e) => /^(send application|submit application|submit|apply|send)$/i.test((e.innerText || e.value || '').trim()));
  const password = [...document.querySelectorAll('input[type=password]')].some(vis);
  const url = location.href;
  const loginUrl = /(login|signin|sign-in|sign_in|\/auth|account\/create|signup|sign-up|register)/i.test(url);
  const ATS = /(greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|smartrecruiters\.com|jobvite\.com|bamboohr\.com|recruitee\.com|breezy\.hr|zohorecruit|freshteam\.com|teamtailor\.com|personio|workday|icims\.com|jazzhr|applytojob\.com|rippling|dover\.com|notion\.site|forms\.gle|docs\.google\.com\/forms|typeform\.com|tally\.so|airtable\.com)/i;
  const hostPath = (s) => { try { const u = new URL(s); return u.hostname + u.pathname; } catch (e) { return ''; } };
  const atsFrame = [...document.querySelectorAll('iframe[src]')].map((f) => f.src)
    .find((s) => ATS.test(hostPath(s)) && hostPath(s) !== hostPath(location.href)) || '';
  const re = new RegExp(__APPLY_RE__, 'i');
  const ctl = [...document.querySelectorAll('a, button, [role=button]')].filter(vis)
    .find((e) => re.test((e.innerText || e.value || '').trim().replace(/[\u2018\u2019]/g, "'").replace(/\s+/g, ' ').toLowerCase()));
  let applyHref = '', applyText = '';
  if (ctl) {
    applyText = (ctl.innerText || '').trim().slice(0, 40);
    const href = ctl.tagName === 'A' ? ctl.href : '';
    if (href && /^https?:/i.test(href) && !/^javascript:/i.test(href)) applyHref = href;
  }
  const body = (document.body && document.body.innerText || '').slice(0, 60000);
  const mailto = [...document.querySelectorAll('a[href^="mailto:"]')].map((a) => a.href.slice(7).split('?')[0]).find(Boolean) || '';
  const m = body.match(/(?:send|email|mail|submit|forward)[^.\n]{0,100}?(?:resume|cv|portfolio|application)[^.\n]{0,100}?([\w.+-]+@[\w-]+(?:\.[\w-]+)+)/i)
        || body.match(/(?:resume|cv)[^.\n]{0,60}?(?:to|at)\s*:?\s*([\w.+-]+@[\w-]+(?:\.[\w-]+)+)/i);
  const emailApply = m ? m[1] : '';
  const locked = /requires all remote workers to be in-country|only (hires|hiring|accepting applications) (in|from)|not (able|eligible) to (hire|apply) (in|from) your (country|location)|does(n't| not) hire in your (country|location)|must (be located|reside|live) in the (united states|us|usa|uk|canada|eu)/i
    .test(body.slice(0, 20000));
  const captcha = /verify you are human|checking your browser|cf-challenge|captcha/i.test(body.slice(0, 3000));
  return { url, fields: textLike.length, files, textareas, sendBtn, password, loginUrl, atsFrame, applyHref, applyText,
           hasApply: !!ctl, emailApply, mailto, captcha, locked };
}
"""


def _inspect_js() -> str:
    from jobtailor.ats import APPLY_TEXT_RE

    return _INSPECT.replace("__APPLY_RE__", json.dumps(APPLY_TEXT_RE))


def _script(url: str) -> str:
    from jobtailor.ats import APPLY_TEXT_RE, ats_form_url

    url = ats_form_url(url)
    return f"""
const URL = {json.dumps(url)};
const INSPECT = {json.dumps(_inspect_js())};
const APPLY_RE = new RegExp({json.dumps(APPLY_TEXT_RE)}, "i");
let task;
try {{ task = await taskSpace({json.dumps(PROBE_SPACE)}); }}
catch (e) {{ task = await claimTaskSpace({json.dumps(PROBE_SPACE)}); }}
let page = (await task.pages())[0];
if (!page) {{
  const t = (await task.tabs())[0];
  page = t ? await task.adopt(t.page) : await task.newPage();
}}
const settle = async (p) => {{
  try {{ await p.waitForLoadState('load', {{ timeout: 15000 }}); }} catch (e) {{}}
  await p.waitForTimeout(1500);
}};
const inspect = async (p) => p.evaluate('(' + INSPECT + ')()');
const fillable = (r) => !r.password && !r.loginUrl && (r.fields >= 2 || r.files >= 1 || (r.textareas >= 1 && r.sendBtn));
const steps = [];
let r;
try {{
  await page.goto(URL, {{ timeout: 30000 }});
  await settle(page);
  r = await inspect(page); steps.push('page');
  if (!fillable(r) && r.atsFrame) {{
    await page.goto(r.atsFrame, {{ timeout: 30000 }}); await settle(page);
    r = await inspect(page); steps.push('ats-iframe');
  }}
  if (!fillable(r) && r.hasApply) {{
    if (r.applyHref && r.applyHref !== page.url) {{
      await page.goto(r.applyHref, {{ timeout: 30000 }});
    }} else {{
      const before = (await task.tabs()).map((t) => t.targetId);
      await page.evaluate((src) => {{
        const vis = (el) => !!(el.offsetParent || el.getClientRects().length);
        const re = new RegExp(src, 'i');
        const c = [...document.querySelectorAll('a, button, [role=button]')].filter(vis)
          .find((e) => re.test((e.innerText || e.value || '').trim().replace(/[\\u2018\\u2019]/g, "'").replace(/\\s+/g, ' ').toLowerCase()));
        if (c) {{ c.removeAttribute && c.removeAttribute('target'); c.click(); }}
      }}, APPLY_RE.source);
      await page.waitForTimeout(1000);
      // Apply popups (e.g. Wellfound) render their fields a moment later.
      try {{
        await page.waitForFunction(() => !!document.querySelector('textarea, input[type=file], [role=dialog] input:not([type=hidden]), form input:not([type=hidden])'),
          undefined, {{ timeout: 8000 }});
      }} catch (e) {{}}
      await page.waitForTimeout(800);
      const fresh = (await task.tabs()).find((t) => !before.includes(t.targetId));
      if (fresh) {{
        const np = fresh.label ? task.page(fresh.label) : await task.adopt(fresh.page);
        await settle(np);
        const u = await np.url();
        await np.close();
        if (u && /^https?:/.test(u)) await page.goto(u, {{ timeout: 30000 }});
      }}
    }}
    await settle(page);
    r = await inspect(page); steps.push('apply');
    if (!fillable(r) && r.atsFrame) {{
      await page.goto(r.atsFrame, {{ timeout: 30000 }}); await settle(page);
      r = await inspect(page); steps.push('ats-iframe');
    }}
  }}
}} catch (e) {{
  console.log({json.dumps(_MARK)} + JSON.stringify({{ error: String(e).slice(0, 200), steps }}));
}}
if (r) console.log({json.dumps(_MARK)} + JSON.stringify({{ ...r, steps }}));
"""


def _classify(url: str, raw: dict) -> ProbeResult:
    if not raw or raw.get("error") and "fields" not in raw:
        return ProbeResult(url, "error", note=(raw or {}).get("error", "no output"))
    form_url = raw.get("url") or url
    fields, files = int(raw.get("fields") or 0), int(raw.get("files") or 0)
    textareas = int(raw.get("textareas") or 0)
    note = "→".join(raw.get("steps") or [])
    fillable = fields >= 2 or files >= 1 or (textareas >= 1 and raw.get("sendBtn"))
    if raw.get("captcha") and not fillable:
        # A bot wall instead of a page. A form that merely HAS a captcha is fine:
        # the user types it when they click Submit.
        return ProbeResult(url, "no_form", form_url, fields, files, note=f"captcha/anti-bot ({note})")
    if raw.get("captcha"):
        note = f"{note}; form has a captcha - type it when you submit"
    if raw.get("locked"):
        return ProbeResult(url, "location_locked", form_url, fields, files, note=note)
    if raw.get("password") or raw.get("loginUrl"):
        return ProbeResult(url, "needs_login", form_url, fields, files, note=note)
    if fields >= 2 or files >= 1 or (textareas >= 1 and raw.get("sendBtn")):
        return ProbeResult(url, "ready", form_url, fields, files, textareas, note=note)
    email = raw.get("emailApply") or ""
    if email:
        return ProbeResult(url, "email_apply", form_url, fields, files, email=email, note=note)
    return ProbeResult(url, "no_form", form_url, fields, files, note=note)


def probe(url: str, timeout: int = 150) -> ProbeResult:
    """Probe one job URL in ego-browser."""
    if not shutil.which("ego-browser"):
        return ProbeResult(url, "error", note="ego-browser not found on PATH")
    try:
        proc = subprocess.run(
            ["ego-browser", "nodejs"],
            input=_script(url),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(url, "error", note=f"probe timed out after {timeout}s")
    raw: dict = {}
    for line in ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines():
        if line.startswith(_MARK):
            try:
                raw = json.loads(line[len(_MARK):])
            except json.JSONDecodeError:
                pass
    if not raw and proc.returncode != 0:
        return ProbeResult(url, "error", note=(proc.stderr or proc.stdout or "")[-200:])
    return _classify(url, raw)


def close_probe_space() -> None:
    """Close the probe task space (its tabs were only for checking)."""
    if not shutil.which("ego-browser"):
        return
    script = f"""
const s = (await listTaskSpaces()).find((x) => x.name === {json.dumps(PROBE_SPACE)});
if (s) {{
  const t = s.ownership === 'user' ? await claimTaskSpace(s.id) : await taskSpace(s.id);
  await t.finish({{ keep: [] }});
}}
"""
    try:
        subprocess.run(["ego-browser", "nodejs"], input=script, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        pass


def probe_until(
    leads: list[JobLead],
    want: int,
    max_probes: int,
    echo=None,
    prober=probe,
) -> tuple[list[tuple[JobLead, ProbeResult]], list[tuple[JobLead, ProbeResult]]]:
    """Probe leads in order until `want` are ready or `max_probes` are spent.

    Returns (ready, not_ready) as (lead, result) pairs.
    """
    from urllib.parse import urlsplit

    ready: list[tuple[JobLead, ProbeResult]] = []
    not_ready: list[tuple[JobLead, ProbeResult]] = []
    login_walls: dict[str, int] = {}
    probes = 0
    for lead in leads:
        if len(ready) >= want or probes >= max_probes:
            break
        host = urlsplit(lead.url).netloc.lower()
        if login_walls.get(host, 0) >= 2:
            continue  # this site wants an account: don't spend more checks on it this run
        probes += 1
        res = prober(lead.url)
        if res.status == "needs_login":
            login_walls[host] = login_walls.get(host, 0) + 1
            if login_walls[host] == 2 and echo:
                echo(f"  [skip site ] {host} needs a login - skipping its other listings this run")
        (ready if res.ready else not_ready).append((lead, res))
        if echo:
            extra = f" {res.email}" if res.email else ""
            echo(f"  [{res.status:<11}] {lead.title[:60]} @ {lead.company[:30]}{extra}")
    return ready, not_ready
