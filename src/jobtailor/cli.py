"""Command-line interface for JobTailor."""

from __future__ import annotations

import glob
import shutil
from pathlib import Path

import typer

from jobtailor.config import load_config
from jobtailor.extract import ScraplingExtractor, extract_all
from jobtailor.fetch import LeadFetcher, load_leads_from_cache
from jobtailor.llm import LLMConfig
from jobtailor.models import JobDescription
from jobtailor.pdf import PdfVerifier, export_all
from jobtailor.tailor import tailor_all

app = typer.Typer(add_completion=False)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config.yaml"),
    config: str = typer.Option("config.yaml", help="Target config path"),
):
    """Guided setup: check dependencies and write config.yaml."""
    from jobtailor.setup import build_config, check_dependencies, validate_resume_dir

    target = Path(config)
    if target.exists() and not force:
        typer.echo(f"{config} already exists. Use --force to overwrite.")
        raise typer.Exit(1)

    typer.echo("Checking dependencies:")
    for d in check_dependencies():
        mark = "ok" if d.ok else "MISSING"
        typer.echo(f"  [{mark:<6}] {d.name}" + ("" if d.ok else f" - {d.hint}"))
    typer.echo("")

    resume = typer.prompt("Resume directory (LaTeX, contains resume.tex)", default="~/resume")
    rpath, err = validate_resume_dir(resume)
    while rpath is None:
        typer.echo(f"  {err}")
        resume = typer.prompt("Resume directory")
        rpath, err = validate_resume_dir(resume)

    keywords = typer.prompt(
        "Job keywords (comma-separated)",
        default="AI Automation Engineer, Performance Marketing, AI Marketing Automation",
    )
    companies = typer.prompt("Target companies (comma-separated, blank to skip)", default="")
    per_run = int(typer.prompt("Applications per run", default="15"))
    times = typer.prompt("Daily run times (comma-separated HH:MM)", default="07:00")

    typer.echo("\nApply mode:")
    typer.echo("  1) full_auto - fills forms, attaches the PDF, submits automatically")
    typer.echo("     (hands-off, but most likely to trip job boards' anti-bot checks)")
    typer.echo("  2) pre_fill - fills everything, you click submit")
    typer.echo("  3) human_in_the_loop - just opens the job pages")
    mode_choice = typer.prompt("Choice", default="1")
    mode = {"1": "full_auto", "2": "pre_fill", "3": "human_in_the_loop"}.get(
        mode_choice.strip(), "full_auto"
    )

    adzuna_id = typer.prompt("Adzuna app_id (blank to skip)", default="")
    adzuna_key = typer.prompt("Adzuna app_key (blank to skip)", default="")

    gmail: dict = {"enabled": False}
    if typer.confirm("\nEnable Gmail reply tracking (confirmations/rejections/interviews)?", default=True):
        gmail = {
            "enabled": True,
            "client_secrets_file": typer.prompt(
                "OAuth client secrets JSON path", default="client_secret.json"
            ),
            "token_file": typer.prompt("Token cache path", default="gmail_token.json"),
            "auto_sync": typer.confirm("Auto-sync tracking in the background?", default=True),
            "sync_interval_minutes": int(typer.prompt("Sync interval (minutes)", default="60")),
        }
        typer.echo("  Note: finish the OAuth flow once so the token file exists.")

    answers = {
        "resume_source": str(rpath),
        "keywords": [k.strip() for k in keywords.split(",") if k.strip()],
        "companies": [c.strip() for c in companies.split(",") if c.strip()],
        "jobs_per_run": per_run,
        "times": [t.strip() for t in times.split(",") if t.strip()],
        "apply_mode": mode,
        "adzuna_id": adzuna_id.strip(),
        "adzuna_key": adzuna_key.strip(),
        "gmail": gmail,
    }
    target.write_text(build_config(answers))

    typer.echo(f"\nWrote {target}. Next steps:")
    typer.echo("  jobtailor run          # first pipeline run")
    if gmail.get("enabled"):
        typer.echo("  # finish Gmail OAuth once so the token file exists")
    typer.echo("  jobtailor schedule     # daily runs at your chosen times")
    typer.echo("  jobtailor serve        # dashboard API (+ background Gmail sync)")
    typer.echo("  cd dashboard && pnpm dev   # dashboard at http://localhost:3000")


