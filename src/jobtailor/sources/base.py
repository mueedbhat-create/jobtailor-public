"""Source adapter interface for JobTailor."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jobtailor.models import JobLead


class SourceAdapter(ABC):
    """Interface every job source implements.

    Only this class talks to external services. Everything upstream
    works with plain JobLead objects.
    """

    name: str = "base"

    @abstractmethod
    def fetch(self, queries: list[str], companies: list[str], limit: int) -> list[JobLead]:
        """Fetch job leads for the given queries and companies."""
        raise NotImplementedError