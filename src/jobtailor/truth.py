"""Deterministic fact-check for AI rewrites (no AI involved).

The tailoring prompt says "never invent", but small local models ignore it:
on 2026-11-16 qwen2.5:7b added a fake job ("Performance Marketing Specialist
at BrightGrowth, Jan 2023 - Present"), Google/Meta/TikTok Ads, Salesforce,
HubSpot and SQL to tailored resumes. This module compares rewritten text
against the user's real resume and lists anything new:

  * job entries (\\cventry company / title / date lines) not on the resume
  * numbers / percentages / years not on the resume
  * known tools & skills (Salesforce, Google Ads, SQL, ...) not on the resume
  * unfamiliar words (not on the resume, not English) - catches new tools

A section with violations is replaced by the original; a note with
violations is dropped. Rephrasing with ordinary English words is allowed.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

# Tools / skills / metrics people commonly get "added" to resumes.
KNOWN_TERMS = [
    "google ads", "adwords", "meta ads", "facebook ads", "instagram ads", "tiktok", "linkedin ads",
    "youtube ads", "bing ads", "microsoft ads", "programmatic", "dsp", "salesforce", "hubspot", "marketo",
    "pardot", "zoho", "pipedrive", "crm", "sql", "postgresql", "postgres", "mysql", "mongodb",
    "bigquery", "snowflake", "python", "javascript", "typescript", "react", "node", "java", "php",
    "excel", "tableau", "power bi", "looker", "ga4", "google analytics", "mixpanel", "amplitude",
    "segment", "shopify", "woocommerce", "klaviyo", "mailchimp", "braze", "iterable", "sendgrid",
    "semrush", "ahrefs", "moz", "screaming frog", "wordpress", "webflow", "figma", "canva",
    "photoshop", "illustrator", "premiere", "after effects", "zapier", "make.com", "n8n", "airtable",
    "notion", "jira", "asana", "openai", "langchain", "llamaindex", "rag", "vector", "pinecone",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "rest api", "graphql", "cac",
    "roas", "ltv", "cpa", "cpc", "cpm", "ctr", "a/b", "ab test", "budget", "p&l", "okrs", "kpis",
]

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#&./'-]*")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(?:\\?%|k|m|x|\+)?", re.I)


def reference_text(resume_dir: str | Path) -> str:
    """All of the user's own resume text (resume.tex + every section file)."""
    root = Path(resume_dir).expanduser()
    parts = []
    for f in [root / "resume.tex", *sorted((root / "resume").glob("*.tex"))]:
        if f.exists():
            parts.append(f.read_text(errors="ignore"))
    return "\n".join(parts)


def _plain(tex: str) -> str:
    # LaTeX comments: "%" at line start or after whitespace (not "35%" or "35\\%")
    t = re.sub(r"(?m)(?:^|(?<=\s))%.*$", "", tex)
    t = re.sub(r"\\href\{[^}]*\}", " ", t)
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)
    t = t.replace("\\&", "&").replace("\\%", "%").replace("\\$", "$")
    return re.sub(r"[{}\[\]]", " ", t)


@lru_cache(maxsize=1)
def _english() -> frozenset[str]:
    try:
        words = Path("/usr/share/dict/words").read_text(errors="ignore").split()
    except OSError:
        return frozenset()
    return frozenset(w.lower() for w in words)


def _is_english(word: str) -> bool:
    eng = _english()
    if not eng:
        return True  # no dictionary available: don't block on unknown words
    w = word.lower().strip("'.-")
    if w in eng:
        return True
    for suf, rep in (("ies", "y"), ("ied", "y"), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"),
                     ("es", ""), ("s", ""), ("ly", ""), ("er", ""), ("ers", ""), ("ment", ""),
                     ("ments", ""), ("ation", "e"), ("ations", "e"), ("ised", "ize"), ("ise", "ize"),
                     ("ising", "ize"), ("isation", "ization")):
        if w.endswith(suf) and (w[: -len(suf)] + rep) in eng:
            return True
    for suf in ("ing", "ed", "er", "ers"):  # planning -> plan, debugged -> debug
        stem = w[: -len(suf)]
        if w.endswith(suf) and len(stem) > 3 and stem[-1] == stem[-2] and stem[:-1] in eng:
            return True
    if "-" in w:
        return all(_is_english(p) for p in w.split("-") if p)
    return False


def _words(text: str) -> set[str]:
    """Normalized words, with hyphenated words also split into parts."""
    out: set[str] = set()
    for tok in _TOKEN.findall(text):
        t = tok.strip("'.-&/").lower()
        if not t:
            continue
        out.add(t)
        out.update(p for p in re.split(r"[-/.&]", t) if p)
    return out


def _entries(tex: str) -> list[str]:
    """First four brace args of every \\cventry (title, org, place, dates)."""
    out = []
    for m in re.finditer(r"\\cventry\s*((?:\{[^{}]*\}\s*(?:%[^\n]*)?\s*){4})", tex):
        args = re.findall(r"\{([^{}]*)\}", m.group(1))
        out.extend(a.strip() for a in args if a.strip())
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", _plain(s).lower()).strip()


def violations(new_text: str, reference: str, extra_allowed: str = "") -> list[str]:
    """Things in `new_text` that are not supported by `reference`.

    `extra_allowed` is text that may be mentioned without being a claim
    (e.g. the target company name and job title in a note).
    """
    ref_norm = _norm(reference)
    ref_plain = _plain(reference).lower()
    allowed_plain = (ref_plain + " " + extra_allowed.lower())
    found: list[str] = []

    ref_entries = {_norm(e) for e in _entries(reference)}
    for e in _entries(new_text):
        n = _norm(e)
        if n and n not in ref_entries and n not in ref_norm:
            found.append(f"new entry: {e[:50]}")

    ref_numbers = {n.replace(" ", "").replace("\\", "").lower() for n in _NUMBER.findall(ref_plain)}
    for n in _NUMBER.findall(_plain(new_text)):
        key = n.replace(" ", "").replace("\\", "").lower()
        if key not in ref_numbers and key.rstrip("%kmx+") not in {r.rstrip("%kmx+") for r in ref_numbers}:
            found.append(f"new number: {n.strip()}")

    new_plain = _plain(new_text).lower()
    for term in KNOWN_TERMS:
        pat = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        if re.search(pat, new_plain) and not re.search(pat, allowed_plain):
            found.append(f"new skill/tool: {term}")

    ref_words = _words(allowed_plain)
    for tok in set(_TOKEN.findall(new_plain.replace("\u2019", "'"))):
        t = tok.strip("'.-&/").lower()
        t = re.sub(r"'(s|m|d|ve|ll|re|t)$", "", t)  # I'm, I'd, Acme's, don't
        if t in ("i", "don", "won", "can", "isn", "didn", "doesn"):
            continue
        if (len(t) < 3 or t in ref_words or t + "s" in ref_words or t.rstrip("s") in ref_words
                or _is_english(t)):
            continue
        parts = [p for p in re.split(r"[-/.&]", t) if p]
        if len(parts) > 1 and all(p in ref_words or _is_english(p) for p in parts):
            continue
        found.append(f"unfamiliar word: {t}")

    # de-duplicate, keep order
    seen, out = set(), []
    for v in found:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
