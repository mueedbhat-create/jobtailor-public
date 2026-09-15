"""Tailoring quality review.

Before PDF export, shows a diff of what the LLM changed in the resume
and lets users approve/reject per section.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SectionDiff:
    """Diff for a single resume section."""

    section: str
    original: str
    tailored: str
    changes: list[str] = field(default_factory=list)
    approved: bool = True

    @property
    def change_count(self) -> int:
        return len(self.changes)

    @property
    def change_ratio(self) -> float:
        if not self.original:
            return 1.0
        orig_lines = set(self.original.splitlines())
        tail_lines = set(self.tailored.splitlines())
        added = tail_lines - orig_lines
        removed = orig_lines - tail_lines
        return len(added | removed) / max(1, len(orig_lines))

    def as_dict(self) -> dict:
        return {
            "section": self.section,
            "change_count": self.change_count,
            "change_ratio": round(self.change_ratio, 3),
            "approved": self.approved,
            "changes": self.changes[:10],
        }


@dataclass
class TailoringReview:
    """Review of all section changes for one tailored resume."""

    job_url: str
    company: str
    title: str
    branch: str
    sections: list[SectionDiff] = field(default_factory=list)
    overall_approved: bool = True

    @property
    def total_changes(self) -> int:
        return sum(s.change_count for s in self.sections)

    @property
    def rejected_sections(self) -> list[str]:
        return [s.section for s in self.sections if not s.approved]

    def as_dict(self) -> dict:
        return {
            "job_url": self.job_url,
            "company": self.company,
            "title": self.title,
            "branch": self.branch,
            "total_changes": self.total_changes,
            "overall_approved": self.overall_approved,
            "sections": [s.as_dict() for s in self.sections],
        }


def compute_section_diff(original: str, tailored: str, section: str) -> SectionDiff:
    """Compute the diff between original and tailored section content."""
    orig_lines = original.splitlines(keepends=True)
    tail_lines = tailored.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        orig_lines, tail_lines,
        fromfile=f"original/{section}.tex",
        tofile=f"tailored/{section}.tex",
        lineterm="",
    ))

    changes = [line.strip() for line in diff if line.startswith("+") and not line.startswith("+++")]
    return SectionDiff(
        section=section,
        original=original,
        tailored=tailored,
        changes=changes,
        approved=True,
    )


def review_tailored_resume(
    tailored_dir: str | Path,
    original_dir: str | Path,
    job_url: str = "",
    company: str = "",
    title: str = "",
    branch: str = "",
) -> TailoringReview:
    """Compare original and tailored resume sections, producing a review."""
    sections_to_check = ["experience", "skills", "education"]
    review = TailoringReview(
        job_url=job_url,
        company=company,
        title=title,
        branch=branch,
    )

    for section_name in sections_to_check:
        orig_path = Path(original_dir) / f"{section_name}.tex"
        tail_path = Path(tailored_dir) / f"{section_name}.tex"

        if not tail_path.exists():
            continue

        original = orig_path.read_text(errors="replace") if orig_path.exists() else ""
        tailored = tail_path.read_text(errors="replace")

        if original == tailored:
            continue

        diff = compute_section_diff(original, tailored, section_name)
        review.sections.append(diff)

    return review


def approve_all(review: TailoringReview) -> None:
    """Approve all sections in a review."""
    for s in review.sections:
        s.approved = True
    review.overall_approved = True


def reject_section(review: TailoringReview, section: str) -> None:
    """Reject a specific section."""
    for s in review.sections:
        if s.section == section:
            s.approved = False
    review.overall_approved = all(s.approved for s in review.sections)


def save_review(review: TailoringReview, output_dir: str | Path = "output/reviews") -> Path:
    """Save a review to disk."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{review.branch.replace('/', '_')}.json"
    path.write_text(json.dumps(review.as_dict(), indent=2))
    return path


def load_review(path: str | Path) -> TailoringReview | None:
    """Load a saved review."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    review = TailoringReview(
        job_url=data.get("job_url", ""),
        company=data.get("company", ""),
        title=data.get("title", ""),
        branch=data.get("branch", ""),
        overall_approved=data.get("overall_approved", True),
    )
    for s in data.get("sections", []):
        review.sections.append(
            SectionDiff(
                section=s.get("section", ""),
                original=s.get("original", ""),
                tailored=s.get("tailored", ""),
                changes=s.get("changes", []),
                approved=s.get("approved", True),
            )
        )
    return review
