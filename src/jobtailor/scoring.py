"""Custom weighted scoring model.

Computes a fit score for each job based on configurable weights
for salary, remote policy, tech stack match, company size, and more.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoringWeights:
    """Weights for the scoring model (all between 0 and 1, summed to 1.0)."""

    salary: float = 0.25
    tech_match: float = 0.25
    remote: float = 0.15
    company_size: float = 0.10
    title_match: float = 0.15
    source_reliability: float = 0.10

    def normalized(self) -> "ScoringWeights":
        total = (
            self.salary + self.tech_match + self.remote
            + self.company_size + self.title_match + self.source_reliability
        )
        if total == 0:
            return ScoringWeights()
        return ScoringWeights(
            salary=self.salary / total,
            tech_match=self.tech_match / total,
            remote=self.remote / total,
            company_size=self.company_size / total,
            title_match=self.title_match / total,
            source_reliability=self.source_reliability / total,
        )


@dataclass
class ScoringProfile:
    """User preferences for scoring."""

    preferred_salary_min: float = 0
    preferred_salary_max: float = 999999
    preferred_tech: list[str] = field(default_factory=list)
    prefer_remote: bool = True
    preferred_company_sizes: list[str] = field(default_factory=list)  # "1-10", "51-200", etc.
    preferred_titles: list[str] = field(default_factory=list)
    source_reliability: dict[str, float] = field(default_factory=dict)  # source -> 0-1 score


_SOURCE_DEFAULTS = {
    "linkedin": 0.8,
    "wellfound": 0.7,
    "hn_hiring": 0.9,
    "remoteok": 0.7,
    "adzuna": 0.6,
    "simplyhired": 0.5,
    "dailyremote": 0.5,
    "freehire": 0.6,
}


def score_job(
    job: dict,
    weights: ScoringWeights | None = None,
    profile: ScoringProfile | None = None,
) -> dict:
    """Score a job posting. Returns {score, breakdown}.

    `job` should contain: title, company, source, salary (optional),
    tech_stack (optional), remote (optional), company_size (optional).
    """
    w = (weights or ScoringWeights()).normalized()
    p = profile or ScoringProfile()

    # Salary score
    salary = job.get("salary") or {}
    salary_mid = None
    if salary.get("min") and salary.get("max"):
        salary_mid = (salary["min"] + salary["max"]) / 2
    elif salary.get("min"):
        salary_mid = salary["min"]
    elif salary.get("max"):
        salary_mid = salary["max"]

    if salary_mid is not None and p.preferred_salary_max > 0:
        if p.preferred_salary_min <= salary_mid <= p.preferred_salary_max:
            salary_score = 1.0
        elif salary_mid < p.preferred_salary_min:
            salary_score = max(0, 1 - (p.preferred_salary_min - salary_mid) / p.preferred_salary_min)
        else:
            salary_score = max(0, 1 - (salary_mid - p.preferred_salary_max) / p.preferred_salary_max)
    else:
        salary_score = 0.5  # unknown salary gets neutral score

    # Tech match score
    job_tech = set(t.lower() for t in job.get("tech_stack", []))
    pref_tech = set(t.lower() for t in p.preferred_tech)
    if pref_tech and job_tech:
        overlap = len(job_tech & pref_tech)
        tech_score = min(1.0, overlap / max(1, len(pref_tech) * 0.5))
    else:
        tech_score = 0.5

    # Remote score
    remote_score = 1.0 if job.get("remote", True) == p.prefer_remote else 0.3

    # Company size score
    job_size = job.get("company_size", "")
    if p.preferred_company_sizes and job_size:
        size_score = 1.0 if job_size in p.preferred_company_sizes else 0.4
    else:
        size_score = 0.5

    # Title match score
    job_title = job.get("title", "").lower()
    if p.preferred_titles:
        title_score = max(
            (1.0 if any(pt.lower() in job_title for pt in p.preferred_titles) else 0.2),
            0.2,
        )
    else:
        title_score = 0.5

    # Source reliability score
    source = job.get("source", "")
    source_score = _SOURCE_DEFAULTS.get(source, 0.5)
    if source in p.source_reliability:
        source_score = p.source_reliability[source]

    # Weighted total
    total = (
        w.salary * salary_score
        + w.tech_match * tech_score
        + w.remote * remote_score
        + w.company_size * size_score
        + w.title_match * title_score
        + w.source_reliability * source_score
    )

    return {
        "score": round(total, 3),
        "breakdown": {
            "salary": round(salary_score, 3),
            "tech_match": round(tech_score, 3),
            "remote": round(remote_score, 3),
            "company_size": round(size_score, 3),
            "title_match": round(title_score, 3),
            "source_reliability": round(source_score, 3),
        },
    }


def rank_jobs(
    jobs: list[dict],
    weights: ScoringWeights | None = None,
    profile: ScoringProfile | None = None,
) -> list[dict]:
    """Score and rank a list of jobs, returning them sorted by score descending."""
    scored = []
    for job in jobs:
        result = score_job(job, weights, profile)
        scored.append({**job, "score": result["score"], "score_breakdown": result["breakdown"]})
    return sorted(scored, key=lambda x: x["score"], reverse=True)
