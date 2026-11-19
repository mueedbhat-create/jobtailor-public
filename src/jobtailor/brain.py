"""One AI call per job: fit check + resume tailoring + application note.

Why this exists
---------------
The old pipeline made three AI calls per job (fit gate, LaTeX rewrite, note),
each re-sending the whole job description and resume, and asked the model to
rewrite raw LaTeX - which wasted tokens, broke the PDF build, and let weak
models invent experience.

This module does the work with plain code wherever possible and asks the
model only for judgement, in ONE small call that returns JSON:

* The resume is parsed into a numbered "bullet bank" (E1.2 = entry 1, bullet 2)
  and skill groups (S1, S2 ...). The model sees plain text, not LaTeX.
* The job description is compacted in code (requirements kept, boilerplate,
  benefits and legal text dropped) to at most ~2,500 characters.
* The model returns: apply/skip, bullet order, skill order, a few optional
  rewordings, skills to surface, and (only when the form needs one) a note.
* Code rebuilds the LaTeX from the user's own text. Every reworded bullet,
  surfaced skill and note is fact-checked against the real resume
  (``truth.violations``); anything that fails keeps the original wording.

Typical cost: ~1,700 input + ~350 output tokens per job.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from jobtailor.models import JobDescription

PROMPT_VERSION = "brain-v1"

# ---------------------------------------------------------------------------
# Small LaTeX helpers
# ---------------------------------------------------------------------------


def _match_brace(text: str, start: int) -> int:
    """Index just past the brace group opening at text[start] == '{'."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced braces in resume LaTeX")


def _brace_args(text: str, pos: int, n: int, starts: list[int] | None = None) -> tuple[list[str], int]:
    """Read n consecutive {...} arguments starting at/after pos (skipping
    whitespace and % comments). Returns (args, end_position); if `starts` is
    given, the offset of each argument's content is appended to it."""
    args = []
    i = pos
    for _ in range(n):
        while i < len(text):
            if text[i].isspace():
                i += 1
            elif text[i] == "%":
                nl = text.find("\n", i)
                i = len(text) if nl < 0 else nl + 1
            else:
                break
        if i >= len(text) or text[i] != "{":
            raise ValueError("expected '{' in resume LaTeX")
        end = _match_brace(text, i)
        args.append(text[i + 1 : end - 1])
        if starts is not None:
            starts.append(i + 1)
        i = end
    return args, i


