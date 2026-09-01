"""Gmail-based application status tracking.

For each submitted application, searches the mailbox for messages from the
company and classifies them into a lifecycle status: confirmation (application
received), rejected, interview (moved forward), offer, or other.

The classifier is pure and deterministic — keyword/regex based, negation
aware, with hard precedence so rejection language can never be overridden by
a weak "offer" substring. Google API imports are lazy so this module (and the
whole pipeline) works without google libs installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

CONFIRMATION = "confirmation"
REJECTED = "rejected"
INTERVIEW = "interview"
OFFER = "offer"
OTHER = "other"
NO_RESPONSE = "no_response"

STATUS_PRECEDENCE = [OFFER, INTERVIEW, REJECTED, CONFIRMATION]

_AUTO_REPLY_PATTERNS = [
    r"\bautomatic reply\b",
    r"\bauto[- ]reply\b",
    r"\bout of (the )?office\b",
    r"\bon (annual )?(leave|vacation|holiday)\b",
    r"\baway from (the )?office\b",
    r"\bcurrently unavailable\b",
    r"\bno[- ]?reply@",
    r"\bdo not reply\b",
    r"\bunsub(scribe)?\b",
    r"\bspecial offer\b",
    r"\blimited[- ]time offer\b",
    r"\bdaily digest\b",
    r"\bnewsletter\b",
    r"\bviewed your (profile|resume)\b",
    r"\bjob alert\b",
    r"\bwe will keep your (resume|cv|application) on file\b",
]

_STRONG_REJECT_PATTERNS = [
    r"\bunable to (extend an )?offer\b",
    r"\bnot able to (extend an )?offer\b",
    r"\bcannot (extend an )?offer\b",
    r"\bcan'?t (extend an )?offer\b",
    r"\bnot (be )?offering you\b",
    r"\bnot in a position to offer\b",
    r"\bwe regret\b",
    r"\bi regret\b",
    r"\bregretfully\b",
    r"\bafter careful (review|consideration)\b",
    r"\bdecided (not )?to move forward\b",
    r"\bnot moving forward\b",
    r"\bwon'?t be moving forward\b",
    r"\bmoving forward with (other|another|different)\b",
    r"\bother (candidates|applicants)\b",
    r"\banother candidate\b",
    r"\bdifferent (candidate|profile|direction)\b",
    r"\bposition has been (filled|closed)\b",
    r"\brole has been (filled|closed)\b",
    r"\bno longer (available|under consideration|being considered)\b",
    r"\bwill not be (progressing|advancing)\b",
    r"\bnot (be )?(progressing|advancing)\b",
    r"\bchosen (candidates|to proceed)\b",
    r"\bprofile does not (match|fit)\b",
]

_WEAK_REJECT_PATTERNS = [
    r"\bunfortunately\b",
    r"\bsadly\b",
]

_INTERVIEW_PATTERNS = [
    r"\binterview\b",
    r"\bphone screen\b",
    r"\bscreening call\b",
    r"\bschedule a (call|chat|conversation|meeting|interview)\b",
    r"\bbook(ing)? a (time|call|slot)\b",
    r"\bcalendar (invite|link)\b",
    r"\bcall with\b",
    r"\bchat with\b",
    r"\btalk to\b",
    r"\bnext steps?\b",
    r"\bvirtual (call|onsite|interview)\b",
    r"\bhiring (manager|team) (call|interview|chat)\b",
    r"\btechnical (round|screen|interview)\b",
    r"\bcoding (round|challenge|assessment)\b",
    r"\btake[- ]home\b",
]

_OFFER_PATTERNS = [
    r"\bextend(ed|ing)? an offer\b",
    r"\bpleased to offer\b",
    r"\bhappy to offer\b",
    r"\bexcited to offer\b",
    r"\bproud to offer\b",
    r"\boffer letter\b",
    r"\bjob offer\b",
    r"\boffer of employment\b",
    r"\bformal offer\b",
    r"\bwelcome (aboard|to the team)\b",
    r"\bcongratulations\b",
    r"\bcompensation (package|details)\b",
    r"\bsign(ing)? (bonus|the offer)\b",
    r"\bstart date\b",
]

_CONFIRMATION_PATTERNS = [
    r"\bthank(s| you) for (your )?(applying|application|interest)\b",
    r"\bapplication (has been |was )?(received|submitted)\b",
    r"\bwe have received your application\b",
    r"\breceived your application\b",
    r"\byour application\b.*\b(received|confirmed|processed)\b",
    r"\bapplication (is|was) (successful(l)? submitted|complete)\b",
    r"\bthanks for reaching out\b",
    r"\bwe'?ve got(n)? your (application|details)\b",
]


def _matches(patterns: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _compiled(prefixes: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in prefixes]


_AUTO = _compiled(_AUTO_REPLY_PATTERNS)
_STRONG_REJECT = _compiled(_STRONG_REJECT_PATTERNS)
_WEAK_REJECT = _compiled(_WEAK_REJECT_PATTERNS)
_INTERVIEW = _compiled(_INTERVIEW_PATTERNS)
_OFFER = _compiled(_OFFER_PATTERNS)
_CONFIRM = _compiled(_CONFIRMATION_PATTERNS)


def classify(subject: str, body: str) -> str:
    """Classify one email into a lifecycle kind.

    Order matters: auto-reply/newsletter noise first (weak words like
    "unfortunately" inside an out-of-office stay OTHER), then rejection —
    strong decision phrases always win, weak ones only outside noise —
    then interview, offer, confirmation. Returns OTHER when nothing matches.
    """
    text = f"{subject or ''}\n{body or ''}"
    if not text.strip():
        return OTHER

    if _matches(_AUTO, text) and not _matches(_STRONG_REJECT, text):
        return OTHER

    if _matches(_STRONG_REJECT, text) or _matches(_WEAK_REJECT, text):
        return REJECTED
    if _matches(_OFFER, text):
        return OFFER
    if _matches(_INTERVIEW, text):
        return INTERVIEW
    if _matches(_CONFIRM, text):
        return CONFIRMATION
    return OTHER


def resolve_status(kinds: list[str]) -> str:
    """Resolve per-email kinds into one app status using hard precedence."""
    present = set(kinds)
    for status in STATUS_PRECEDENCE:
        if status in present:
            return status
    return NO_RESPONSE


_JOB_BOARD_SUFFIXES = (
    "greenhouse.io", "lever.co", "workable.com", "smartrecruiters.com",
    "ashbyhq.com", "myworkdayjobs.com", "bamboohr.com", "recruitee.com",
    "teamtailor.com", "jobvite.com", "eightfold.ai", "paylocity.com",
)

_HOST_PREFIXES = ("www", "jobs", "job", "careers", "career", "apply",
                  "boards", "workday", "myworkdayjobs", "m", "workat")


def query_for(company: str, domain: str) -> str:
    """Build a Gmail search query for a company. Empty when nothing to match."""
    parts: list[str] = []
    if domain:
        d = domain.strip().lstrip("@").lower()
        if d and "." in d:
            parts.append(f"from:{d}")
            labels = [l for l in d.split(".") if l]
            if labels[0] in _HOST_PREFIXES and len(labels) >= 2:
                base = labels[1]
            else:
                base = labels[0]
            if len(base) >= 3:
                parts.append(f"from:{base}")
    if company:
        c = company.strip()
        if c:
            parts.append(f'"{c}"')
    seen: set[str] = set()
    unique = [p for p in parts if not (p in seen or seen.add(p))]
    return " OR ".join(unique)


def _domain_for(url: str, company: str) -> str:
    """Best-effort sender domain guess from the job URL host."""
    from urllib.parse import urlsplit

    try:
        host = urlsplit(url).netloc.lower().split(":")[0]
    except ValueError:
        return ""
    labels = [l for l in host.split(".") if l]
    while len(labels) > 2 and labels[0] in _HOST_PREFIXES:
        labels = labels[1:]
    remaining = ".".join(labels)
    if any(remaining.endswith(s) for s in _JOB_BOARD_SUFFIXES):
        return ""
    if len(labels) < 2:
        slug = re.sub(r"[^a-z0-9]+", "", (company or "").lower())
        return f"{slug}.com" if slug else ""
    if labels[0] in ("linkedin", "wellfound", "remoteok", "glassdoor", "indeed", "adzuna"):
        slug = re.sub(r"[^a-z0-9]+", "", (company or "").lower())
        return f"{slug}.com" if slug else ""
    return ".".join(labels[-2:])


@dataclass
class TrackingRecord:
    url: str
    status: str = NO_RESPONSE
    last_checked: str = ""
    source: str = "gmail"
    emails: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "status": self.status,
            "last_checked": self.last_checked,
            "source": self.source,
            "emails": self.emails,
        }


class NoCredentials(Exception):
    """Raised when Gmail credentials are missing or invalid."""


def is_configured(config=None) -> bool:
    from jobtailor.config import GmailConfig

    cfg = config or GmailConfig()
    if not cfg.enabled:
        return False
    token = Path(cfg.token_file).expanduser() if cfg.token_file else None
    return bool(token and token.exists())


class GmailTracker:
    """Syncs application statuses against a Gmail mailbox."""

    def __init__(
        self,
        config=None,
        gmail_service=None,
        output_dir: str | Path = "output/tracking",
        max_messages: int = 10,
    ):
        from jobtailor.config import GmailConfig

        self._config = config or GmailConfig()
        self._service = gmail_service
        self._output_dir = Path(output_dir)
        self._max = max_messages

    def sync(self, apps: list[dict]) -> dict:
        """Track each submitted app; returns a summary dict.

        Never raises for credential problems — returns an explicit error dict
        instead so callers (CLI, server) can surface a clean message.
        """
        submitted = [
            a for a in apps
            if isinstance(a, dict)
            and a.get("url")
            and (a.get("status") == "submitted" or a.get("applied_at"))
        ]
        if not submitted:
            return {"status": "no_apps", "message": "No submitted applications to track.",
                    "updated": 0, "entries": [], "last_synced": None}

        service = self._service
        if service is None:
            try:
                service = self._build_service()
            except NoCredentials as exc:
                return {"status": "unconfigured", "message": str(exc),
                        "updated": 0, "entries": [], "last_synced": None}
            except Exception as exc:  # noqa: BLE001 - surfaced, not raised
                return {"status": "error", "message": f"Gmail unavailable: {exc}",
                        "updated": 0, "entries": [], "last_synced": None}

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entries: list[dict] = []
        updated = 0
        for app in submitted:
            record = TrackingRecord(url=app["url"], last_checked=now)
            try:
                q = query_for(app.get("company", ""), _domain_for(app["url"], app.get("company", "")))
                if q:
                    msgs = self._search(service, q)
                    for m in msgs:
                        kind = classify(m.get("subject", ""), m.get("snippet", ""))
                        m["kind"] = kind
                        record.emails.append(m)
                    record.status = resolve_status([m["kind"] for m in record.emails])
                else:
                    record.source = None
                updated += 1
            except Exception:  # noqa: BLE001 - per-app isolation
                record.source = None
                record.status = NO_RESPONSE
            entries.append(record.as_dict())

        self._write(entries)
        return {"status": "ok", "message": f"Tracked {updated} application(s).",
                "updated": updated, "entries": entries, "last_synced": now}

    def _build_service(self):
        if not is_configured(self._config):
            raise NoCredentials(
                "Gmail is not configured. Set gmail.enabled=true and provide a token file "
                "(run the OAuth flow once with your client secrets)."
            )
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise NoCredentials(f"Google libraries not installed: {exc}") from exc

        token_path = Path(self._config.token_file).expanduser()
        creds = Credentials.from_authorized_user_file(str(token_path))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        return build("gmail", "v1", credentials=creds)

    def _search(self, service, query: str) -> list[dict]:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=self._max)
            .execute()
        )
        out: list[dict] = []
        for msg in resp.get("messages", []):
            full = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata",
                     metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
            snippet = full.get("snippet", "")
            out.append({
                "id": msg["id"],
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "snippet": snippet[:300],
                "date": headers.get("date", ""),
            })
        return out

    def _write(self, entries: list[dict]) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"{date.today().isoformat()}.json"
        existing: dict[str, dict] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
                existing = {e.get("url", ""): e for e in data.get("apps", []) if isinstance(e, dict)}
            except (json.JSONDecodeError, AttributeError):
                existing = {}
        for e in entries:
            existing[e["url"]] = e
        path.write_text(json.dumps({"date": date.today().isoformat(), "apps": list(existing.values())}, indent=2))

    def load_latest(self) -> dict[str, dict]:
        """Most recent tracking records keyed by URL."""
        files = sorted(self._output_dir.glob("*.json"))
        if not files:
            return {}
        try:
            data = json.loads(files[-1].read_text())
        except json.JSONDecodeError:
            return {}
        return {e.get("url", ""): e for e in data.get("apps", []) if isinstance(e, dict) and e.get("url")}


def collect_submitted_apps(
    state_dir: str | Path = "output/applications",
    leads_dir: str | Path = "output/leads",
) -> list[dict]:
    """Submitted applications (url/company/status/applied_at) from state files.

    Shared by the CLI, the pipeline run hook, and the server auto-sync loop.
    Corrupt or wrong-shape records are skipped individually.
    """
    companies: dict[str, str] = {}
    ldir = Path(leads_dir)
    if ldir.exists():
        for f in sorted(ldir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for lead in data.get("leads", []) if isinstance(data, dict) else []:
                if isinstance(lead, dict) and lead.get("url"):
                    companies[lead["url"]] = str(lead.get("company") or "")

    apps: list[dict] = []
    sdir = Path(state_dir)
    if not sdir.exists():
        return apps
    for f in sorted(sdir.glob("*.json")):
        try:
            state = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(state, dict):
            continue
        for url, entry in state.items():
            if (
                isinstance(entry, dict)
                and isinstance(url, str)
                and url
                and (entry.get("status") == "submitted" or entry.get("applied_at"))
            ):
                apps.append({
                    "url": url,
                    "company": companies.get(url, ""),
                    "status": str(entry.get("status") or ""),
                    "applied_at": str(entry.get("applied_at") or ""),
                })
    return apps


def maybe_auto_sync(cfg, apps: list[dict], echo=None, output_dir: str | Path = "output/tracking") -> dict | None:
    """Run a Gmail sync when auto_sync is enabled; None when disabled.

    Accepts a full Config (reads cfg.gmail) or a GmailConfig directly.
    `output_dir` isolates where tracking state is written (per track).
    """
    gm = getattr(cfg, "gmail", cfg)
    if gm is None or not gm.enabled or not gm.auto_sync:
        return None
    tracker = GmailTracker(gm, output_dir=output_dir)
    result = tracker.sync(apps)
    if echo:
        echo(f"  [gmail] {result.get('message') or result.get('status')}")
        for e in result.get("entries", []):
            echo(f"    [{e['status']:<12}] {e['url']}")
    return result
