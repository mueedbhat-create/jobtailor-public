"""Configuration loading and validation for JobTailor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when the configuration file is invalid."""


@dataclass
class ScheduleConfig:
    times: list[str] = field(default_factory=lambda: ["07:00"])
    jobs_per_run: int = 15


@dataclass
class QueryConfig:
    keyword: str
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResumeConfig:
    source: str = "~/resume"
    format: str = "latex"  # "latex" or "doc"
    compiler: str = "tectonic"


@dataclass
class LLMConfig:
    provider: str = "opencode"  # "opencode" (default) or "openai-compatible"
    model: str = ""  # opencode: model name (empty = default); openai-compatible: required


@dataclass
class ApplyConfig:
    mode: str = "human_in_the_loop"  # or "full_auto" (opt-in)


@dataclass
class ApplicantConfig:
    """Contact details used to fill application forms."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    website: str = ""
    headline: str = ""
    fit_profile: str = ""


@dataclass
class DiscoveryConfig:
    queries: list[QueryConfig] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    sources: dict[str, bool] = field(
        default_factory=lambda: {
            "adzuna": True,
            "wellfound": True,
            "glassdoor": False,
            "foundit": False,
            "simplyhired": False,
            "dailyremote": False,
            "linkedin": True,
            "careers": False,
            "mercor": False,
            "outlier": False,
            "freehire": True,
            "remoteok": True,
            "weworkremotely": True,
            "hn_hiring": True,
        }
    )
    max_per_query: int = 5
    max_per_company: int = 3
    exclude_title_keywords: list[str] = field(default_factory=list)
    skip_engineer_specific: bool = True


@dataclass
class AdzunaConfig:
    app_id: str = ""
    app_key: str = ""
    country: str = "in"


@dataclass
class InternshipConfig:
    enabled: bool = False
    queries: list[str] = field(default_factory=list)
    jobs_per_run: int = 10
    output_base: str = "output/internships"


@dataclass
class GmailConfig:
    enabled: bool = False
    client_secrets_file: str = ""
    token_file: str = ""
    auto_sync: bool = False
    sync_interval_minutes: int = 60


@dataclass
class Config:
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    resume: ResumeConfig = field(default_factory=ResumeConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    apply: ApplyConfig = field(default_factory=ApplyConfig)
    applicant: ApplicantConfig = field(default_factory=ApplicantConfig)
    adzuna: AdzunaConfig = field(default_factory=AdzunaConfig)
    internships: InternshipConfig = field(default_factory=InternshipConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)


def load_config(path: str | Path) -> Config:
    """Load and validate a config.yaml file."""
    p = Path(path).expanduser()
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")

    raw = yaml.safe_load(p.read_text()) or {}
    cfg = Config()

    # Schedule
    sched = raw.get("schedule", {})
    cfg.schedule.times = sched.get("times", ["07:00"])
    cfg.schedule.jobs_per_run = int(sched.get("jobs_per_run", 15))

    # Discovery
    disc = raw.get("discovery", {})
    for q in disc.get("queries", []):
        cfg.discovery.queries.append(
            QueryConfig(keyword=q["keyword"], filters=q.get("filters", {}))
        )
    cfg.discovery.companies = disc.get("companies", [])
    # Merge sources from config file (add new keys, update existing ones)
    for key, val in disc.get("sources", {}).items():
        cfg.discovery.sources[key] = bool(val)
    cfg.discovery.max_per_query = int(disc.get("max_per_query", 5))
    cfg.discovery.max_per_company = int(disc.get("max_per_company", 3))
    cfg.discovery.exclude_title_keywords = [
        str(k).lower() for k in disc.get("exclude_title_keywords", []) if k
    ]
    cfg.discovery.skip_engineer_specific = bool(disc.get("skip_engineer_specific", True))

    # Resume
    res = raw.get("resume", {})
    cfg.resume.source = res.get("source", "~/resume")
    cfg.resume.format = res.get("format", "latex")
    cfg.resume.compiler = res.get("compiler", "tectonic")

    # LLM
    llm = raw.get("llm", {})
    cfg.llm.provider = llm.get("provider", "opencode")
    cfg.llm.model = llm.get("model", "")

    # Apply
    apply = raw.get("apply", {})
    cfg.apply.mode = apply.get("mode", "human_in_the_loop")

    # Applicant (form-fill contact details)
    ap = raw.get("applicant") or {}
    for f in ("full_name", "email", "phone", "location", "linkedin", "website", "headline", "fit_profile"):
        setattr(cfg.applicant, f, str(ap.get(f, "") or ""))

    # Adzuna
    adz = raw.get("adzuna", {})
    cfg.adzuna.app_id = adz.get("app_id", "")
    cfg.adzuna.app_key = adz.get("app_key", "")
    cfg.adzuna.country = adz.get("country", "in")

    # Internships (separate pipeline track)
    intr = raw.get("internships") or {}
    cfg.internships.enabled = bool(intr.get("enabled", False))
    cfg.internships.queries = [str(q) for q in intr.get("queries", []) if q]
    cfg.internships.jobs_per_run = int(intr.get("jobs_per_run", 10))
    cfg.internships.output_base = str(intr.get("output_base", "output/internships"))

    # Gmail
    gm = raw.get("gmail") or {}
    cfg.gmail.enabled = bool(gm.get("enabled", False))
    cfg.gmail.client_secrets_file = str(gm.get("client_secrets_file", "") or "")
    cfg.gmail.token_file = str(gm.get("token_file", "") or "")
    cfg.gmail.auto_sync = bool(gm.get("auto_sync", False))
    cfg.gmail.sync_interval_minutes = int(gm.get("sync_interval_minutes", 60))

    return cfg