def tex_to_plain(tex: str) -> str:
    """Readable plain text from a LaTeX fragment (for the prompt)."""
    t = re.sub(r"(?m)(?:^|(?<=\s))%.*$", "", tex)
    t = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)
    t = t.replace("\\&", "&").replace("\\%", "%").replace("\\$", "$").replace("\\_", "_")
    t = t.replace("---", "-").replace("--", "-")
    t = re.sub(r"[{}]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def plain_to_tex(text: str) -> str:
    """Plain text (with optional **bold**) -> safe LaTeX."""
    t = text.strip()
    for a, b in (("\\", ""), ("&", "\\&"), ("%", "\\%"), ("$", "\\$"), ("#", "\\#"),
                 ("_", "\\_"), ("{", ""), ("}", ""), ("~", ""), ("^", "")):
        t = t.replace(a, b)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", t)
    return t.replace("*", "")


# ---------------------------------------------------------------------------
# Resume bank
# ---------------------------------------------------------------------------


@dataclass
class Bullet:
    id: str
    tex: str  # the inner LaTeX of \item{...} (or the text after \item)
    braced: bool

    @property
    def plain(self) -> str:
        return tex_to_plain(self.tex)


@dataclass
class Entry:
    id: str
    title: str
    org: str
    block_start: int  # span of the text inside \begin{cvitems} ... \end{cvitems}
    block_end: int
    indent: str
    bullets: list[Bullet] = field(default_factory=list)


@dataclass
class SkillGroup:
    id: str
    name: str
    items: list[str]


@dataclass
class ResumeBank:
    resume_dir: Path
    experience_tex: str
    skills_tex: str
    entries: list[Entry]
    skills: list[SkillGroup]
    reference: str  # all of the user's resume text, for fact-checking

    # -- parsing -----------------------------------------------------------

    @classmethod
    def load(cls, resume_dir: str | Path) -> "ResumeBank":
        from jobtailor.truth import reference_text

        root = Path(resume_dir).expanduser()
        exp_path = root / "resume" / "experience.tex"
        sk_path = root / "resume" / "skills.tex"
        exp = exp_path.read_text(errors="replace") if exp_path.exists() else ""
        sk = sk_path.read_text(errors="replace") if sk_path.exists() else ""
        return cls(root, exp, sk, _parse_entries(exp), _parse_skills(sk), reference_text(root))

    def fingerprint(self) -> str:
        return hashlib.sha256((self.experience_tex + "\x00" + self.skills_tex).encode()).hexdigest()[:16]

    def bullet(self, bid: str) -> Bullet | None:
        for e in self.entries:
            for b in e.bullets:
                if b.id == bid:
                    return b
        return None

    def prompt_text(self) -> str:
        lines = []
        for e in self.entries:
            lines.append(f"{e.id} {tex_to_plain(e.title)} @ {tex_to_plain(e.org)}")
            lines.extend(f" {b.id} {b.plain}" for b in e.bullets)
        if self.skills:
            lines.append("SKILLS:")
            lines.extend(f" {g.id} {tex_to_plain(g.name)}: {', '.join(tex_to_plain(i) for i in g.items)}"
                         for g in self.skills)
        return "\n".join(lines)


def _parse_entries(tex: str) -> list[Entry]:
    entries: list[Entry] = []
    for n, m in enumerate(re.finditer(r"\\cventry\b", tex), start=1):
        starts: list[int] = []
        try:
            args, _ = _brace_args(tex, m.end(), 5, starts)
        except ValueError:
            continue
        body = args[4]
        body_start = starts[4]
        bm = re.search(r"\\begin\{cvitems\}(.*?)\\end\{cvitems\}", body, re.S)
        if not bm:
            continue
        inner_start = body_start + bm.start(1)
        inner_end = body_start + bm.end(1)
        inner = tex[inner_start:inner_end]
        im = re.search(r"\n([ \t]*)\\item", inner)
        indent = im.group(1) if im else "        "
        entry = Entry(f"E{n}", args[0], args[1], inner_start, inner_end, indent)
        for k, b in enumerate(_parse_items(inner), start=1):
            entry.bullets.append(Bullet(f"E{n}.{k}", b[0], b[1]))
        entries.append(entry)
    return entries


def _parse_items(inner: str) -> list[tuple[str, bool]]:
    items: list[tuple[str, bool]] = []
    for m in re.finditer(r"\\item\b", inner):
        j = m.end()
        while j < len(inner) and inner[j] in " \t":
            j += 1
        if j < len(inner) and inner[j] == "{":
            try:
                end = _match_brace(inner, j)
            except ValueError:
                continue
            items.append((inner[j + 1 : end - 1], True))
        else:
            nxt = re.search(r"\\item\b", inner[j:])
            chunk = inner[j : j + nxt.start()] if nxt else inner[j:]
            chunk = re.sub(r"(?m)^\s*%.*$", "", chunk).strip()
            if chunk:
                items.append((chunk, False))
    return items


def _parse_skills(tex: str) -> list[SkillGroup]:
    groups: list[SkillGroup] = []
    for n, m in enumerate(re.finditer(r"\\cvskill\b", tex), start=1):
        try:
            (name, items), _ = _brace_args(tex, m.end(), 2)
        except ValueError:
            continue
        groups.append(SkillGroup(f"S{n}", name, _split_skills(items)))
    return groups


def _split_skills(items: str) -> list[str]:
    """Split a skill list on commas that are not inside (...) or {...}."""
    out, depth, cur = [], 0, ""
    for c in items:
        if c in "({":
            depth += 1
        elif c in ")}":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return [s for s in out if s]


# ---------------------------------------------------------------------------
# Job description compaction (no AI)
# ---------------------------------------------------------------------------

_KEEP_HEAD = re.compile(
    r"(requirement|responsibilit|qualification|what you|you will|you'll|about the role|the role|"
    r"role overview|must[- ]have|nice[- ]to[- ]have|skills|experience|who you are|what we.?re looking|"
    r"ideal candidate|key duties|your day|duties|location|eligib|remote)", re.I)
_DROP_HEAD = re.compile(
    r"(benefit|perk|what we offer|why join|our values|equal opportunit|eeo|diversity|privacy|"
    r"cookie|about us|who we are|our story|compensation philosophy|apply now|share this|similar jobs)",
    re.I)
_DROP_LINE = re.compile(
    r"(cookie|privacy policy|terms of (use|service)|sign in|log in|create alert|share on|"
    r"all rights reserved|equal opportunity employer|subscribe|newsletter|©|"
    r"^(guidelines|faq|lists|api|security|legal|apply to yc|contact|search:?|hacker news|on:|"
    r"home|jobs|about|blog|careers|pricing|menu|skip to content)$)", re.I)


def compact_jd(text: str, limit: int = 2500) -> str:
    """Keep the parts of a job page that matter for fit and tailoring."""
    raw = [ln.strip(" \t*-•#>|") for ln in (text or "").splitlines()]
    seen: set[str] = set()
    lines = []
    for ln in raw:
        key = ln.lower()
        if (not ln or key in seen or _DROP_LINE.search(ln) or re.match(r"^\[?\d*\]?\s*https?://\S+$", ln)
                or re.match(r"^\[\d+\]$", ln)):
            continue
        seen.add(key)
        lines.append(ln)

    def is_head(ln: str) -> bool:
        return len(ln) <= 45 and not ln.endswith(".") and (ln.endswith(":") or ln[:1].isupper())

    keep, other, mode = [], [], "other"
    for ln in lines:
        if is_head(ln) and _DROP_HEAD.search(ln):
            mode = "drop"
            continue
        if is_head(ln) and _KEEP_HEAD.search(ln):
            mode = "keep"
            keep.append(ln.rstrip(":") + ":")
            continue
        if len(ln) < 15 and not is_head(ln):
            continue  # navigation crumbs: "new", "past", "login", ...
        if mode == "keep":
            keep.append(ln)
        elif mode == "other":
            other.append(ln)
    if sum(len(x) for x in keep) >= 400:
        body = other[:3] + keep  # a little context (title/location line) + requirements
    else:
        body = other + keep
    out = re.sub(r"[ \t]+", " ", "\n".join(body))
    if len(out) > limit:
        out = out[:limit].rsplit("\n", 1)[0]
    return out


# ---------------------------------------------------------------------------
# Hard rules in code (no AI)
# ---------------------------------------------------------------------------

_SWE_YEARS = re.compile(
    r"\b\d+\+?\s*(?:-\s*\d+\s*)?years?\b[^.\n]{0,40}\b(?:software|backend|back-end|frontend|front-end|"
    r"full[- ]?stack|web|mobile|ios|android|devops|cloud|infrastructure|data)\s+"
    r"(?:development|engineering|developer|engineer)", re.I)
_REGION_ONLY = re.compile(
    r"\b(?:(?:us|u\.s\.|usa|united states|canada|uk|united kingdom|eu|europe|emea|latam|australia|"
    r"germany|philippines)[- ](?:only|based only|residents only)|must (?:be )?(?:located|based|reside|residing)"
    r" in (?:the )?(?:us|u\.s\.|usa|united states|canada|uk|united kingdom|eu|europe|australia))\b", re.I)
_OPEN_WORLD = re.compile(r"\b(worldwide|anywhere|global(?:ly)?|international)\b", re.I)


def hard_skip(jd: JobDescription, location: str = "", skip_engineering: bool = True) -> str:
    """A reason to skip without spending a token, or "" to continue."""
    text = jd.description or ""
    m = _SWE_YEARS.search(text) if skip_engineering else None
    if m:
        return f"needs engineering experience ({m.group(0)[:60]})"
    m = _REGION_ONLY.search(text)
    if m:
        country = location.split(",")[-1].strip()
        open_to_me = (country and re.search(rf"\b{re.escape(country)}\b", text, re.I)) or _OPEN_WORLD.search(text)
        if not open_to_me:
            return f"location restricted ({m.group(0)[:40]})"
    return ""


# ---------------------------------------------------------------------------
# The one AI call
# ---------------------------------------------------------------------------

SYSTEM = ("You match a candidate's real resume to a job. Use ONLY facts given. "
          "Reply with one JSON object and nothing else.")

_RULE_ENG = "an engineering/developer role, or it needs software-development experience, or "
_RULE_LOC = ("it restricts applicants to other countries/regions (remote-anywhere and the candidate's own "
             "country are fine)")


def rules(skip_engineering: bool = True) -> str:
    fit = (" APPLY to marketing/growth/content roles AND to AI-automation or workflow roles "
           "(n8n, Zapier, Make, prompts, AI agents) that do not need a software engineer."
           if skip_engineering else " Otherwise APPLY.")
    return f"SKIP if: {_RULE_ENG if skip_engineering else ''}{_RULE_LOC}.{fit}"


RULES = rules(True)


@dataclass
class Plan:
    apply: bool = True
    why: str = ""
    order: list[str] = field(default_factory=list)
    skills: dict[str, list[str]] = field(default_factory=dict)
    cat_order: list[str] = field(default_factory=list)
    add_skills: dict[str, list[str]] = field(default_factory=dict)
    rewrite: dict[str, str] = field(default_factory=dict)
    note: str = ""
    cached: bool = False


def build_prompt(jd: JobDescription, bank: ResumeBank, profile: str, location: str,
                 want_note: bool, skip_engineering: bool = True) -> str:
    note_spec = (',"note":"60-90 words, first person, plain text, why this candidate fits; '
                 'only facts above; name the company once; no greeting/sign-off"') if want_note else ""
    return (
        f"CANDIDATE: {profile.strip()[:700]}\nLocation: {location or 'not given'}\n{rules(skip_engineering)}\n\n"
        f"RESUME:\n{bank.prompt_text()}\n\n"
        f"JOB: {jd.title} @ {jd.company}\n{compact_jd(jd.description)}\n\n"
        "Return JSON:\n"
        '{"apply":true|false,"why":"max 15 words",'
        '"order":[bullet ids, most relevant to this job first],'
        '"skills":{"S1":[that group\'s skills, most relevant first]},'
        '"cat_order":[skill group ids, most relevant first],'
        '"add_skills":{"S1":[up to 3 terms the job wants that appear WORD FOR WORD in the RESUME bullets '
        'but not in SKILLS]},'
        '"rewrite":{"E1.2":"max 3 bullets, same facts and numbers, reworded with the job\'s terms; '
        '**bold** allowed"}'
        f"{note_spec}}}\n"
        "If apply is false, return only apply and why."
    )


def _parse_json(text: str) -> dict:
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in AI reply")
    blob = t[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        blob = re.sub(r",\s*([}\]])", r"\1", blob)  # trailing commas
        return json.loads(blob)


def _clean_plan(data: dict) -> Plan:
    def strs(v) -> list[str]:
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    def strmap(v) -> dict[str, list[str]]:
        return {str(k): strs(x) for k, x in v.items()} if isinstance(v, dict) else {}

    apply_v = data.get("apply", True)
    if isinstance(apply_v, str):
        apply_v = apply_v.strip().lower() not in ("false", "no", "skip")
    rw = data.get("rewrite") if isinstance(data.get("rewrite"), dict) else {}
    return Plan(
        apply=bool(apply_v),
        why=str(data.get("why", ""))[:200],
        order=strs(data.get("order")),
        skills=strmap(data.get("skills")),
        cat_order=strs(data.get("cat_order")),
        add_skills=strmap(data.get("add_skills")),
        rewrite={str(k): str(v) for k, v in list(rw.items())[:3] if str(v).strip()},
        note=str(data.get("note", "") or ""),
    )


def plan_job(llm, jd: JobDescription, bank: ResumeBank, profile: str = "", location: str = "",
             want_note: bool = False, cache_dir: str | Path | None = None,
             skip_engineering: bool = True) -> Plan:
    """Ask the model once for this job. Cached by prompt, so re-runs are free."""
    prompt = build_prompt(jd, bank, profile, location, want_note, skip_engineering)
    key = hashlib.sha256(f"{PROMPT_VERSION}\x00{SYSTEM}\x00{prompt}".encode()).hexdigest()[:24]
    cache = Path(cache_dir) / f"{key}.json" if cache_dir else None
    if cache and cache.exists():
        try:
            plan = _clean_plan(json.loads(cache.read_text()))
            plan.cached = True
            return plan
        except (ValueError, OSError):
            pass
    reply = llm.generate(SYSTEM, prompt)
    data = _parse_json(reply)
    plan = _clean_plan(data)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=1))
    return plan


