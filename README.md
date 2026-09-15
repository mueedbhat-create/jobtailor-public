# JobTailor

[![CI](https://github.com/mueedbhat-create/jobtailor-public/actions/workflows/ci.yml/badge.svg)](https://github.com/mueedbhat-create/jobtailor-public/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Your daily remote job application assistant. Finds remote jobs across multiple portals, tailors your resume to each one, exports PDFs, and prepares applications for you to submit.

## Who Benefits

**Job seekers** — Applying to 50+ jobs? Tailoring each resume manually takes hours. JobTailor does it in minutes.

**Career changers** — Need different resumes for different industries? JobTailor creates tailored versions automatically.

**Developers** — Want to automate your job search? The code is open source, easy to modify.

**Students/interns** — Looking for your first job? JobTailor finds opportunities and tailors applications.

**Freelancers** — Apply to many gigs? JobTailor scales the process.

## The Value

- **Time saved** — 2-3 hours per day of manual tailoring
- **Better results** — Tailored resumes get 3-5x more responses
- **AI-powered** — Uses LLMs to customize content intelligently
- **Free** — Open source, no subscription fees

## The Problem It Solves

Most people send the same generic resume to every job. That's why they get ignored. JobTailor fixes that.

## Features

### Core
- **Multi-source job discovery** — Wellfound, LinkedIn, HN Who's Hiring, RemoteOK, Adzuna, and more
- **AI-powered resume tailoring** — Customizes your resume for each job using LLMs
- **PDF generation** — Compiles tailored LaTeX resumes to PDFs
- **ATS text-layer verification** — Checks compiled PDFs for contact details, page count, and readable text
- **LLM fit gate** — Filters out pure software-engineer roles and location-ineligible jobs
- **Application queue** — Opens application pages for human review
- **Dashboard** — Next.js + shadcn/ui dashboard to track applications
- **Auto-apply mode** — Optional full auto-submit (use with care)

### Intelligence
- **Cross-day duplicate detection** — Prevents re-applying to jobs seen in previous runs
- **Salary range extraction** — Parses salary from JDs and filters by range
- **Custom weighted scoring** — Fit score based on salary, tech match, remote, company size
- **Company research enrichment** — Detects industry, tech stack from JD text
- **Response rate analytics** — Conversion funnel, source effectiveness, daily summaries

### Resume Management
- **Multi-resume support** — Define multiple base resumes, auto-pick best per job
- **Resume versioning/A-B testing** — Track which resume variations get more responses
- **Tailoring quality review** — See diffs of what LLM changed, approve/reject per section
- **Cover letter generation** — AI-generated cover letters per job

### Integrations
- **Telegram/Slack notifications** — Daily summaries and real-time alerts
- **Webhook integrations** — Send events to n8n, Zapier, or custom endpoints
- **CSV/JSON export** — Export full application history for spreadsheets/CRMs

### Operations
- **Docker + Docker Compose** — One-command containerized deployment
- **Gmail tracking** — Classifies confirmations/rejections/interviews/offers
- **Follow-up drafts** — Surfaces quiet applications, drafts follow-up messages
- **Internship pipeline** — Isolated track with separate queries and state
- **Daily scheduling** — macOS LaunchAgent for automated runs

## Quick Start

```bash
# Install
git clone https://github.com/mueedbhat-create/jobtailor-public.git
cd jobtailor-public
pip install -e .

# Or with uv (recommended)
uv sync

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your details (never commit it)

# Run the full pipeline
jobtailor run
```

## How It Works

A 5-stage production line:

1. **Find jobs** — Checks multiple sources, filtered to remote-only
2. **Read jobs** — Extracts job descriptions and requirements
3. **Tailor resume** — AI rewrites your resume to match each job
4. **Make PDF** — Compiles tailored resume with Tectonic
5. **Open applications** — Opens application pages for review

## Commands

| Command | What it does |
|---|---|
| `jobtailor run` | Full pipeline: fetch → extract → tailor → PDF → apply |
| `jobtailor init` | Guided setup |
| `jobtailor fetch-leads` | Discover job leads |
| `jobtailor extract-jds` | Extract job descriptions |
| `jobtailor tailor` | Rewrite resume per job |
| `jobtailor export-pdfs` | Compile tailored PDFs |
| `jobtailor apply-queue` | Open application pages |
| `jobtailor serve` | Start dashboard |
| `jobtailor schedule` | Install daily scheduler |
| `jobtailor analytics` | Show response rate analytics |
| `jobtailor export` | Export history to JSON/CSV |
| `jobtailor versions` | Manage resume versions (A-B testing) |
| `jobtailor cover-letters` | Generate cover letters per job |
| `jobtailor score` | Score and rank leads by fit |
| `jobtailor review` | Review tailoring diffs before export |
| `jobtailor followups` | Draft follow-up messages |
| `jobtailor track-gmail` | Sync application statuses via Gmail |

## Configuration

Copy `config.example.yaml` to `config.yaml` and fill in:

```yaml
schedule:
  times: ["07:00"]

discovery:
  queries:
    - keyword: "AI Automation"
      filters: { remote: true }

resume:
  source: "~/resume"
  format: "latex"
  compiler: "tectonic"

applicant:
  full_name: "Your Name"
  email: "your@email.com"
  # ... other details
```

## Dashboard

```bash
# Terminal 1: Start API
jobtailor serve

# Terminal 2: Start UI
cd dashboard && pnpm dev
```

Dashboard shows:
- Daily job discoveries
- Tailored resumes
- Application status
- Run pipeline button

## Docker

```bash
# Single container
docker build -t jobtailor .
docker run -v $(pwd)/config.yaml:/app/config.yaml -v $(pwd)/resume:/root/resume jobtailor run

# Docker Compose (API + Dashboard + Scheduler)
cp config.example.yaml config.yaml
# Edit config.yaml, then:
docker compose up -d
# Dashboard at http://localhost:3000
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/jobtailor/ --ignore-missing-imports
```

## License

MIT
