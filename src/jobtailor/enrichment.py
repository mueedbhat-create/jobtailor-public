"""Company research enrichment.

Enriches job leads with company metadata: size, tech stack,
Glassdoor rating, and industry classification.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import URLError


@dataclass
class CompanyInfo:
    """Enriched company metadata."""

    name: str
    size: str = ""  # "1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"
    industry: str = ""
    tech_stack: list[str] = field(default_factory=list)
    glassdoor_rating: float | None = None
    linkedin_url: str = ""
    website: str = ""
    founded: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "industry": self.industry,
            "tech_stack": self.tech_stack,
            "glassdoor_rating": self.glassdoor_rating,
            "linkedin_url": self.linkedin_url,
            "website": self.website,
            "founded": self.founded,
        }


# Simple keyword-based industry detection from JD text
_INDUSTRY_KEYWORDS = {
    "fintech": ["fintech", "banking", "payment", "financial", "insurance", "lending"],
    "healthtech": ["health", "medical", "clinical", "patient", "healthcare"],
    "edtech": ["education", "learning", "student", "school", "university"],
    "ecommerce": ["e-commerce", "ecommerce", "shopify", "store", "retail"],
    "saas": ["saas", "software as a service", "cloud", "platform"],
    "ai/ml": ["ai", "machine learning", "deep learning", "nlp", "llm", "gpt"],
    "marketing": ["marketing", "advertising", "seo", "sem", "growth"],
    "gaming": ["game", "gaming", "unity", "unreal", "esports"],
    "crypto": ["crypto", "blockchain", "web3", "defi", "nft"],
}

_TECH_KEYWORDS = [
    "python", "javascript", "typescript", "react", "vue", "angular", "node",
    "go", "rust", "java", "kotlin", "swift", "ruby", "php", "c++", "c#",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "n8n", "zapier", "make", "airtable", "notion",
    "openai", "langchain", "llamaindex", "huggingface",
    "figma", "sketch", "adobe",
    "salesforce", "hubspot", "stripe", "twilio",
]


def detect_industry(text: str) -> str:
    """Detect the most likely industry from JD text."""
    lowered = text.lower()
    best_match = "technology"
    best_count = 0
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in lowered)
        if count > best_count:
            best_count = count
            best_match = industry
    return best_match


def detect_tech_stack(text: str) -> list[str]:
    """Extract mentioned technologies from JD text."""
    lowered = text.lower()
    found = []
    for tech in _TECH_KEYWORDS:
        if tech in lowered and tech not in found:
            found.append(tech)
    return found


def enrich_from_jd(company_name: str, jd_text: str) -> CompanyInfo:
    """Create a CompanyInfo from available JD text (no API calls)."""
    return CompanyInfo(
        name=company_name,
        industry=detect_industry(jd_text),
        tech_stack=detect_tech_stack(jd_text),
    )


class CompanyEnricher:
    """Enrich job leads with company data. Uses local heuristics by default,
    can optionally call external APIs."""

    def __init__(self, cache_file: str | None = None):
        self._cache: dict[str, CompanyInfo] = {}
        self._cache_file = cache_file
        if cache_file:
            self._load_cache()

    def _load_cache(self) -> None:
        if not self._cache_file:
            return
        path = __import__("pathlib").Path(self._cache_file)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for name, info in data.items():
            self._cache[name] = CompanyInfo(**info)

    def _save_cache(self) -> None:
        if not self._cache_file:
            return
        path = __import__("pathlib").Path(self._cache_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: info.as_dict() for name, info in self._cache.items()}
        path.write_text(json.dumps(data, indent=2))

    def get_company(self, name: str, jd_text: str = "") -> CompanyInfo:
        """Get company info, using cache or generating from JD text."""
        if name in self._cache:
            return self._cache[name]
        info = enrich_from_jd(name, jd_text) if jd_text else CompanyInfo(name=name)
        self._cache[name] = info
        self._save_cache()
        return info

    def enrich_lead(self, lead_dict: dict, jd_text: str = "") -> dict:
        """Add company enrichment data to a lead dictionary."""
        company = lead_dict.get("company", "")
        if not company:
            return lead_dict
        info = self.get_company(company, jd_text)
        lead_dict["company_info"] = info.as_dict()
        return lead_dict
