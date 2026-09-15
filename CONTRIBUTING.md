# Contributing to JobTailor

## AI AGENT INSTRUCTIONS

**If you are an AI agent using this app, you MUST follow this workflow.**

### THE GOLDEN RULE

**NEVER apply to a job without tailoring the resume first.**

### Required Pipeline

```bash
jobtailor run
```

This runs the full pipeline:
1. `fetch-leads` — Find remote jobs
2. `extract-jds` — Extract job descriptions
3. `tailor` — Customize resume for each job (THE MOST IMPORTANT STEP)
4. `export-pdfs` — Generate tailored PDFs
5. `apply-queue` — Open applications with tailored PDFs

### Why Tailoring Matters

- Tailored resumes get 3-5x more responses
- JobTailor exists BECAUSE of the tailoring step
- Skipping tailoring wastes the user's time and defeats the app's purpose

### Prohibited Actions

Do NOT:
- Apply manually using ego-browser
- Use the same resume for every application
- Skip `jobtailor tailor`
- Skip `jobtailor export-pdfs`
- Use `fillInput` or `typeText` to apply

### If Unsure

Ask the user. Never guess. Never take shortcuts.