@app.command()
def fetch_leads(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    cache: bool = typer.Option(True, help="Write results to output/leads/"),
    show: bool = typer.Option(False, help="Print discovered leads"),
):
    """Run lead discovery across all enabled sources."""
    cfg = load_config(config)
    fetcher = LeadFetcher(cfg)
    batch = fetcher.run(cache=cache)
    for source, count in batch.source_counts.items():
        typer.echo(f"  {source:<12} {count} leads")
    typer.echo(f"  total (deduped, remote): {len(batch.leads)}")
    if show:
        for lead in batch.leads:
            typer.echo(f"  - {lead.title} @ {lead.company} ({lead.source})")


@app.command()
def extract_jds(
    leads_file: str = typer.Option("", help="Path to cached leads JSON (default: latest in output/leads/)"),
    out: str = typer.Option("output/jds", help="Directory to write extracted JDs"),
):
    """Extract job descriptions for cached leads using Scrapling."""
    import json
    import glob

    files = sorted(glob.glob(str(Path("output/leads") / "*.json")))
    if not leads_file and not files:
        typer.echo("No leads found. Run 'jobtailor fetch-leads' first.")
        raise typer.Exit(1)

    source = leads_file or files[-1]
    leads = load_leads_from_cache(source)
    typer.echo(f"Extracting {len(leads)} job descriptions...")
    jds = extract_all(leads, ScraplingExtractor())

    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    written = 0
    for jd in jds:
        path = outdir / f"{written}_{jd.company.replace(' ', '_')}_{jd.title.replace(' ', '_')[:40]}.json"
        path.write_text(json.dumps(jd.__dict__, indent=2))
        written += 1

    typer.echo(f"Extracted {written}/{len(leads)} JDs -> {outdir}/")
    for jd in jds[:5]:
        typer.echo(f"  - {jd.company} | {jd.title} | keywords: {', '.join(jd.keywords[:6])}")


@app.command()
def tailor(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    jds_dir: str = typer.Option("output/jds", help="Directory with extracted JD JSON files"),
    resume_dir: str = typer.Option("", help="Resume directory (default: from config)"),
):
    """Tailor the resume for each extracted JD on an isolated copy."""
    import glob
    import json

    cfg = load_config(config)
    resume = resume_dir or cfg.resume.source

    files = sorted(glob.glob(str(Path(jds_dir) / "*.json")))
    if not files:
        typer.echo(f"No JDs found in {jds_dir}/. Run 'jobtailor extract-jds' first.")
        raise typer.Exit(1)

    jds = []
    for f in files:
        data = json.loads(Path(f).read_text())
        jds.append(
            JobDescription(
                url=data["url"],
                company=data["company"],
                title=data["title"],
                description=data["description"],
                keywords=data.get("keywords", []),
            )
        )

    typer.echo(f"Tailoring resume in {resume} for {len(jds)} jobs...")
    llm_cfg = LLMConfig(provider=cfg.llm.provider, model=cfg.llm.model)
    results = tailor_all(jds, resume_dir=resume, llm_config=llm_cfg)

    typer.echo(f"Tailored {len(results)}/{len(jds)} resumes:")
    for r in results:
        typer.echo(f"  - branch: {r.branch}  (job: {r.job_url})")

    if results:
        _write_tailored(results)


def _write_tailored(results, path="output/tailored.json") -> None:
    import json

    Path(path).write_text(
        json.dumps(
            [{"job_url": r.job_url, "branch": r.branch} for r in results],
            indent=2,
        )
    )


@app.command()
def export_pdfs(
    out_dir: str = typer.Option("output/resumes", help="Directory for exported PDFs"),
    branch: str = typer.Option("", help="Export only this slug (default: all tailored resumes)"),
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
):
    """Compile tailored resumes to PDFs with Tectonic."""
    from jobtailor.models import TailoredResume
    from jobtailor.pdf import PdfExporter, PdfVerifier

    cfg = load_config(config)
    a = cfg.applicant
    contact_terms = [t for t in (a.email, a.phone, a.full_name) if t]

    slugs = [branch] if branch else _tailored_slugs()
    if not slugs:
        typer.echo("No tailored resumes found. Run 'jobtailor tailor' first.")
        raise typer.Exit(1)

    exporter = PdfExporter("output/tailored", out_dir,
                           verifier=PdfVerifier(contact_terms))
    results = [TailoredResume(job_url="", branch=s) for s in slugs]
    paths = []
    for r in results:
        try:
            paths.append(exporter.export(r))
        except Exception as exc:  # noqa: BLE001 - per-job isolation
            typer.echo(f"  [warn] {r.branch}: {exc}")

    typer.echo(f"Exported {len(paths)} PDF(s):")
    for p in paths:
        typer.echo(f"  - {p}")


