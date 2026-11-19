# JobTailor — instructions for AI agents

## If the user asks to apply for jobs or internships

Run ONE command and end your turn:

    scripts/apply.sh <limit> <jobs|internships|both> --bg     # default: 5 both

Reply "Started — you'll get a notification; then run scripts/status.sh." Nothing else.
This applies however it is phrased ("/apply - jobs", "apply jobs", "run jobtailor").

For results, run `scripts/status.sh` once and report each job: title, company,
ready to submit or why not.

Do NOT: read files to "understand" the project first, poll or tail logs, re-run,
debug, edit code or config, open a browser, or apply by hand. Every extra AI turn
re-sends the whole conversation; one babysat run cost ~700k tokens. The pipeline
needs no help.

## How the pipeline spends AI tokens

`jobtailor run` does everything in plain code except one small AI call per job
(`brain.py`): fit check + resume tailoring + optional form note, ~2k tokens,
fact-checked against the real resume, cached, and hard-capped by
`llm.max_tokens_per_run`. Never add a second AI call per job.

## Rules

- Never apply without a tailored resume. Never invent experience.
- The user clicks Submit (`--mode pre_fill`); never auto-submit unless told.
- Free models only (`llm.provider: zen`, model ids ending in `-free`). Never paid.
- If unsure, ask the user. Do not guess.
