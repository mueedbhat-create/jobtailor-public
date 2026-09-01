"""Hacker News 'Who's Hiring' job source adapter.

Scrapes the monthly "Ask HN: Who is hiring?" threads via the HN Firebase API.
Each comment is a job posting with company, title, location, and remote status.
Free, structured, no auth needed.
"""

from __future__ import annotations

import re

import httpx

from jobtailor.models import JobLead
from jobtailor.sources.base import SourceAdapter

HN_ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"


class HNWhoIsHiringSource(SourceAdapter):
    """Scrape Hacker News 'Who is hiring?' threads for remote job postings."""

    name = "hn_hiring"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            },
        )

    def fetch(self, queries: list[str], companies: list[str], limit: int) -> list[JobLead]:
        # Find the latest "Who is hiring?" thread
        thread_id = self._find_latest_thread()
        if not thread_id:
            print("[warn] hn_hiring: could not find 'Who is hiring?' thread")
            return []

        # Get all comments from the thread
        comment_ids = self._get_thread_comments(thread_id)
        if not comment_ids:
            return []

        # Parse each comment as a job posting
        leads: list[JobLead] = []
        seen: set[str] = set()

        for cid in comment_ids[:500]:  # limit to first 500 comments
            if len(leads) >= limit:
                break
            comment = self._get_comment(cid)
            if not comment or not comment.get("text"):
                continue

            lead = self._parse_comment(comment, queries)
            if lead and lead.url not in seen:
                seen.add(lead.url)
                leads.append(lead)

        return leads

    def _find_latest_thread(self) -> int | None:
        """Find the most recent 'Who is hiring?' thread via Algolia API."""
        resp = self._client.get(
            HN_ALGOLIA_SEARCH,
            params={
                "query": "Ask HN: Who is hiring?",
                "tags": "story",
                "numericFilters": "created_at_i>1700000000",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # Find the most recent thread with "Who is hiring" in the title
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            if "who is hiring" in title.lower() and "ask hn" in title.lower():
                return hit.get("objectID") and int(hit["objectID"])
        return None

    def _get_thread_comments(self, story_id: int) -> list[int]:
        """Get comment IDs from a HN story."""
        resp = self._client.get(HN_ITEM_URL.format(story_id))
        resp.raise_for_status()
        story = resp.json()
        return story.get("kids", [])

    def _get_comment(self, comment_id: int) -> dict | None:
        """Fetch a single HN comment."""
        try:
            resp = self._client.get(HN_ITEM_URL.format(comment_id))
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def _parse_comment(self, comment: dict, queries: list[str]) -> JobLead | None:
        """Parse a HN comment into a JobLead.

        HN 'Who is hiring?' comments typically follow a format like:
        Company Name | Location | Remote | URL | Description
        """
        html = comment.get("text", "")
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", html).strip()
        if len(text) < 20:
            return None

        # The first line is usually: Company Name | Location | Remote | ...
        first_line = text.split("\n")[0].strip()
        parts = [p.strip() for p in first_line.split("|")]

        company = parts[0] if parts else ""
        title = self._extract_title(text)
        location = self._extract_location(parts)
        remote = self._is_remote(text, parts)

        # Filter by queries
        text_lower = text.lower()
        if queries:
            matched = False
            for q in queries:
                if any(w.lower() in text_lower for w in q.split() if len(w) > 2):
                    matched = True
                    break
            if not matched:
                return None

        url = f"https://news.ycombinator.com/item?id={comment['id']}"

        return JobLead(
            url=url,
            company=company[:80],
            title=title[:120],
            source=self.name,
            remote=remote,
            location=location[:80],
        )

    @staticmethod
    def _extract_title(text: str) -> str:
        """Extract job title from the comment text."""
        # Look for common title patterns
        lines = text.split("\n")
        for line in lines[:5]:
            line = line.strip()
            # Look for lines with role titles
            title_patterns = [
                r"(?:hiring|looking for|seeking)\s+(.+?)(?:\||$)",
                r"(?:role|position):\s*(.+?)(?:\||$)",
                r"(\w+(?:\s+\w+){0,3}\s+(?:engineer|developer|manager|designer|marketer|analyst|specialist|coordinator|lead|director))",
            ]
            for pattern in title_patterns:
                m = re.search(pattern, line, re.I)
                if m:
                    return m.group(1).strip()[:120]

        # Fallback: use company name + "role"
        first_line = lines[0].split("|")[0].strip() if lines else ""
        return f"{first_line} role" if first_line else "Unknown role"

    @staticmethod
    def _extract_location(parts: list[str]) -> str:
        """Extract location from the pipe-separated parts."""
        location_keywords = {
            "remote", "anywhere", "usa", "us", "uk", "europe", "eu",
            "asia", "india", "canada", "australia", "germany", "france",
            "san francisco", "new york", "london", "berlin", "toronto",
        }
        for part in parts[1:]:
            part_lower = part.lower().strip()
            if any(kw in part_lower for kw in location_keywords):
                return part.strip()
        return ""

    @staticmethod
    def _is_remote(text: str, parts: list[str]) -> bool:
        """Check if the job is remote."""
        remote_indicators = ["remote", "anywhere", "worldwide", "distributed"]
        for part in parts:
            if any(ind in part.lower() for ind in remote_indicators):
                return True
        # Also check the full text (first 200 chars)
        header = text[:200].lower()
        return any(ind in header for ind in remote_indicators)
