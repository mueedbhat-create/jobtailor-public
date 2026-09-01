# JobTailor

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

- **Multi-source job discovery** — Wellfound, LinkedIn, HN Who's Hiring, RemoteOK, Adzuna, and more
- **AI-powered resume tailoring** — Customizes your resume for each job using LLMs
- **PDF generation** — Compiles tailored LaTeX resumes to PDFs
- **Application queue** — Opens application pages for human review
- **Dashboard** — Next.js + shadcn/ui dashboard to track applications
- **Auto-apply mode** — Optional full auto-submit (use with care)

## Quick Start

```bash
# Install
git clone <this-repo>
cd jobtailor
uv sync

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your details

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

## Development

```bash
uv run pytest tests/
```

## License

MIT
