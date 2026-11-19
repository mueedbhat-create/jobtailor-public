"""Source adapter registry."""

from __future__ import annotations

from jobtailor.config import Config
from jobtailor.sources.adzuna import AdzunaSource
from jobtailor.sources.base import SourceAdapter
from jobtailor.sources.dailyremote import DailyRemoteSource
from jobtailor.sources.freehire import FreehireSource
from jobtailor.sources.himalayas import HimalayasSource
from jobtailor.sources.hn_hiring import HNWhoIsHiringSource
from jobtailor.sources.internshala import InternshalaSource
from jobtailor.sources.linkedin import LinkedInSource
from jobtailor.sources.simplyhired import SimplyHiredSource
from jobtailor.sources.wellfound import WellfoundSource

# Scrapling-based sources (lazy import — only loaded when used)
_SCRAPELING_SOURCES: dict[str, str] = {
    "remoteok": "jobtailor.sources.scrapling_source:RemoteOKSource",
    "weworkremotely": "jobtailor.sources.scrapling_source:WeWorkRemotelySource",
}

_SOURCES: dict[str, type[SourceAdapter]] = {
    "adzuna": AdzunaSource,
    "wellfound": WellfoundSource,
    "linkedin": LinkedInSource,
    "dailyremote": DailyRemoteSource,
    "simplyhired": SimplyHiredSource,
    "freehire": FreehireSource,
    "hn_hiring": HNWhoIsHiringSource,
    "himalayas": HimalayasSource,
    "internshala": InternshalaSource,
}


def _load_scrapling_source(name: str) -> type[SourceAdapter]:
    """Lazy-load a Scrapling-based source adapter."""
    import importlib

    module_path, class_name = _SCRAPELING_SOURCES[name].rsplit(":", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def build_source(name: str, config: Config) -> SourceAdapter:
    """Instantiate a source adapter by name."""
    if name in _SCRAPELING_SOURCES:
        cls = _load_scrapling_source(name)
        return cls()
    if name not in _SOURCES:
        raise ValueError(f"Unknown source: {name}")
    cls = _SOURCES[name]
    if name == "adzuna":
        return cls(config.adzuna)
    if name == "himalayas":
        # Only jobs open to the candidate's country (or worldwide if unknown).
        country = (config.applicant.location or "").split(",")[-1].strip()
        return cls(country=country)
    return cls()


def enabled_sources(
    config: Config, override: dict[str, bool] | None = None
) -> list[str]:
    """Return source names that are both known and enabled in config.

    `override` (e.g. internships.sources) is merged on top of
    discovery.sources, so a track can add or disable individual sources
    without re-listing the rest.
    """
    sources = dict(config.discovery.sources)
    if override:
        sources.update(override)
    all_known = {**_SOURCES, **_SCRAPELING_SOURCES}
    if not (config.adzuna.app_id and config.adzuna.app_key):
        sources["adzuna"] = False  # needs a free key; skip quietly instead of failing every run
    return [name for name, enabled in sources.items() if enabled and name in all_known]