# ---------------------------------------------------------------------------
# Rebuilding the resume from the plan (no AI)
# ---------------------------------------------------------------------------


@dataclass
class BuildReport:
    reordered: bool = False
    rewritten: list[str] = field(default_factory=list)
    surfaced: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.reordered or bool(self.rewritten) or bool(self.surfaced)


def _number_tokens(s: str) -> list[str]:
    return sorted(re.findall(r"\d+(?:\.\d+)?", s))


def _accept_rewrite(bid: str, text: str, bank: ResumeBank, report: BuildReport) -> str | None:
    from jobtailor.truth import violations

    b = bank.bullet(bid)
    if b is None:
        return None
    if "\\href" in b.tex:
        report.rejected.append(f"{bid}: has a link, kept original")
        return None
    plain = re.sub(r"\*\*", "", text).strip()
    if len(plain) < 25 or len(plain) > max(320, int(len(b.plain) * 1.6)):
        report.rejected.append(f"{bid}: odd length, kept original")
        return None
    if _number_tokens(plain) != _number_tokens(b.plain):
        report.rejected.append(f"{bid}: numbers changed, kept original")
        return None
    from jobtailor.truth import KNOWN_TERMS

    def terms(s: str) -> set[str]:
        low = s.lower()
        return {t for t in KNOWN_TERMS if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)}

    lost = terms(b.plain) - terms(plain)
    if lost:
        report.rejected.append(f"{bid}: dropped {', '.join(sorted(lost)[:3])}, kept original")
        return None
    found = violations(plain, bank.reference)
    if found:
        report.rejected.append(f"{bid}: {', '.join(found[:3])}")
        return None
    return plain_to_tex(text)


