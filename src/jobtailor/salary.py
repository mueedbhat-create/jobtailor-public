"""Salary range extraction from job descriptions.

Parses common salary patterns from JD text and provides filtering
capabilities for the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SalaryRange:
    """Extracted salary information."""

    min_amount: float | None = None
    max_amount: float | None = None
    currency: str = "USD"
    period: str = "yearly"  # yearly, monthly, hourly
    raw_text: str = ""

    @property
    def midpoint(self) -> float | None:
        if self.min_amount is not None and self.max_amount is not None:
            return (self.min_amount + self.max_amount) / 2
        return self.min_amount or self.max_amount

    def within_range(self, low: float, high: float) -> bool:
        """Check if this salary overlaps with the given range."""
        mid = self.midpoint
        if mid is None:
            return True  # unknown salary passes filter
        return low <= mid <= high

    def as_dict(self) -> dict:
        return {
            "min": self.min_amount,
            "max": self.max_amount,
            "currency": self.currency,
            "period": self.period,
            "raw": self.raw_text,
        }


_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY"}
_PERIOD_KEYWORDS = {
    "per year": "yearly",
    "per annum": "yearly",
    "p.a.": "yearly",
    "annual": "yearly",
    "yearly": "yearly",
    "/year": "yearly",
    "/yr": "yearly",
    "per month": "monthly",
    "monthly": "monthly",
    "/month": "monthly",
    "/mo": "monthly",
    "per hour": "hourly",
    "hourly": "hourly",
    "/hour": "hourly",
    "/hr": "hourly",
}

# Matches: $100k, $100K, $100,000, $100,000 - $150,000, $100k-$150k
_SALARY_PATTERN = re.compile(
    r"(?P<currency>[\$€£₹¥])?\s*"
    r"(?P<amount1>[\d,]+(?:\.\d+)?)\s*"
    r"(?P<suffix1>[kK])?"
    r"(?:\s*[-–—to]+\s*"
    r"(?P<currency2>[\$€£₹¥])?\s*"
    r"(?P<amount2>[\d,]+(?:\.\d+)?)\s*"
    r"(?P<suffix2>[kK])?)?"
    r"(?:\s*(?:per|a|/)\s*(?P<period>year|month|hour|annum|yearly|monthly|hourly|p\.a\.))?",
    re.IGNORECASE,
)


def _parse_amount(amount_str: str, suffix: str | None) -> float:
    """Parse a number string with optional K suffix."""
    clean = amount_str.replace(",", "")
    try:
        val = float(clean)
    except ValueError:
        return 0.0
    if suffix and suffix.lower() == "k":
        val *= 1000
    return val


def extract_salary(text: str) -> SalaryRange | None:
    """Extract salary range from job description text.

    Returns SalaryRange if found, None otherwise.
    """
    if not text:
        return None

    # Find the first salary-like match
    match = _SALARY_PATTERN.search(text)
    if not match:
        return None

    raw = match.group(0)
    currency_sym = match.group("currency") or match.group("currency2") or "$"
    currency = _CURRENCY_SYMBOLS.get(currency_sym, "USD")

    amount1 = _parse_amount(match.group("amount1"), match.group("suffix1"))
    amount2_str = match.group("amount2")
    amount2 = (
        _parse_amount(amount2_str, match.group("suffix2")) if amount2_str else None
    )

    if amount1 == 0:
        return None

    # Determine period
    period_text = match.group("period") or ""
    period = "yearly"
    for kw, p in _PERIOD_KEYWORDS.items():
        if kw in period_text.lower():
            period = p
            break

    min_amt = min(amount1, amount2) if amount2 else amount1
    max_amt = max(amount1, amount2) if amount2 else amount1

    return SalaryRange(
        min_amount=min_amt,
        max_amount=max_amt,
        currency=currency,
        period=period,
        raw_text=raw.strip(),
    )