def _tailored_slugs() -> list[str]:
    root = Path("output/tailored")
    if not root.exists():
        return []
    return sorted(
        str(p.relative_to(root))
        for p in root.glob("apply/*/resume.tex")
    )


@app.command()
def apply_queue(
    out_dir: str = typer.Option("output/resumes", help="Directory with exported PDFs"),
    state_dir: str = typer.Option("output/applications", help="Application state directory"),
    browser: str = typer.Option("open", help="Browser: 'open' (default) or 'ego'"),
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
):
    """Open each prepared application page for the user to review and submit."""
    from jobtailor.apply import ApplicantProfile, ApplicationQueue, Browser
    from jobtailor.models import TailoredResume

    cfg = load_config(config)

    slugs = _tailored_slugs()
    if not slugs:
        typer.echo("No tailored resumes found. Run 'jobtailor tailor' first.")
        raise typer.Exit(1)

    import json

    tailored = {}
    tp = Path("output/tailored.json")
    if tp.exists():
        for item in json.loads(tp.read_text()):
            tailored[item["branch"]] = item["job_url"]

    resumes = []
    for slug in slugs:
        pdf = Path(out_dir) / f"{slug}.pdf"
        resumes.append(
            TailoredResume(
                job_url=tailored.get(slug, ""),
                branch=slug,
                pdf_path=pdf if pdf.exists() else None,
            )
        )

    queue = ApplicationQueue(cfg.apply, state_dir, Browser(browser), profile=_applicant_profile(cfg))
    opened = queue.prepare(resumes)
    typer.echo(f"Opened {len(opened)} application page(s). Review each and click Submit.")
    for url in opened:
        typer.echo(f"  - {url}")


def _applicant_profile(cfg) -> ApplicantProfile:
    from jobtailor.apply import ApplicantProfile

    a = cfg.applicant
    return ApplicantProfile(
        full_name=a.full_name,
        email=a.email,
        phone=a.phone,
        location=a.location,
        linkedin=a.linkedin,
        website=a.website,
        headline=a.headline,
    )


@app.command()
def apply_status(
    state_dir: str = typer.Option("output/applications", help="Application state directory"),
):
    """Show the application queue status."""
    from jobtailor.apply import ApplicationQueue

    queue = ApplicationQueue(state_dir=state_dir)
    entries = queue.status()
    if not entries:
        typer.echo("Queue is empty. Run 'jobtailor apply-queue' first.")
        return
    for e in entries:
        pdf = f"  pdf={e.get('pdf')}" if e.get("pdf") else ""
        typer.echo(f"  [{e['status']:<10}] {e['url']}{pdf}")


@app.command()
def apply_mark(
    job_url: str = typer.Argument(..., help="Job URL to mark"),
    status: str = typer.Argument(..., help="'submitted' or 'skipped'"),
    state_dir: str = typer.Option("output/applications", help="Application state directory"),
):
    """Mark a job as submitted or skipped."""
    from jobtailor.apply import ApplicationQueue

    queue = ApplicationQueue(state_dir=state_dir)
    if status == "submitted":
        queue.mark_submitted(job_url)
    elif status == "skipped":
        queue.mark_skipped(job_url)
    else:
        typer.echo("status must be 'submitted' or 'skipped'")
        raise typer.Exit(1)
    typer.echo(f"Marked {job_url} as {status}.")


@app.command()
def run(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    limit: int = typer.Option(15, help="Maximum jobs to process this run"),
    mode: str = typer.Option("", help="Apply mode override: 'full_auto', 'pre_fill', or 'human_in_the_loop'"),
):
    """Run the full pipeline: fetch -> extract -> tailor -> export -> apply."""
    cfg = load_config(config)
    run_pipeline(
        cfg,
        limit=limit,
        mode=mode,
        queries=None,
        output_base="output",
        echo=typer.echo,
    )