def _surface_ok(term: str, bank: ResumeBank, group: SkillGroup) -> bool:
    t = term.strip()
    if not (2 <= len(t) <= 40) or "," in t:
        return False
    plain_resume = tex_to_plain(bank.experience_tex).lower()
    if not re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", plain_resume):
        return False
    have = {tex_to_plain(i).lower() for g in bank.skills for i in g.items}
    return t.lower() not in have


def render(bank: ResumeBank, plan: Plan) -> tuple[str, str, BuildReport]:
    """New (experience.tex, skills.tex) built only from the user's own text."""
    report = BuildReport()
    rank = {bid: i for i, bid in enumerate(plan.order)}
    rewrites = {}
    for bid, txt in plan.rewrite.items():
        ok = _accept_rewrite(bid, txt, bank, report)
        if ok:
            rewrites[bid] = ok
            report.rewritten.append(bid)

    exp = bank.experience_tex
    for e in sorted(bank.entries, key=lambda e: e.block_start, reverse=True):
        ordered = sorted(enumerate(e.bullets), key=lambda kb: (rank.get(kb[1].id, 10_000), kb[0]))
        if [b.id for _, b in ordered] != [b.id for b in e.bullets]:
            report.reordered = True
        lines = []
        for _, b in ordered:
            body = rewrites.get(b.id, b.tex)
            lines.append(f"{e.indent}\\item{{{body}}}" if b.braced or b.id in rewrites else f"{e.indent}\\item {body}")
        old = exp[e.block_start : e.block_end]
        head = re.match(r"[^\\]*", old).group(0) if "\\item" in old else "\n"
        head = head if head.strip() == "" else "\n"
        tail = re.search(r"\s*$", old).group(0) or "\n"
        new_inner = head + "\n".join(line.lstrip() if i == 0 and head.endswith(e.indent) else line
                                       for i, line in enumerate(lines)) + tail
        exp = exp[: e.block_start] + new_inner + exp[e.block_end :]

    skills_tex = bank.skills_tex
    if bank.skills:
        by_id = {g.id: g for g in bank.skills}
        groups = []
        for g in bank.skills:
            want = [w.lower() for w in plan.skills.get(g.id, [])]
            pos = {tex_to_plain(i).lower(): n for n, i in enumerate(g.items)}
            order_idx = [pos[w] for w in want if w in pos]
            rest = [n for n in range(len(g.items)) if n not in order_idx]
            items = [g.items[n] for n in order_idx + rest]
            if items != g.items:
                report.reordered = True
            for term in plan.add_skills.get(g.id, [])[:3]:
                if _surface_ok(term, bank, g):
                    items.insert(0, plain_to_tex(term))
                    report.surfaced.append(term)
                else:
                    report.rejected.append(f"skill '{term[:30]}': not in your experience text")
            groups.append(SkillGroup(g.id, g.name, items))
        cat_rank = {gid: i for i, gid in enumerate(plan.cat_order) if gid in by_id}
        groups.sort(key=lambda g: (cat_rank.get(g.id, 10_000), int(g.id[1:])))
        if [g.id for g in groups] != [g.id for g in bank.skills]:
            report.reordered = True
        first = re.search(r"\\cvskill\b", skills_tex)
        endm = re.search(r"\\end\{cvskills\}", skills_tex)
        if first and endm:
            block = "\n\n".join(f"\\cvskill\n    {{{g.name}}}\n    {{{', '.join(g.items)}}}" for g in groups)
            skills_tex = skills_tex[: first.start()] + block + "\n\n" + skills_tex[endm.start():]
    return exp, skills_tex, report


