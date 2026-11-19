# JobTailor

Your daily remote job application assistant. Finds remote AI Automation & Performance Marketing jobs across multiple portals, tailors your resume to each one, exports PDFs, and prepares applications for you to submit.

---

## Why it is cheap to run

Most "AI job apply" tools send the whole resume and job page to a model several
times per job, or let a chat agent drive the browser. JobTailor uses AI for
exactly one thing - judgement - and does everything else in plain code:

| Step | Done by | AI tokens |
|---|---|---|
| Find jobs, dedupe, skip ones already handled | code | 0 |
| Title / location / role filter | code | 0 |
| Check the job has a fillable application form | code (browser) | 0 |
| Trim the job page to requirements only | code | 0 |
| Obvious no-fits (e.g. "US only", "5+ years software development") | code | 0 |
| **Fit check + resume tailoring + form note** | **one AI call, JSON out** | **~2,000** |
| Rebuild the LaTeX, fact-check every change, compile PDF, fill the form | code | 0 |

- **One call per job, ~2k tokens.** 5 jobs + 5 internships is about 20k tokens.
- **Free models, called directly** (`llm.provider: zen`): no opencode CLI wrapper
  (which adds ~20k tokens of its own prompt to every call), no key, never paid.
- **Hard budget** (`llm.max_tokens_per_run`, default 30,000): a run stops before
  it can go over. Every run prints exact usage: `== AI usage: 10 AI call(s), 19,840 tokens`.
- **Cached:** re-running the same job costs 0 tokens.
- **Stops instantly** when the free daily allowance is used up - no retries.

### Accuracy: the AI picks, it does not write your resume

Your resume is split into numbered bullets (E1.1, E1.2 ...) and skill groups.
The model only returns which bullets and skills matter most for this job, up to
three rewordings, and skills to surface. Code then rebuilds the resume from your
own LaTeX. A reworded bullet is used only if it keeps every number and tool of
the original and passes the fact-check (`truth.py`) - otherwise your original
wording stays. A skill is surfaced only if it already appears in your
experience. Nothing can be invented, and the PDF can't break.

## How it works

1. **Find jobs** - Wellfound, RemoteOK, HN "Who is hiring", Freehire, LinkedIn, Internshala (remote only)
2. **Filter for free** - title/location rules and already-applied URLs, no AI
3. **Form check** - opens each job in ego-browser and keeps only ones with a fillable form
4. **One AI call per job** - fit + tailoring + note (see above)
5. **PDF** - compiles the tailored resume with Tectonic
6. **Pre-fill** - fills the form and attaches the PDF in ego-browser; you click Submit

Run it with `scripts/apply.sh 5 both` (or `jobtailor run --mode pre_fill`) and
read the result with `scripts/status.sh`. No AI chat is needed at any point.

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
| `jobtailor tailor` | Tailor the resume per job (one AI call each) on an isolated copy |
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
- [x] Stage 3: Resume tailoring (one AI call per job, fact-checked, isolated copies)
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