@app.command()
def run_internships(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    limit: int = typer.Option(0, help="Maximum jobs to process (default: from internships.jobs_per_run)"),
    mode: str = typer.Option("", help="Apply mode override"),
):
    """Run the internship pipeline: fetch -> extract -> tailor -> export -> apply.

    Isolated from the main full-time track (separate output dirs + state).
    """
    cfg = load_config(config)
    if not cfg.internships.enabled:
        typer.echo("Internships track is disabled. Set internships.enabled=true in config.yaml.")
        raise typer.Exit(1)
    run_pipeline(
        cfg,
        limit=limit or cfg.internships.jobs_per_run,
        mode=mode,
        queries=cfg.internships.queries or None,
        output_base=cfg.internships.output_base,
        title_filter="intern",
        echo=typer.echo,
    )


def run_pipeline(
    cfg,
    limit: int,
    mode: str,
    queries: list[str] | None,
    output_base: str,
    echo=None,
    title_filter: str | None = None,
) -> None:
    """Run the full pipeline against a given output base + query set.

    `output_base` isolates where state/PDFs live (e.g. "output" for full-time,
    "output/internships" for internships). `queries` overrides discovery
    queries when given. `title_filter`, when set, keeps only leads whose title
    contains the keyword (case-insensitive) — used to keep the internship
    track focused on actual internships. `echo` is the output printer.
    """
    from jobtailor.apply import ApplicantProfile, ApplicationQueue, Browser
    from jobtailor.config import ApplyConfig
    from jobtailor.fetch import LeadFetcher
    from jobtailor.models import TailoredResume
    from jobtailor.pdf import PdfExporter

    if echo is None:
        echo = print
    out = Path(output_base)
    resume = cfg.resume.source
    apply_mode = mode or cfg.apply.mode

    # 1. Fetch leads
    echo("[1/5] Fetching leads...")
    batch = LeadFetcher(cfg, output_dir=out / "leads").run(queries=queries)
    if title_filter:
        before = len(batch.leads)
        batch.leads = [
            lead for lead in batch.leads
            if title_filter in (lead.title or "").lower()
        ]
        echo(f"  {before} leads -> {len(batch.leads)} matching '{title_filter}'")
    echo(f"  {len(batch.leads)} leads (deduped, remote)")
    if not batch.leads:
        echo("  No leads. Check config sources.")
        return

    # 2. Extract JDs (cap at limit)
    echo(f"[2/5] Extracting JDs ({min(limit, len(batch.leads))} jobs)...")
    jds = extract_all(batch.leads[:limit], ScraplingExtractor())
    echo(f"  {len(jds)} JDs extracted")
    if not jds:
        echo("  Extraction failed for all leads.")
        return

    # 2.5 Fit gate: drop ONLY jobs specifically seeking an engineer
    if cfg.discovery.skip_engineer_specific:
        from jobtailor.fit import gate_jds
        from jobtailor.llm import LLMClient

        echo("[2.5/5] Fit gate (skip only specifically-engineer roles)...")
        gate_llm = LLMClient(LLMConfig(provider=cfg.llm.provider, model=cfg.llm.model))
        jds, gate_skipped = gate_jds(jds, gate_llm, cfg.applicant.fit_profile, echo=echo, location=cfg.applicant.location)
        echo(f"  {len(jds)} fit, {len(gate_skipped)} skipped")

    # 3. Tailor resumes
    echo("[3/5] Tailoring resumes...")
    llm_cfg = LLMConfig(provider=cfg.llm.provider, model=cfg.llm.model)
    results = tailor_all(jds, resume_dir=resume, llm_config=llm_cfg, tailored_dir=out / "tailored")
    echo(f"  {len(results)} tailored")
    if not results:
        echo("  Tailoring failed for all jobs.")
        return
    _write_tailored(results, out / "tailored.json")

    # 4. Export PDFs
    echo("[4/5] Exporting PDFs...")
    a = cfg.applicant
    contact_terms = [t for t in (a.email, a.phone, a.full_name) if t]
    exporter = PdfExporter(out / "tailored", out / "resumes",
                           verifier=PdfVerifier(contact_terms))
    for r in results:
        try:
            exporter.export(r)
        except Exception as exc:  # noqa: BLE001 - per-job isolation
            echo(f"  [warn] {r.branch}: {exc}")
    echo(f"  {len(results)} PDFs exported")

    # 5. Apply — human_in_the_loop (open tabs), pre_fill, or full_auto
    echo(f"[5/5] Applying ({apply_mode})...")
    for r in results:
        pdf = out / "resumes" / f"{r.branch}.pdf"
        r.pdf_path = pdf if pdf.exists() else None

    queue = ApplicationQueue(
        cfg.apply,
        out / "applications",
        browser=Browser("ego" if apply_mode != "human_in_the_loop" else "open"),
        profile=_applicant_profile(cfg),
    )

    if apply_mode == "human_in_the_loop":
        opened = queue.prepare(results)
        echo(f"  Opened {len(opened)} pages. Review each and click Submit.")
        echo("Run 'jobtailor apply-mark <url> submitted' as you go, "
             "or 'jobtailor apply-status' to track progress.")
    elif apply_mode == "pre_fill":
        summaries = queue.auto_apply(results, submit=False)
        for s in summaries:
            echo(f"  [{s['status']:<10}] {s['url']}")
            if s.get("note"):
                echo(f"             {s['note']}")
    else:
        from jobtailor.apply import split_never_auto

        source_map = {lead.url: lead.source for lead in batch.leads}
        auto_resumes, manual_resumes = split_never_auto(results, source_map)
        summaries = queue.auto_apply(auto_resumes, submit=True)
        for s in summaries:
            echo(f"  [{s['status']:<10}] {s['url']}")
            if s.get("note"):
                echo(f"             {s['note']}")
        if manual_resumes:
            queue.prepare(manual_resumes)
            echo(
                f"  [manual  ] {len(manual_resumes)} never-auto "
                "application(s) opened for you to submit (LinkedIn)"
            )

    from jobtailor.tracking import collect_submitted_apps, maybe_auto_sync

    auto = maybe_auto_sync(cfg, collect_submitted_apps(out / "applications", out / "leads"),
                           echo=echo, output_dir=out / "tracking")
    if auto is None and cfg.gmail.enabled:
        echo("  [gmail] auto_sync disabled — run 'jobtailor track-gmail' to check replies.")


