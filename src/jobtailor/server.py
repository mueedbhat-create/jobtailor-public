"""FastAPI backend for the JobTailor dashboard.

Serves the data the pipeline produces (jobs, JDs, PDFs, application status)
and lets the dashboard trigger pipeline runs.

Endpoints:
  GET  /api/health
  GET  /api/jobs                    — all job leads grouped by day
  GET  /api/jobs/{day}              — job leads for one day
  GET  /api/jds/{day}               — extracted JDs for one day
  GET  /api/jds/{day}/{file}        — one JD JSON
  GET  /api/resumes/{branch}        — tailored PDF file
  GET  /api/applications            — application status per job
  POST /api/run                     — trigger a pipeline run
  GET  /api/run/status              — last run status/log tail

All data is read from the pipeline's `output/` directory.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel


def _auto_sync_once() -> dict | None:
    """One Gmail auto-sync attempt if enabled in config; None otherwise."""
    from jobtailor.config import ConfigError, load_config
    from jobtailor.tracking import collect_submitted_apps, maybe_auto_sync

    try:
        cfg = load_config(Path("config.yaml"))
    except ConfigError:
        return None
    if not cfg.gmail.enabled or not cfg.gmail.auto_sync:
        return None
    leads = _leads_index()
    apps = collect_submitted_apps()
    for app in apps:
        app["company"] = leads.get(app["url"], {}).get("company", app["company"])
    return maybe_auto_sync(cfg, apps)


def _auto_sync_loop(stop: threading.Event) -> None:
    time.sleep(20)
    while not stop.is_set():
        try:
            _auto_sync_once()
        except Exception:  # noqa: BLE001 - background loop must never die
            pass
        try:
            from jobtailor.config import ConfigError, load_config

            cfg = load_config(Path("config.yaml"))
            interval = max(5, int(cfg.gmail.sync_interval_minutes)) * 60
        except Exception:  # noqa: BLE001
            interval = 3600
        stop.wait(interval)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    stop = threading.Event()
    thread = threading.Thread(target=_auto_sync_loop, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()


app = FastAPI(title="JobTailor API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT = Path("output")

_TRACK_SUBDIR = {
    "jobs": Path(""),
    "internships": Path("internships"),
}


def _track_output(track: str) -> Path:
    """Resolve the output base for a track ('jobs' default, or 'internships').

    The jobs track is the top-level OUTPUT dir (so existing OUTPUT patches in
    tests keep working); internships live under OUTPUT/internships.
    """
    sub = _TRACK_SUBDIR.get(track, _TRACK_SUBDIR["jobs"])
    return OUTPUT / sub


class RunRequest(BaseModel):
    mode: str = "human_in_the_loop"  # or "full_auto" | "pre_fill"
    limit: int = 15


class _RunState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.last_status = "idle"  # idle | running | done | error
        self.last_output = ""
        self.last_started: str | None = None


run_state = _RunState()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "date": date.today().isoformat()}


@app.get("/api/jobs")
def jobs() -> dict:
    """All cached job leads, grouped by day."""
    leads_dir = OUTPUT / "leads"
    if not leads_dir.exists():
        return {"days": {}}
    days: dict[str, list[dict]] = {}
    for path in sorted(leads_dir.glob("*.json")):
        data = json.loads(path.read_text())
        day = data.get("date", path.stem)
        days[day] = data.get("leads", [])
    return {"days": days}


@app.get("/api/jds/{day}")
def jds_for_day(day: str) -> dict:
    """Extracted JDs for a given day (YYYY-MM-DD)."""
    jds_dir = OUTPUT / "jds"
    if not jds_dir.exists():
        return {"jds": []}
    jds = []
    for path in sorted(jds_dir.glob("*.json")):
        try:
            jds.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return {"jds": jds}


@app.get("/api/jd")
def jd_by_url(url: str) -> dict:
    """Find a JD by its original job URL."""
    jds_dir = OUTPUT / "jds"
    if not jds_dir.exists():
        raise HTTPException(404, "No JDs extracted yet")
    for path in sorted(jds_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("url") == url:
            return data
    raise HTTPException(404, "No JD for this URL yet")


@app.get("/api/jds/{day}/{file}")
def jd_detail(day: str, file: str) -> dict:
    path = OUTPUT / "jds" / f"{file}.json"
    if not path.exists():
        raise HTTPException(404, "JD not found")
    return json.loads(path.read_text())


@app.get("/api/resumes/{branch:path}")
def resume_pdf(branch: str, track: str = "jobs") -> FileResponse:
    """Serve a tailored resume PDF by branch name (apply/<slug>)."""
    if not branch or branch.startswith(("/", "~")) or ".." in branch.split("/"):
        raise HTTPException(400, "Invalid branch name")
    base = (_track_output(track) / "resumes").resolve()
    path = (base / f"{branch}.pdf").resolve()
    if not path.is_relative_to(base):
        raise HTTPException(400, "Invalid branch name")
    if not path.exists():
        raise HTTPException(404, "PDF not found")
    return FileResponse(path, media_type="application/pdf", filename=f"{branch}.pdf")


def _iter_app_records(track: str = "jobs") -> Iterator[tuple[str, dict]]:
    """Yield (day, entry) from every parseable application state file.

    Corrupt or wrong-shape entries are skipped individually — one bad record
    never takes down an endpoint.
    """
    apps_dir = _track_output(track) / "applications"
    if not apps_dir.exists():
        return
    for path in sorted(apps_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for url, entry in data.items():
            if isinstance(entry, dict) and isinstance(url, str) and url:
                yield path.stem, {"url": url, **entry}


def _leads_index(track: str = "jobs") -> dict[str, dict]:
    idx: dict[str, dict] = {}
    leads_dir = _track_output(track) / "leads"
    if not leads_dir.exists():
        return idx
    for path in sorted(leads_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for lead in data.get("leads", []) if isinstance(data, dict) else []:
            if isinstance(lead, dict) and lead.get("url"):
                idx[lead["url"]] = lead
    return idx


def _tracking_index(track: str = "jobs") -> dict[str, dict]:
    idx: dict[str, dict] = {}
    tracking_dir = _track_output(track) / "tracking"
    if not tracking_dir.exists():
        return idx
    for path in sorted(tracking_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for rec in data.get("apps", []) if isinstance(data, dict) else []:
            if isinstance(rec, dict) and rec.get("url"):
                idx[rec["url"]] = rec
    return idx


@app.get("/api/applications")
def applications(track: str = "jobs") -> dict:
    """Enriched application entries: state + lead metadata + PDF URL + tracking."""
    leads = _leads_index(track)
    tracking = _tracking_index(track)
    days: dict[str, list[dict]] = {}
    for day, entry in _iter_app_records(track):
        url = entry["url"]
        lead = leads.get(url, {})
        branch = str(entry.get("branch") or "")
        fields = entry.get("fields")
        days.setdefault(day, []).append({
            "url": url,
            "status": str(entry.get("status") or "pending"),
            "branch": branch,
            "pdf": str(entry.get("pdf") or ""),
            "pdf_url": f"/api/resumes/{branch}?track={track}" if branch and track != "jobs" else f"/api/resumes/{branch}" if branch else "",
            "opened_at": str(entry.get("opened_at") or ""),
            "applied_at": str(entry.get("applied_at") or ""),
            "note": str(entry.get("note") or ""),
            "fields": fields if isinstance(fields, dict) else {},
            "company": str(lead.get("company") or ""),
            "title": str(lead.get("title") or ""),
            "source": str(lead.get("source") or ""),
            "location": str(lead.get("location") or ""),
            "remote": bool(lead.get("remote", True)),
            "tracking": tracking.get(url),
        })
    return {"days": days}


@app.get("/api/tracking")
def tracking_summary(track: str = "jobs") -> dict:
    """Aggregate application-tracking totals across all runs."""
    tracking = _tracking_index(track)
    totals = {
        "applied": 0,
        "no_response": 0,
        "confirmation": 0,
        "rejected": 0,
        "interview": 0,
        "offer": 0,
    }
    by_status: dict[str, int] = {}
    last_synced = ""
    for _, entry in _iter_app_records(track):
        status = str(entry.get("status") or "pending")
        by_status[status] = by_status.get(status, 0) + 1
        if entry.get("applied_at") or status == "submitted":
            totals["applied"] += 1
            rec = tracking.get(entry["url"])
            kind = (rec or {}).get("status") or "no_response"
            if kind in totals:
                totals[kind] += 1
            last_synced = max(last_synced, str((rec or {}).get("last_checked") or ""))
    return {"totals": totals, "by_status": by_status, "last_synced": last_synced}


@app.post("/api/tracking/sync")
def tracking_sync(track: str = "jobs") -> dict:
    """Run a Gmail tracking sync. Uniform response on every path."""
    from jobtailor.config import GmailConfig, ConfigError, load_config
    from jobtailor.tracking import GmailTracker

    def _respond(status: str, message: str, result: dict | None = None) -> dict:
        out = {
            "status": status,
            "message": message,
            "updated": 0,
            "entries": [],
            "last_synced": None,
        }
        if result:
            out.update({k: result.get(k) for k in ("updated", "entries", "last_synced")})
        return out

    try:
        cfg = load_config(Path("config.yaml"))
    except ConfigError as exc:
        return _respond("unconfigured", f"Config not available: {exc}")

    gm = cfg.gmail
    if not gm.enabled:
        return _respond(
            "unconfigured",
            "Gmail tracking is disabled. Enable it under gmail.enabled in config.yaml.",
        )
    if not gm.token_file or not Path(gm.token_file).expanduser().exists():
        return _respond(
            "unconfigured",
            "Gmail token file missing. Run the OAuth flow once to create it.",
        )

    leads = _leads_index(track)
    apps = [
        {
            "url": e["url"],
            "company": str(leads.get(e["url"], {}).get("company") or ""),
            "status": str(e.get("status") or ""),
            "applied_at": str(e.get("applied_at") or ""),
        }
        for _, e in _iter_app_records(track)
    ]
    tracker = GmailTracker(gm, output_dir=_track_output(track) / "tracking")
    try:
        result = tracker.sync(apps)
    except Exception as exc:  # noqa: BLE001 - surfaced, never raised
        return _respond("error", f"Tracking sync failed: {exc}")
    return _respond(str(result.get("status")), str(result.get("message")), result)


@app.get("/api/tailored")
def tailored_map() -> dict:
    """Map job URL -> tailored branch from output/tailored.json."""
    path = OUTPUT / "tailored.json"
    if not path.exists():
        return {"jobs": []}
    return {"jobs": json.loads(path.read_text())}


@app.post("/api/run")
def trigger_run(req: RunRequest) -> dict:
    """Start a pipeline run in the background (opt-in from the dashboard)."""
    with run_state.lock:
        if run_state.running:
            raise HTTPException(409, "A run is already in progress")
        run_state.running = True
        run_state.last_status = "running"
        run_state.last_started = date.today().isoformat()

    def _work() -> None:
        cmd = ["jobtailor", "run", "--limit", str(req.limit)]
        if req.mode == "full_auto":
            cmd = ["jobtailor", "run", "--limit", str(req.limit), "--mode", "full_auto"]
        elif req.mode == "pre_fill":
            cmd = ["jobtailor", "run", "--limit", str(req.limit), "--mode", "pre_fill"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            output = proc.stdout or proc.stderr
        except Exception as exc:  # noqa: BLE001
            output = str(exc)
        with run_state.lock:
            run_state.running = False
            run_state.last_status = "error" if "Traceback" in output or proc.returncode != 0 else "done"
            run_state.last_output = output[-4000:]

    threading.Thread(target=_work, daemon=True).start()
    return {"started": True, "status": "running"}


@app.get("/api/run/status")
def run_status() -> dict:
    with run_state.lock:
        return {
            "running": run_state.running,
            "status": run_state.last_status,
            "started": run_state.last_started,
            "output": run_state.last_output,
        }


@app.get("/api/analytics")
def analytics(period: str = "all") -> dict:
    """Response rate analytics and conversion funnel."""
    from jobtailor.analytics import AnalyticsEngine

    engine = AnalyticsEngine()
    if period == "today":
        from datetime import date
        return engine.daily_summary(date.today().isoformat())
    elif period == "sources":
        return {"sources": engine.source_effectiveness()}
    return engine.overview()


@app.get("/api/export")
def export_data(format: str = "json") -> dict:
    """Export application history."""
    from jobtailor.export import export_csv, export_json

    if format == "csv":
        path = export_csv()
        return {"format": "csv", "path": str(path)}
    path = export_json()
    return {"format": "json", "path": str(path)}


@app.get("/api/versions")
def versions_list() -> dict:
    """List resume versions and their analytics."""
    from jobtailor.versioning import ResumeVersionManager

    mgr = ResumeVersionManager()
    return {
        "versions": [v.__dict__ for v in mgr.list_versions()],
        "analytics": mgr.analytics(),
        "best": mgr.best_version(),
    }


@app.get("/api/scoring/top")
def scoring_top(limit: int = 20) -> dict:
    """Top-scored leads."""
    from jobtailor.scoring import rank_jobs
    from jobtailor.fetch import load_leads_from_cache

    files = sorted(glob.glob(str(Path("output/leads") / "*.json")))
    if not files:
        return {"jobs": []}

    leads = load_leads_from_cache(files[-1])
    jobs = [{"title": l.title, "company": l.company, "source": l.source, "remote": l.remote} for l in leads]
    ranked = rank_jobs(jobs)
    return {"jobs": ranked[:limit]}


@app.get("/api/cover-letters/{branch}")
def cover_letter(branch: str) -> dict:
    """Get cover letter for a tailored resume."""
    path = Path("output/cover_letters") / f"{branch}.txt"
    if not path.exists():
        raise HTTPException(404, "Cover letter not found")
    return {"branch": branch, "letter": path.read_text()}