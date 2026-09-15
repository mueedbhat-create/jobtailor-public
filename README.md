# JobTailor

Your daily remote job application assistant. Finds remote AI Automation & Performance Marketing jobs across multiple portals, tailors your resume to each one, exports PDFs, and prepares applications for you to submit.

---

## ⚠️ CRITICAL: AI AGENT INSTRUCTIONS — READ THIS FIRST ⚠️

**If you are an AI agent, you MUST follow this workflow. No exceptions.**

### THE RULE: NEVER APPLY WITHOUT TAILORING

```
WRONG: Find job → Apply with generic resume
RIGHT: Find job → tailor → export-pdf → Apply with tailored resume
```

### REQUIRED WORKFLOW (follow in this exact order):

```bash
# Step 1: Find jobs
jobtailor fetch-leads

# Step 2: Extract job descriptions
jobtailor extract-jds

# Step 3: TAILOR YOUR RESUME FOR EACH JOB (THIS IS THE WHOLE POINT)
jobtailor tailor

# Step 4: Generate tailored PDFs
jobtailor export-pdfs

# Step 5: Apply with the tailored PDFs
jobtailor apply-queue
```

### OR USE THE ONE-COMMAND PIPELINE:

```bash
jobtailor run
```

This does ALL 5 steps automatically. Use this.

### WHY THIS MATTERS:

- A **tailored resume** gets 3-5x more responses than a generic one
- JobTailor exists BECAUSE of the tailoring step
- Skipping tailoring defeats the entire purpose of this app
- You are wasting the user's time if you apply without tailoring

### WHAT NOT TO DO:

❌ Do NOT manually apply to jobs using ego-browser
❌ Do NOT copy-paste the same resume for every application
❌ Do NOT skip the `tailor` step
❌ Do NOT skip the `export-pdfs` step
❌ Do NOT use `fillInput` or `typeText` to apply manually

### WHAT TO DO:

✅ Use `jobtailor run` or follow the 5-step pipeline
✅ Let the LLM tailor your resume for each job
✅ Generate unique PDFs for each application
✅ Apply with the tailored PDFs attached

### IF YOU ARE UNSURE:

Ask the user. Do not guess. Do not take shortcuts.

---

## How it works

A 5-stage production line, run automatically each morning:

1. **Find jobs** — checks 5 sources (Wellfound, LinkedIn, DailyRemote, SimplyHired, Adzuna), all filtered to remote-only. LinkedIn applications are never auto-submitted — they're always opened for you to review and submit yourself
2. **Read jobs** — pulls each job description and highlights what the employer is asking for
3. **Rewrite resume** — an AI adjusts your LaTeX resume to match each job, working on an isolated copy (your original resume folder is never touched). Only rephrases what's genuinely on your resume — nothing you couldn't defend in an interview
4. **Make PDF** — compiles the tailored resume with Tectonic
5. **Open applications** — opens each application page with your PDF attached; you review and click Submit

Then a local **dashboard** (Next.js + shadcn/ui over a FastAPI backend) shows each day's jobs, descriptions, tailored PDFs, and apply status — with an optional "run pipeline" button.

Applications are never auto-submitted by default — you're always in the loop (keeps accounts safe from portal ToS policies). Full auto-submit is available per-run from the dashboard, but be aware it can trip anti-bot checks.

## Fully automatic setup (hands-off)

Three commands and it runs itself every day:

```bash
jobtailor init        # guided setup: deps check, config, apply mode, Gmail
jobtailor schedule    # daily pipeline runs at your chosen times
jobtailor serve       # dashboard API + background Gmail status sync
```

With `apply.mode: full_auto` (the `init` default), each run finds new remote jobs, tailors the resume on an isolated copy, compiles the PDF, fills the application form, attaches the PDF, and submits — no clicks. With `gmail.auto_sync: true`, reply tracking (confirmation / rejection / interview / offer) syncs right after every run and on an interval while `jobtailor serve` is up.

> **Warning:** full auto-submit is the mode most likely to trip job boards' anti-bot checks. Hands-off convenience trades against account risk — prefer `pre_fill` if a board matters to you.

## Install

```bash
git clone <this-repo>
cd jobtailor
uv sync
cp config.example.yaml config.yaml   # fill in your values
```

## Usage

```bash
# Stage 1: discover leads
uv run jobtailor fetch-leads

# Show what was cached from the latest run
uv run jobtailor show-leads
```

## Config

Edit `config.yaml`: schedule times, job count, search queries, target companies, source toggles, resume path, and LLM provider.

## Status

**All 5 stages + scheduling + dashboard are built and tested (32 tests).** `jobtailor run` chains the whole pipeline; a LaunchAgent runs it daily at your configured time.

## Quick start

```bash
# 1. Install
brew install tectonic
uv sync

# 2. Configure
cp config.example.yaml config.yaml
#   - add your Adzuna key (optional; skip if using Wellfound only)
#   - point resume.source at your LaTeX resume dir

# 3. Run the whole pipeline (fetch -> extract -> tailor -> PDF -> open apps)
jobtailor run

# 4. Track / mark applications as you submit them
jobtailor apply-status
jobtailor apply-mark "<job-url>" submitted

# 5. Schedule daily (default 07:00, or set in config.yaml schedule.times)
jobtailor schedule

# 6. Dashboard (local)
#   terminal A: jobtailor serve            # FastAPI on 127.0.0.1:8000
#   terminal B: cd dashboard && pnpm dev   # Next.js on localhost:3000
```

## Commands

| Command | What it does |
|---|---|
| `jobtailor init` | Guided setup: dependency checks + writes config.yaml |
| `jobtailor run` | Full pipeline: fetch → extract → tailor → PDF → open applications |
| `jobtailor fetch-leads` | Discover job leads from enabled sources (remote-only) |
| `jobtailor extract-jds` | Extract job descriptions from leads (Scrapling) |
| `jobtailor tailor` | Rewrite resume per job on an isolated copy (opencode LLM) |
| `jobtailor export-pdfs` | Compile tailored branches to PDFs (Tectonic) |
| `jobtailor apply-queue` | Open each application page for human review + submit |
| `jobtailor apply-status` | Show prepared / submitted / skipped state |
| `jobtailor apply-mark <url> <status>` | Mark a job submitted or skipped |
| `jobtailor schedule` | Install macOS LaunchAgent for daily runs |
| `jobtailor serve` | Start the FastAPI backend for the dashboard |
| `jobtailor run --mode full_auto` | Pre-fill and submit applications automatically (use with care) |

## Roadmap

- [x] Stage 1a: Adzuna lead fetching (API)
- [x] Stage 1b: Wellfound lead fetching (scraper)
- [x] Stage 1c: LinkedIn, DailyRemote, SimplyHired scrapers (LinkedIn is never auto-submitted)
- [x] Stage 2: JD extraction (Scrapling — anti-bot bypass built in)
- [x] Stage 3: Resume tailoring (opencode LLM, isolated copies)
- [x] Stage 4: PDF export (Tectonic)
- [x] Stage 5: Application queue (open pages for human-in-the-loop submit)
- [x] Stage 5b: Auto-fill engine (ego-browser pre-fill + optional full auto-submit)
- [x] Dashboard (Next.js + shadcn/ui + FastAPI, local-only)
- [x] Scheduling (macOS LaunchAgent at configurable times)
- [x] `jobtailor run` — one-command full pipeline
- [ ] Stage 1c: AI gig platform setup (Mercor, Outlier profiles)

## Development

```bash
uv run pytest tests/
```