@app.command()
def track_gmail(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    tracking_dir: str = typer.Option("output/tracking", help="Directory for tracking state"),
):
    """Sync application statuses against Gmail (confirmations, rejections, interviews)."""
    from jobtailor.tracking import GmailTracker, collect_submitted_apps

    cfg = load_config(config)
    apps = collect_submitted_apps()
    tracker = GmailTracker(cfg.gmail, output_dir=tracking_dir)
    result = tracker.sync(apps)
    typer.echo(result.get("message") or result.get("status"))
    for e in result.get("entries", []):
        typer.echo(f"  [{e['status']:<12}] {e['url']} ({len(e.get('emails', []))} email(s))")


@app.command()
def followups(
    days: int = typer.Option(10, help="Surface applications silent for N+ days"),
    state_dir: str = typer.Option("output/applications", help="Application state directory"),
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
):
    """List quiet applications and draft follow-ups (drafts only, never sends)."""
    from jobtailor.followup import MAX_FOLLOWUPS, draft_followup, find_quiet

    cfg = load_config(config)
    apps = _submitted_apps_from_state(state_dir)
    quiet = find_quiet(apps, quiet_days=days)
    if not quiet:
        typer.echo(f"No submitted applications silent for {days}+ days.")
        return

    name = cfg.applicant.full_name or ""
    typer.echo(f"{len(quiet)} quiet application(s):")
    for q in quiet:
        typer.echo(f"\n  [{q.days_since} days] {q.company or q.url}")
        typer.echo(f"    follow-ups so far: {q.followups_sent}/{MAX_FOLLOWUPS}")
        typer.echo(f"    url: {q.url}")
        if q.followups_sent < MAX_FOLLOWUPS:
            typer.echo("    draft (review before sending — not sent):")
            for line in draft_followup(q, name=name).splitlines():
                typer.echo(f"      {line}")


