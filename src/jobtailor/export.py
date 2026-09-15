"""CSV and JSON export of application history.

Provides utilities to export the full application pipeline data
for external analysis in spreadsheets, CRMs, or data tools.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path


def export_json(
    state_dir: str | Path = "output/applications",
    leads_dir: str | Path = "output/leads",
    tracking_dir: str | Path = "output/tracking",
    output_path: str | Path = "output/export.json",
) -> Path:
    """Export all application data as a single JSON file."""
    state_path = Path(state_dir)
    leads_path = Path(leads_dir)
    tracking_path = Path(tracking_dir)

    # Load leads index
    leads_idx: dict[str, dict] = {}
    if leads_path.exists():
        for f in leads_path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for lead in data.get("leads", []):
                if isinstance(lead, dict) and lead.get("url"):
                    leads_idx[lead["url"]] = lead

    # Load tracking index
    tracking_idx: dict[str, dict] = {}
    if tracking_path.exists():
        for f in tracking_path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for rec in data.get("apps", []):
                if isinstance(rec, dict) and rec.get("url"):
                    tracking_idx[rec["url"]] = rec

    # Merge applications with lead + tracking data
    records: list[dict] = []
    if state_path.exists():
        for f in sorted(state_path.glob("*.json")):
            try:
                state = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(state, dict):
                continue
            for url, entry in state.items():
                if not isinstance(entry, dict) or not url:
                    continue
                lead = leads_idx.get(url, {})
                track = tracking_idx.get(url, {})
                records.append({
                    "url": url,
                    "company": lead.get("company", entry.get("company", "")),
                    "title": lead.get("title", ""),
                    "source": lead.get("source", ""),
                    "remote": lead.get("remote", True),
                    "status": entry.get("status", ""),
                    "branch": entry.get("branch", ""),
                    "pdf": entry.get("pdf", ""),
                    "opened_at": entry.get("opened_at", ""),
                    "applied_at": entry.get("applied_at", ""),
                    "note": entry.get("note", ""),
                    "tracking_status": track.get("status", ""),
                    "tracking_last_checked": track.get("last_checked", ""),
                    "tracking_emails": len(track.get("emails", [])),
                })

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, indent=2))
    return out


def export_csv(
    state_dir: str | Path = "output/applications",
    leads_dir: str | Path = "output/leads",
    tracking_dir: str | Path = "output/tracking",
    output_path: str | Path = "output/export.csv",
) -> Path:
    """Export all application data as CSV."""
    # Reuse JSON export logic to get records
    json_path = Path("output/export.json")
    if not json_path.exists():
        export_json(state_dir, leads_dir, tracking_dir, json_path)

    records = json.loads(json_path.read_text())

    if not records:
        # Write empty CSV with headers
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "url", "company", "title", "source", "remote", "status",
                "branch", "pdf", "opened_at", "applied_at", "note",
                "tracking_status", "tracking_last_checked", "tracking_emails",
            ])
        return out

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "url", "company", "title", "source", "remote", "status",
        "branch", "pdf", "opened_at", "applied_at", "note",
        "tracking_status", "tracking_last_checked", "tracking_emails",
    ]

    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    return out


def export_summary(
    state_dir: str | Path = "output/applications",
    leads_dir: str | Path = "output/leads",
) -> dict:
    """Export a quick summary of application stats."""
    state_path = Path(state_dir)
    leads_path = Path(leads_dir)

    total_apps = 0
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_company: dict[str, int] = {}

    if state_path.exists():
        for f in state_path.glob("*.json"):
            try:
                state = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(state, dict):
                continue
            for url, entry in state.items():
                if not isinstance(entry, dict) or not url:
                    continue
                total_apps += 1
                status = entry.get("status", "unknown")
                by_status[status] = by_status.get(status, 0) + 1

    if leads_path.exists():
        for f in leads_path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for lead in data.get("leads", []):
                if isinstance(lead, dict):
                    src = lead.get("source", "unknown")
                    by_source[src] = by_source.get(src, 0) + 1
                    co = lead.get("company", "unknown")
                    by_company[co] = by_company.get(co, 0) + 1

    return {
        "total_applications": total_apps,
        "by_status": by_status,
        "by_source": by_source,
        "top_companies": dict(sorted(by_company.items(), key=lambda x: x[1], reverse=True)[:20]),
        "exported_at": date.today().isoformat(),
    }