def build_resume(bank: ResumeBank, plan: Plan, dest: str | Path) -> BuildReport:
    """Write a tailored copy of the resume folder to dest. Original untouched."""
    exp, sk, report = render(bank, plan)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(bank.resume_dir, dest,
                    ignore=shutil.ignore_patterns(".git", "*.pdf", "__pycache__", "*.aux", "*.log"))
    if bank.experience_tex:
        (dest / "resume" / "experience.tex").write_text(exp)
    if bank.skills_tex:
        (dest / "resume" / "skills.tex").write_text(sk)
    return report


def check_note(note: str, title: str, company: str, reference: str) -> str:
    """The note if it is clean and truthful, else "" (the user writes it)."""
    from jobtailor.truth import violations

    out = (note or "").strip().strip('"').strip()
    out = re.sub(r"(?is)^(dear [^\n,]*,?\s*|hi[^\n,]*,\s*)", "", out)
    out = re.sub(r"(?is)\n\s*(best|regards|sincerely|thanks)[^\n]*$", "", out).strip()
    if len(out) < 40 or re.search(r"\[[^\]]+\]|<[^>]+>|\{[^}]+\}", out):
        return ""
    if company and re.search(rf"\b(at|with|for)\s+{re.escape(company)}\s*,?\s+(i|we)\b", out, re.I):
        return ""
    if reference and violations(out, reference, extra_allowed=f"{title} {company}"):
        return ""
    return out[:900]
