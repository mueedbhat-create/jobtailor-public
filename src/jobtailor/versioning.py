"""Resume versioning and A-B testing.

Manages multiple resume base versions, tracks which version was used
per application, and provides analytics on which versions perform best.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class ResumeVersion:
    """A named resume variant."""

    name: str
    path: str  # path to resume directory
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class VersionUsage:
    """Tracks where a version was used and the outcome."""

    version: str
    job_url: str
    company: str
    applied_at: str
    status: str = "applied"  # applied, confirmed, rejected, interview, offer


class ResumeVersionManager:
    """Manages multiple resume versions and tracks their performance."""

    def __init__(self, versions_file: str | Path = "output/versions.json"):
        self._path = Path(versions_file)
        self._versions: list[ResumeVersion] = []
        self._usage: list[VersionUsage] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for v in data.get("versions", []):
            self._versions.append(
                ResumeVersion(
                    name=v["name"],
                    path=v["path"],
                    description=v.get("description", ""),
                    tags=v.get("tags", []),
                )
            )
        for u in data.get("usage", []):
            self._usage.append(
                VersionUsage(
                    version=u["version"],
                    job_url=u["job_url"],
                    company=u.get("company", ""),
                    applied_at=u.get("applied_at", ""),
                    status=u.get("status", "applied"),
                )
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "versions": [
                {
                    "name": v.name,
                    "path": v.path,
                    "description": v.description,
                    "tags": v.tags,
                }
                for v in self._versions
            ],
            "usage": [
                {
                    "version": u.version,
                    "job_url": u.job_url,
                    "company": u.company,
                    "applied_at": u.applied_at,
                    "status": u.status,
                }
                for u in self._usage
            ],
        }
        self._path.write_text(json.dumps(data, indent=2))

    def add_version(self, name: str, path: str, description: str = "", tags: list[str] | None = None) -> ResumeVersion:
        """Register a new resume version."""
        v = ResumeVersion(name=name, path=path, description=description, tags=tags or [])
        self._versions.append(v)
        self._save()
        return v

    def remove_version(self, name: str) -> bool:
        before = len(self._versions)
        self._versions = [v for v in self._versions if v.name != name]
        if len(self._versions) < before:
            self._save()
            return True
        return False

    def list_versions(self) -> list[ResumeVersion]:
        return list(self._versions)

    def get_version(self, name: str) -> ResumeVersion | None:
        for v in self._versions:
            if v.name == name:
                return v
        return None

    def record_usage(self, version: str, job_url: str, company: str = "", status: str = "applied") -> None:
        """Record that a version was used for a specific job."""
        self._usage.append(
            VersionUsage(
                version=version,
                job_url=job_url,
                company=company,
                applied_at=date.today().isoformat(),
                status=status,
            )
        )
        self._save()

    def update_status(self, job_url: str, status: str) -> bool:
        """Update the status for a usage record."""
        found = False
        for u in self._usage:
            if u.job_url == job_url:
                u.status = status
                found = True
        if found:
            self._save()
        return found

    def analytics(self) -> dict[str, dict]:
        """Return performance analytics per version."""
        stats: dict[str, dict] = {}
        for v in self._versions:
            usages = [u for u in self._usage if u.version == v.name]
            total = len(usages)
            statuses = {}
            for u in usages:
                statuses[u.status] = statuses.get(u.status, 0) + 1
            interviews = statuses.get("interview", 0) + statuses.get("offer", 0)
            response_rate = interviews / total if total > 0 else 0.0
            stats[v.name] = {
                "total_applied": total,
                "statuses": statuses,
                "interviews": interviews,
                "response_rate": round(response_rate, 3),
            }
        return stats

    def best_version(self) -> str | None:
        """Return the version name with the highest response rate (min 3 applications)."""
        stats = self.analytics()
        best_name = None
        best_rate = -1.0
        for name, s in stats.items():
            if s["total_applied"] >= 3 and s["response_rate"] > best_rate:
                best_rate = s["response_rate"]
                best_name = name
        return best_name

    def recommend_for_job(self, job_keywords: list[str]) -> ResumeVersion | None:
        """Pick the best version based on tag overlap with job keywords.

        Falls back to best_version() if no tag match is found.
        """
        if not self._versions:
            return None

        job_kw_lower = {k.lower() for k in job_keywords}
        best_version = None
        best_overlap = -1
        for v in self._versions:
            v_tags = {t.lower() for t in v.tags}
            overlap = len(job_kw_lower & v_tags)
            if overlap > best_overlap:
                best_overlap = overlap
                best_version = v

        if best_overlap > 0 and best_version:
            return best_version
        # fallback to performance-based pick
        fallback_name = self.best_version()
        if fallback_name:
            return self.get_version(fallback_name)
        return self._versions[0] if self._versions else None