def _submitted_apps_from_state(state_dir: str) -> list[dict]:
    import json

    apps: list[dict] = []
    for f in sorted(glob.glob(str(Path(state_dir) / "*.json"))):
        try:
            state = json.loads(Path(f).read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(state, dict):
            continue
        for url, entry in state.items():
            if isinstance(entry, dict) and entry.get("status") == "submitted":
                apps.append({
                    "url": url,
                    "company": str(entry.get("company") or ""),
                    "applied_at": str(entry.get("applied_at") or ""),
                    "followups_sent": entry.get("followups_sent", 0),
                })
    return apps


@app.command()
def schedule(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    times: str = typer.Option("", help="Comma-separated HH:MM run times (default: from config)"),
    label: str = typer.Option("com.jobtailor.daily", help="LaunchAgent label"),
):
    """Install a macOS LaunchAgent to run the full-time pipeline daily."""
    cfg = load_config(config)
    when = [t.strip() for t in times.split(",") if t.strip()] or cfg.schedule.times
    _install_launch_agent(label, "run", config, when)


@app.command()
def schedule_internships(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    times: str = typer.Option("08:00", help="Comma-separated HH:MM run times"),
    label: str = typer.Option("com.jobtailor.internships", help="LaunchAgent label"),
):
    """Install a macOS LaunchAgent to run the internship pipeline daily."""
    cfg = load_config(config)
    if not cfg.internships.enabled:
        typer.echo("Internships track is disabled. Set internships.enabled=true in config.yaml.")
        raise typer.Exit(1)
    when = [t.strip() for t in times.split(",") if t.strip()] or ["08:00"]
    _install_launch_agent(label, "run-internships", config, when)


def _install_launch_agent(label: str, subcommand: str, config: str, when: list[str]) -> None:
    """Write + load a LaunchAgent plist running `jobtailor <subcommand>`."""
    import os
    import textwrap

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{label}.plist"

    cwd = Path.cwd().resolve()
    exe = str(Path.cwd().resolve() / ".venv" / "bin" / "jobtailor")
    if not Path(exe).exists():
        exe = shutil.which("jobtailor") or "jobtailor"
    hours = sorted({int(t.split(":")[0]) for t in when if ":" in t})
    minutes = sorted({int(t.split(":")[1]) for t in when if ":" in t})

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
        <string>{subcommand}</string>
        <string>--config</string>
        <string>{str(Path(config).resolve())}</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        {''.join(f'<dict><key>Hour</key><integer>{h}</integer><key>Minute</key><integer>{m}</integer></dict>' for h in hours for m in minutes)}
    </array>
    <key>WorkingDirectory</key>
    <string>{cwd}</string>
    <key>StandardOutPath</key>
    <string>{cwd}/output/{subcommand}.log</string>
    <key>StandardErrorPath</key>
    <string>{cwd}/output/{subcommand}.err.log</string>
</dict>
</plist>
"""
    plist_path.write_text(textwrap.dedent(plist))
    os.system(f"launchctl unload {plist_path} 2>/dev/null; launchctl load {plist_path}")
    typer.echo(f"Installed {label} at {plist_path}")
    typer.echo(f"  Runs 'jobtailor {subcommand}' at {', '.join(when)} daily")
    typer.echo(f"  Logs: {cwd}/output/{subcommand}.log")


@app.command()
def unschedule(
    label: str = typer.Option("com.jobtailor.daily", help="LaunchAgent label"),
):
    """Remove the JobTailor LaunchAgent."""
    import os

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    os.system(f"launchctl unload {plist_path} 2>/dev/null; rm -f {plist_path}")
    typer.echo(f"Removed {label}.")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
):
    """Start the FastAPI backend for the dashboard."""
    import uvicorn

    from jobtailor.server import app as fastapi_app

    typer.echo(f"JobTailor API on http://{host}:{port}")
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command()
def show_leads(
    path: str = typer.Option("output/leads", help="Cache dir with YYYY-MM-DD.json files"),
):
    """Show leads cached from the latest fetch run."""
    files = sorted(glob.glob(str(Path(path) / "*.json")))
    if not files:
        typer.echo("No cached leads found.")
        return
    latest = files[-1]
    leads = load_leads_from_cache(latest)
    typer.echo(f"{len(leads)} leads from {latest}:")
    for lead in leads:
        typer.echo(f"  - {lead.title} @ {lead.company} ({lead.source}) | {lead.url}")


if __name__ == "__main__":
    app()