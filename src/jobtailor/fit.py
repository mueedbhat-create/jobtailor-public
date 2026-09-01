"""LLM fit gate: skip ONLY jobs specifically seeking an engineer.

User rule (2026-08-24): jobs about working WITH AI automations are always
eligible — even when titled "AI Automation Engineer" (that is literally the
candidate's role). Skip only when the job requires an actual engineer:
an engineering degree, hardware/mechanical/electrical/civil work, or a pure
software-development career (backend/frontend/fullstack/platform/ML).

Gate failure defaults to APPLY — uncertainty never loses a candidate.
"""

from __future__ import annotations

from jobtailor.models import JobDescription

FIT_RULE = """RULE: SKIP only if the job specifically requires an ENGINEER - engineering degree, or a pure software-developer career (builds production applications/systems as the core job: backend/frontend/fullstack/platform/ML engineering).
ALSO SKIP if the job restricts where applicants can be based (country, region, or timezone requirements) in a way that excludes the candidate's location - even if the role is titled remote. "Remote (anywhere)" or roles listing the candidate's country always pass.
APPLY if the actual work is: AI automation/workflows/agents (building with tools like n8n/Zapier/LLM APIs), marketing, growth, DevRel/marketing content, marketing ops, or solutions/consulting work where deep coding is not the core requirement.
Answer with exactly one word first - SKIP or APPLY - then one short sentence why. Include which rule (engineer or location) fired if SKIP."""

_DEFAULT_PROFILE = (
    "Candidate: marketing & AI-automation professional. Not an engineer, "
    "no engineering degree. Builds AI automations and workflows with n8n, "
    "Zapier, Make, LLM APIs, RAG, prompt engineering. Runs performance "
    "marketing (funnels, paid ads, CTR/ROAS)."
)

_SYSTEM = "You are a precise job-fit classifier."


def fit_verdict(llm, description: str, fit_profile: str = "", location: str = "") -> tuple[str, str]:
    """Classify one JD. Returns (verdict, reason); verdict is apply|skip."""
    profile = fit_profile.strip() or _DEFAULT_PROFILE
    loc = location.strip() or "not specified (treat as remote-eligible globally)"
    prompt = (
        f"{FIT_RULE}\n\nCandidate location: {loc}\n"
        f"Candidate profile: {profile}\n\n"
        f"JOB DESCRIPTION:\n{description[:6000]}"
    )
    out = llm.generate(_SYSTEM, prompt).strip()
    first = out.split()[0].rstrip(".,-—:") if out else ""
    if first.upper() == "SKIP":
        return "skip", out[:200]
    return "apply", out[:200]


def gate_jds(
    jds: list[JobDescription],
    llm,
    fit_profile: str = "",
    echo=None,
    location: str = "",
) -> tuple[list[JobDescription], list[tuple[JobDescription, str]]]:
    """Partition JDs into (keep, skipped). Gate errors default to keep."""
    keep: list[JobDescription] = []
    skipped: list[tuple[JobDescription, str]] = []
    for jd in jds:
        try:
            verdict, reason = fit_verdict(llm, jd.description, fit_profile, location)
        except Exception as exc:  # noqa: BLE001 - fail open to APPLY
            verdict, reason = "apply", f"gate error, defaulting to apply: {exc}"
        if verdict == "skip":
            skipped.append((jd, reason))
            if echo:
                echo(f"  [skip   ] {jd.title} @ {jd.company} - {reason[:100]}")
        else:
            keep.append(jd)
            if echo:
                echo(f"  [apply  ] {jd.title} @ {jd.company}")
    return keep, skipped
