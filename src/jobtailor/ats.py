"""Known applicant-tracking systems: where the application form actually lives.

Many job links point at a description page; the form is one fixed step away.
Going straight there skips a fragile "find and click Apply" step. Pure URL
rules, no network.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

# Button / link texts that open an application form (compared lower-case,
# curly apostrophes normalised, whitespace collapsed). Shared with the
# browser-side scripts in probe.py and apply.py.
APPLY_TEXT_RE = (
    r"^(apply|apply now|apply here|apply today|apply online|quick apply|easy apply|"
    r"apply for this (job|role|position|opportunity)|apply for (the )?job|apply to (this )?job|"
    r"apply on (the )?company (website|site)|apply on website|apply with (your )?(resume|cv)|"
    r"start (your )?application|begin application|i'?m interested|i am interested|interested|"
    r"submit (your )?(resume|cv)|apply via [a-z ]+)$"
)


def ats_form_url(url: str) -> str:
    """The direct application-form URL for a known ATS job link, else `url`."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host, path = parts.netloc.lower(), parts.path.rstrip("/")

    def with_path(p: str) -> str:
        return urlunsplit((parts.scheme or "https", parts.netloc, p, parts.query, ""))

    # Lever: jobs.lever.co/<company>/<uuid>  ->  .../apply
    if host.endswith("lever.co") and re.fullmatch(r"/[^/]+/[0-9a-f-]{36}", path):
        return with_path(path + "/apply")
    # Ashby: jobs.ashbyhq.com/<company>/<uuid>  ->  .../application
    if host.endswith("ashbyhq.com") and re.fullmatch(r"/[^/]+/[0-9a-f-]{36}", path):
        return with_path(path + "/application")
    # Workable: apply.workable.com/<company>/j/<ID>  ->  .../apply/
    if host == "apply.workable.com" and re.fullmatch(r"/[^/]+/j/[0-9A-F]+", path):
        return with_path(path + "/apply/")
    # Breezy: <company>.breezy.hr/p/<slug>  ->  .../apply
    if host.endswith("breezy.hr") and re.fullmatch(r"/p/[^/]+", path):
        return with_path(path + "/apply")
    # Recruitee: <company>.recruitee.com/o/<slug>  ->  .../c/new
    if host.endswith("recruitee.com") and re.fullmatch(r"/o/[^/]+", path):
        return with_path(path + "/c/new")
    return url
