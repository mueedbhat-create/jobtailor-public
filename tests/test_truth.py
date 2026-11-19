"""Fact-check tests, using the fabrications qwen2.5:7b actually produced on 2026-11-16."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobtailor.truth import violations

REF = r"""
\cvsection{Work Experience}
\begin{cventries}
\cventry
    {Marketing Strategist \& Copywriter}
    {Northwind Paints \& Coatings Ltd.}
    {Pune, India}
    {Feb 2022 - April 2026}
    {
      \begin{cvitems}
        \item{Designed data-driven strategies lifting \textbf{brand visibility by 35\%} and \textbf{engagement by 28\%}.}
        \item{Managed \textbf{end-to-end content production}; leveraged \textbf{AI-assisted tools} for keyword analysis.}
        \item{Produced SEO-optimised blogs and articles.}
        \item{Designed n8n/Zapier/Make automations; LLM workflows with OpenAI API, RAG and prompt engineering.}
      \end{cvitems}
    }
\end{cventries}
"""


def test_original_passes():
    assert violations(REF, REF) == []


def test_rephrasing_with_ordinary_words_passes():
    new = REF.replace("Designed data-driven strategies lifting",
                      "Developed data-driven marketing strategies that increased")
    new = new.replace("SEO-optimised blogs", "SEO-optimized blogs")
    assert violations(new, REF) == []


def test_fake_job_entry_caught():
    new = REF.replace(r"\end{cventries}", r"""
\cventry
    {Performance Marketing Specialist}
    {BrightGrowth}
    {Remote (India)}
    {Jan 2023 - Present}
    {\begin{cvitems}\item{Managed paid campaigns.}\end{cvitems}}
\end{cventries}""")
    v = " ".join(violations(new, REF))
    assert "new entry: BrightGrowth" in v and "2023" in v


@pytest.mark.parametrize("added", ["Salesforce", "HubSpot", "SQL", "PostgreSQL", "Google Ads",
                                   "Meta Ads", "TikTok Ads", "CRM", "Google Analytics", "PyCharm"])
def test_invented_tools_caught(added):
    new = REF.replace("prompt engineering.", f"prompt engineering and {added}.")
    assert violations(new, REF), added


def test_invented_number_caught():
    new = REF.replace("engagement by 28", "engagement by 48")
    assert any("48" in v for v in violations(new, REF))


def test_note_checks():
    from jobtailor.brain import check_note

    bad1 = ("I am excited about the role at BrightGrowth. At BrightGrowth, I drove significant "
            "performance improvements across Google Ads and Meta Ads.")
    bad2 = ("I am drawn to BrightGrowth. At Northwind Paints I lifted brand visibility by 35%. "
            "My background in CRM management will help drive pipeline growth.")
    good = ("I am drawn to the Marketing Manager role at BrightGrowth. At Northwind Paints I lifted "
            "brand visibility by 35% and engagement by 28% through data-driven strategies.")
    for out, ok in ((bad1, False), (bad2, False), (good, True)):
        got = check_note(out, "Marketing Manager", "BrightGrowth", REF)
        assert bool(got) is ok, out


def test_tailor_keeps_original_when_rewrite_invents(tmp_path):
    from jobtailor.models import JobDescription
    from jobtailor.tailor import ResumeTailor

    resume = tmp_path / "resume"
    (resume / "resume").mkdir(parents=True)
    (resume / "resume.tex").write_text("main")
    (resume / "resume" / "experience.tex").write_text(REF)
    (resume / "resume" / "skills.tex").write_text(
        "\\begin{cvskills}\n\\cvskill{Automation}{n8n, Zapier, Make}\n\\end{cvskills}")

    class LLM:
        def generate(self, system, user, workdir="."):
            return ('{"apply":true,"order":["E1.2"],"skills":{"S1":["Zapier","n8n","Make"]},'
                    '"add_skills":{"S1":["Salesforce"]},'
                    '"rewrite":{"E1.1":"Designed data-driven strategies with Salesforce and HubSpot lifting '
                    'brand visibility by 35% and engagement by 28%."}}')

    t = ResumeTailor(resume, llm=LLM(), tailored_dir=tmp_path / "out")
    jd = JobDescription(url="https://j/1", title="AI Automation Specialist", company="Acme",
                        description="build zaps", keywords=[])
    res = t.tailor(jd)
    out = tmp_path / "out" / res.branch / "resume"
    assert "Salesforce" not in (out / "experience.tex").read_text()  # rejected -> original kept
    assert "Salesforce" not in (out / "skills.tex").read_text()
    assert "{Zapier, n8n, Make}" in (out / "skills.tex").read_text()  # truthful reorder kept
    assert any("salesforce" in w.lower() for w in t.rejected[res.branch])
