"""Free keyword pre-filter: drop obvious non-matches before any AI call.

Runs on lead titles/locations only — no network, no tokens. It is
deliberately conservative about what it keeps: a lead must look like a
target role (marketing / growth / AI automation / content ...), must not be
a pure engineering role, and must not be pinned to a place other than the
candidate's country. The LLM fit gate still runs afterwards on what's left.
"""

from __future__ import annotations

import re

from jobtailor.models import JobLead

# A lead must match at least one of these to be worth an AI call.
TARGET = re.compile(
    r"marketing|marketer|growth|automation|\bai\b|artificial intelligence|\bllm|prompt|"
    r"n8n|zapier|no-?code|low-?code|agentic|\bagents?\b|\bseo\b|\bsem\b|\bppc\b|content|"
    r"copywrit|social media|digital|brand|\bgtm\b|go-to-market|demand gen|lifecycle|"
    r"performance|paid (media|social|search|ads)|\bads\b|advertising|media buy|\bcrm\b|"
    r"email|community|partnership|campaign|acquisition|business development|"
    r"communications|\bpr\b|public relations|analytics|analyst|e-?commerce|retention",
    re.I,
)

# Pure engineering / technical-trade titles ...
# User rule (2026-11-18): the candidate is NOT an engineer and does not want
# engineering roles applied to - including "AI Automation Engineer", which the
# earlier ENGINEER_OK exception used to let through. Any engineering title is
# now dropped. Non-engineering automation roles ("AI Automation Specialist",
# "Marketing Automation Manager", "Growth Automation Lead") contain no
# engineer/developer word and still pass.
ENGINEER = re.compile(
    r"\b(engineer|engineering|developer|programmer|architect|scientist|devops|devsecops|"
    r"\bsre\b|technician|electrician|fitter|machinist)\b",
    re.I,
)

# Clearly technical engineering titles: dropped even if they mention marketing.
HARD_ENGINEER = re.compile(
    r"\b(software|backend|back-end|frontend|front-end|full[- ]?stack|machine learning|ml|"
    r"data|platform|devops|cloud|security|web|mobile|ios|android|qa|test|embedded|hardware|"
    r"firmware|electrical|mechanical|civil|infrastructure|site reliability)\b"
    r"[^,;|]{0,25}?\b(engineer|engineering|developer)\b",
    re.I,
)

# Region markers in titles, e.g. "(PH)", "- NAMER", "U.S."
TITLE_REGION = re.compile(
    r"\((?:us|usa|u\.s\.|ph|uk|ca|canada|namer|latam|emea|eu|anz)\)|"
    r"[-–—|]\s*(?:namer|us|usa|uk|emea|latam|canada|philippines)\b|\bu\.s\.(?=\s|$)|"
    r"\b(?:us|usa|uk|emea|latam|namer)\s*$",
    re.I,
)

# Words in a location string that don't name a place.
_NON_PLACE = re.compile(
    r"\b(remote|fully remote|work from home|wfh|hybrid|on-?site|onsite|anywhere|"
    r"worldwide|global|international|distributed|flexible|n/?a|tbd|multiple locations?|"
    r"jobs?|home ?based|homebased|from home|all|location)\b",
    re.I,
)
_OPEN_EVERYWHERE = re.compile(r"\b(anywhere|worldwide|global|international)\b", re.I)


# Job boards often list Indian roles by city/state only ("Gurugram, Haryana").
_INDIA_PLACES = [
    "asia", "apac", "south asia", "bharat", "delhi", "new delhi", "ncr", "gurugram",
    "gurgaon", "noida", "mumbai", "bombay", "bengaluru", "bangalore", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "kochi", "chandigarh", "indore", "lucknow",
    "srinagar", "jammu", "kashmir", "haryana", "maharashtra", "karnataka", "tamil nadu",
    "telangana", "kerala", "gujarat", "rajasthan", "uttar pradesh", "west bengal",
]


def _candidate_places(location: str) -> list[str]:
    """'Pune, India' -> ['srinagar', 'india', ...Indian cities/states]."""
    parts = [p.strip().lower() for p in location.split(",") if p.strip()]
    if "india" in parts:
        parts += _INDIA_PLACES
    return parts


def classify(lead: JobLead, candidate_location: str = "") -> str:
    """Return '' to keep the lead, else a short reason it was dropped."""
    title = (lead.title or "").strip()
    if not title:
        return "no title"
    if not TARGET.search(title):
        return "not a target role"
    if HARD_ENGINEER.search(title):
        return "engineering role"
    if ENGINEER.search(title):
        return "engineering role"
    if TITLE_REGION.search(title):
        return "region-locked title"

    loc = (lead.location or "").strip()
    if loc and not _OPEN_EVERYWHERE.search(loc):
        places = _candidate_places(candidate_location)
        lowered = loc.lower()
        if not any(p and re.search(rf"\b{re.escape(p)}\b", lowered) for p in places):
            leftover = _NON_PLACE.sub(" ", loc)
            leftover = re.sub(r"[\s,;:/()\-–—|.]+", " ", leftover).strip()
            if leftover:
                return f"location-locked ({loc[:40]})"
    return ""


def prefilter_leads(
    leads: list[JobLead], candidate_location: str = ""
) -> tuple[list[JobLead], list[tuple[JobLead, str]]]:
    """Split leads into (kept, [(dropped, reason)])."""
    kept: list[JobLead] = []
    dropped: list[tuple[JobLead, str]] = []
    for lead in leads:
        reason = classify(lead, candidate_location)
        if reason:
            dropped.append((lead, reason))
        else:
            kept.append(lead)
    return kept, dropped


# --- Listing age (free) ----------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DATE_WORDS = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)\b", re.I)
_DATE_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")


def _parse_date(value: str):
    import datetime as dt

    m = _DATE_ISO.search(value or "")
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def too_old(lead: JobLead, max_age_days: int, today=None) -> str:
    """Reason to skip a listing posted more than max_age_days ago, else ''.

    Listings without a date are kept (checked again on their text later).
    """
    import datetime as dt

    if not max_age_days:
        return ""
    posted = _parse_date(lead.posted)
    today = today or dt.date.today()
    if posted and (today - posted).days > max_age_days:
        return f"posted {posted.isoformat()} ({(today - posted).days} days ago)"
    return ""


def stale_text(text: str, max_age_days: int, today=None) -> str:
    """For listings with no posting date: if every full date written in the job
    text is older than max_age_days (e.g. an HN post "on May 1, 2024"), skip."""
    import datetime as dt

    if not max_age_days or not text:
        return ""
    today = today or dt.date.today()
    dates = []
    for m in _DATE_WORDS.finditer(text):
        try:
            dates.append(dt.date(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2))))
        except ValueError:
            pass
    for m in _DATE_ISO.finditer(text):
        try:
            dates.append(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    dates = [d for d in dates if d <= today]
    if dates and (today - max(dates)).days > max_age_days:
        return f"newest date on the page is {max(dates).isoformat()}"
    return ""
