# JobTailor Dashboard

Local control room for your JobTailor application pipeline: every job you applied for, the tailored PDF you applied with, the form fields you filled in, and Gmail-tracked outcomes (confirmation / rejection / interview / offer).

Next.js 16 + React 19 + Tailwind v4 + shadcn/ui-style primitives over the FastAPI backend.

## Run it

```bash
# terminal 1 — API
jobtailor serve                 # FastAPI on 127.0.0.1:8000

# terminal 2 — dashboard
pnpm install
pnpm dev                        # http://localhost:3000
```

No data yet? Append `?mock=1` to any URL (or set `NEXT_PUBLIC_MOCK=1`) to explore with a realistic sample fixture. Mock mode is not sticky: as soon as the API answers, the dashboard switches to live data.

## Views

- **Overview** — lifecycle stats (applied / awaiting / confirmations / rejections / interviews / offers), recent applications, run-pipeline card, Gmail sync.
- **Applications** — searchable, filterable list of every application. Click a row for details: inline PDF preview + download, the form fields you filled in, and the Gmail activity timeline per job.
- **Pipeline** — apply-mode selector (open only / pre-fill / auto-submit) and live run output.

## API it consumes

| Endpoint | Purpose |
|---|---|
| `GET /api/applications` | enriched entries (lead join, `pdf_url`, `fields`, `tracking`) |
| `GET /api/tracking` | aggregate totals |
| `POST /api/tracking/sync` | run a Gmail tracking sync |
| `GET/POST /api/run(/status)` | pipeline trigger + status |
| `GET /api/resumes/{branch}` | tailored PDF file |
| `GET /api/jd?url=` | extracted job description |

## Gmail tracking setup

Enable in `config.yaml`:

```yaml
gmail:
  enabled: true
  client_secrets_file: "client_secret.json"   # Google Cloud Console OAuth client
  token_file: "gmail_token.json"
```

Complete the OAuth flow once so the token file exists, then use `jobtailor track-gmail` or the dashboard's **Sync Gmail now** button.

## Development

```bash
pnpm lint          # eslint
npx tsc --noEmit   # types
pnpm build         # production build
node ../.gauntlet/probes/dom-probe.js   # DOM probes (needs pnpm dev running)
```

Structure: `app/` routes · `components/` views & widgets · `components/ui/` primitives · `lib/api.ts` typed client · `lib/seed.ts` mock fixture.
