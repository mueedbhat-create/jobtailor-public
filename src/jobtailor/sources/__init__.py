"""Source adapter registry."""

from __future__ import annotations

from jobtailor.config import Config
from jobtailor.sources.adzuna import AdzunaSource
from jobtailor.sources.base import SourceAdapter
from jobtailor.sources.dailyremote import DailyRemoteSource
from jobtailor.sources.freehire import FreehireSource
from jobtailor.sources.hn_hiring import HNWhoIsHiringSource
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
    return cls()


def enabled_sources(config: Config) -> list[str]:
    """Return source names that are both known and enabled in config."""
    all_known = {**_SOURCES, **_SCRAPELING_SOURCES}
    return [name for name, enabled in config.discovery.sources.items() if enabled and name in all_known]