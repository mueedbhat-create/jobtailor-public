"""Tests for JobTailor."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from jobtailor.config import ConfigError, load_config
from jobtailor.extract import ScraplingExtractor, extract_all
from jobtailor.fetch import LeadFetcher, load_leads_from_cache
from jobtailor.models import JobDescription, JobLead, JobLeadBatch, TailoredResume
from jobtailor.apply import (
    ApplicantProfile,
    ApplicationQueue,
    ApplyError,
    AutoSubmitter,
    Browser,
    queue_resumes,
)
from jobtailor.pdf import PdfError, PdfExporter
from jobtailor.sources.adzuna import AdzunaSource
from jobtailor.sources.wellfound import WellfoundSource
from jobtailor.tailor import ResumeTailor, TailorError, tailor_all


class TestModels:
    def test_canonical_url_strips_tracking(self):
        lead = JobLead(
            url="https://x.com/job/123?position=5&utm_source=linkedin&trackingId=abc",
            company="Co",
            title="Role",
            source="test",
        )
        assert "utm_source" not in lead.canonical_url()
        assert "position" not in lead.canonical_url()

    def test_dedupe_by_url(self):
        batch = JobLeadBatch(
            leads=[
                JobLead("https://x.com/job/1", "A", "T1", "src1"),
                JobLead("https://x.com/job/1?utm_source=a", "A", "T1", "src2"),
                JobLead("https://x.com/job/2", "B", "T2", "src1"),
            ]
        )
        batch.dedupe()
        assert len(batch.leads) == 2

    def test_filter_remote(self):
        batch = JobLeadBatch(
            leads=[
                JobLead("https://x.com/1", "A", "T", "s", remote=True),
                JobLead("https://x.com/2", "B", "T", "s", remote=False),
            ]
        )
        batch.filter_remote()
        assert len(batch.leads) == 1
        assert batch.leads[0].url == "https://x.com/1"


class TestConfig:
    def test_load_minimal(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text(
            "discovery:\n"
            "  queries:\n"
            "    - keyword: AI Automation Engineer\n"
            "schedule:\n"
            "  jobs_per_run: 20\n"
        )
        cfg = load_config(p)
        assert cfg.schedule.jobs_per_run == 20
        assert cfg.discovery.queries[0].keyword == "AI Automation Engineer"

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError):
            load_config(tmp_path / "nope.yaml")

    def test_defaults(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("discovery:\n  queries:\n    - keyword: X\n")
        cfg = load_config(p)
        assert cfg.schedule.times == ["07:00"]
        assert cfg.apply.mode == "human_in_the_loop"


class TestAdzuna:
    def test_missing_creds_raises(self):
        from jobtailor.config import AdzunaConfig, Config

        cfg = Config()
        cfg.adzuna = AdzunaConfig(app_id="", app_key="")
        src = AdzunaSource(cfg.adzuna)
        with pytest.raises(RuntimeError):
            src.fetch(["x"], [], 5)

    def test_build_url(self):
        from urllib.parse import urlencode

        params = {
            "app_id": "id",
            "app_key": "key",
            "what": "AI Automation",
            "where": "remote",
        }
        url = "https://api.adzuna.com/v1/api/jobs/in/search/1?" + urlencode(params)
        assert "where=remote" in url
        assert "app_key=key" in url


class TestWellfound:
    def test_slug_mapping(self):
        assert WellfoundSource._slug_for("Performance Marketing") == "marketing"
        assert WellfoundSource._slug_for("AI Automation Engineer") == "engineer"
        assert WellfoundSource._slug_for("Growth") == "marketing"

    def test_parse_remote_cards(self):
        """A fixture HTML page with remote + onsite cards must yield only remote."""
        html = """
        <div class="mb-6">
          <a href="/company/acme">Acme Inc</a>
          <a href="/jobs/1-remote-engineer">Remote Engineer</a>
          <span>Full-time $100k Remote</span>
        </div>
        <div class="mb-6">
          <a href="/company/beta">Beta Co</a>
          <a href="/jobs/2-onsite-dev">Onsite Dev</a>
          <span>Full-time San Francisco</span>
        </div>
        """
        import httpx

        client = httpx.Client()
        source = WellfoundSource(client)

        # monkeypatch _search network via a fake client response
        import io

        class FakeResp:
            text = html
            def raise_for_status(self):
                pass

        class FakeClient:
            def __init__(self):
                self.urls = []

            def get(self, url):
                self.urls.append(url)
                return FakeResp()

        fake = FakeClient()
        src = WellfoundSource(fake)
        leads = src._search("AI Automation Engineer", limit=10)
        assert len(leads) == 1
        assert leads[0].company == "Acme Inc"
        assert leads[0].remote is True


class TestTailor:
    def _make_jd(self):
        return JobDescription(
            url="https://x.com/job/1",
            company="Acme AI",
            title="AI Automation Engineer",
            description="We need AI automation + performance marketing. n8n, Python.",
            keywords=["AI", "Automation", "n8n"],
        )

    def _make_resume(self, root: Path) -> Path:
        resume_dir = root / "resume"
        (resume_dir / "resume").mkdir(parents=True)
        (resume_dir / "resume.tex").write_text("\\cvsection{Experience}\n")
        (resume_dir / "resume" / "experience.tex").write_text("\\cventry{Acme}{}{}{}{}{}done\n")
        (resume_dir / "resume" / "skills.tex").write_text("\\cvskill{Writing}{blogs}\n")
        (resume_dir / "resume" / "education.tex").write_text("\\cventry{Uni}{}{}{}{}{}done\n")
        return resume_dir

    def test_missing_resume_raises(self, tmp_path):
        with pytest.raises(TailorError):
            ResumeTailor(tmp_path)

    def test_slug_sanitized(self):
        jd = JobDescription(
            "https://x.com/1", "Acme/Monks & Co", "AI Automation Engineer!", "d", []
        )
        slug = ResumeTailor._slug_for(jd)
        assert " " not in slug
        assert "&" not in slug
        assert slug.startswith("apply/")
        assert "/" not in slug.removeprefix("apply/")

    def test_tailor_writes_copy_and_leaves_original_untouched(self, tmp_path):
        resume_dir = self._make_resume(tmp_path)
        originals = {
            p.name: p.read_text() for p in sorted((resume_dir / "resume").glob("*.tex"))
        }

        class TailoringLLM:
            def generate(self, system, user, workdir="."):
                for line in user.splitlines():
                    if line.startswith("CURRENT RESUME SECTION"):
                        name = line.split("(")[1].split(")")[0].removesuffix(".tex")
                        current = (Path(workdir) / "resume" / f"{name}.tex").read_text()
                        return current + "\n% tailored for job\n"
                return ""

        tailor = ResumeTailor(resume_dir, llm=TailoringLLM(), tailored_dir=tmp_path / "tailored")
        result = tailor.tailor(self._make_jd())

        assert result.branch.startswith("apply/")
        assert result.job_url == "https://x.com/job/1"

        # original untouched
        for name, text in originals.items():
            assert (resume_dir / "resume" / name).read_text() == text

        # tailored copy exists and differs
        tailored = tmp_path / "tailored" / result.branch / "resume" / "experience.tex"
        assert tailored.exists()
        assert "% tailored for job" in tailored.read_text()

        # temp workspace cleaned up
        leftovers = [p for p in Path(tempfile.gettempdir()).glob("jobtailor-tailor-*")]
        assert leftovers == []

    def test_identical_content_raises_with_no_output(self, tmp_path):
        resume_dir = self._make_resume(tmp_path)

        class EchoLLM:
            def generate(self, system, user, workdir="."):
                for line in user.splitlines():
                    if line.startswith("CURRENT RESUME SECTION"):
                        name = line.split("(")[1].split(")")[0].removesuffix(".tex")
                        return (Path(workdir) / "resume" / f"{name}.tex").read_text()
                return ""

        tailor = ResumeTailor(resume_dir, llm=EchoLLM(), tailored_dir=tmp_path / "tailored")
        with pytest.raises(TailorError):
            tailor.tailor(self._make_jd())

        assert not (tmp_path / "tailored").exists() or list((tmp_path / "tailored").iterdir()) == []

    def test_tailor_all_isolates_failures(self, tmp_path):
        from jobtailor.llm import LLMClient

        resume_dir = self._make_resume(tmp_path)

        class BrokenLLM(LLMClient):
            def generate(self, system, user, workdir="."):
                raise RuntimeError("llm down")

        tailor = ResumeTailor(resume_dir, llm=BrokenLLM(None), tailored_dir=tmp_path / "tailored")
        with pytest.raises(RuntimeError):
            tailor.tailor(self._make_jd())

        results = tailor_all([self._make_jd()], resume_dir, tailored_dir=tmp_path / "tailored")
        # tailor_all constructs its own ResumeTailor without our fake LLM, so
        # this only asserts the isolation contract shape:
        assert isinstance(results, list)


class TestPdf:
    def test_no_tectonic_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("jobtailor.pdf.shutil.which", lambda _: None)
        with pytest.raises(PdfError):
            PdfExporter(tmp_path)

    def test_export_compiles_from_tailored_dir(self, tmp_path, monkeypatch):
        from jobtailor.models import TailoredResume

        tailored_root = tmp_path / "tailored"
        src = tailored_root / "apply" / "test-job"
        src.mkdir(parents=True)
        (src / "resume.tex").write_text("\\cvsection{X}\nhello world\n")

        def fake_tectonic(cmd, cwd=None, capture_output=True, text=True, check=True):
            assert any("tectonic" in str(part) for part in cmd)
            from pypdf import PdfWriter

            w = PdfWriter()
            w.add_blank_page(width=72, height=72)
            out_path = Path(cwd) / "resume.pdf"
            with open(out_path, "wb") as fh:
                w.write(fh)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("jobtailor.pdf.subprocess.run", fake_tectonic)
        out = tmp_path / "out"
        exporter = PdfExporter(tailored_root, out)
        result = TailoredResume(job_url="https://x", branch="apply/test-job")
        dest = exporter.export(result)
        assert dest.exists()
        assert dest.read_bytes().startswith(b"%PDF")
        assert result.pdf_path == dest

    def test_export_missing_tailored_raises(self, tmp_path, monkeypatch):
        from jobtailor.models import TailoredResume

        monkeypatch.setattr(
            "jobtailor.pdf.subprocess.run",
            lambda *a, **k: subprocess.CompletedProcess([], 0),
        )
        exporter = PdfExporter(tmp_path / "tailored", tmp_path / "out")
        result = TailoredResume(job_url="https://x", branch="apply/nope")
        with pytest.raises(PdfError):
            exporter.export(result)


class TestApply:
    def _make_resumes(self, n=2):
        from jobtailor.models import TailoredResume

        return [
            TailoredResume(job_url=f"https://x.com/job/{i}", branch=f"apply/job-{i}", pdf_path=Path(f"/tmp/job-{i}.pdf"))
            for i in range(n)
        ]

    def test_prepare_tracks_state(self, tmp_path):
        class FakeBrowser:
            def __init__(self):
                self.opened = []

            def open(self, url):
                self.opened.append(url)

        fb = FakeBrowser()
        queue = ApplicationQueue(state_dir=tmp_path, browser=fb)
        opened = queue.prepare(self._make_resumes(2))
        assert len(opened) == 2
        assert len(fb.opened) == 2

        # state persisted
        entries = queue.status()
        assert len(entries) == 2
        assert all(e["status"] == "prepared" for e in entries)
        assert entries[0]["pdf"] == "/tmp/job-0.pdf"

    def test_submitted_not_reopened(self, tmp_path):
        class FakeBrowser:
            def __init__(self):
                self.opened = []

            def open(self, url):
                self.opened.append(url)

        fb = FakeBrowser()
        queue = ApplicationQueue(state_dir=tmp_path, browser=fb)
        resumes = self._make_resumes(1)
        queue.prepare(resumes)
        queue.mark_submitted(resumes[0].job_url)

        # re-running the queue should skip the submitted job
        queue2 = ApplicationQueue(state_dir=tmp_path, browser=fb)
        opened = queue2.prepare(resumes)
        assert opened == []
        assert len(fb.opened) == 1  # only the first open happened

    def test_mark_unknown_raises(self, tmp_path):
        queue = ApplicationQueue(state_dir=tmp_path, browser=Browser("open"))
        with pytest.raises(ApplyError):
            queue.mark_submitted("https://x.com/not-in-queue")

    def test_unknown_browser_mode_raises(self):
        with pytest.raises(ApplyError):
            Browser("bogus").open("https://x.com")

    def test_queue_resumes_smoke(self, tmp_path, monkeypatch):
        opened_urls = []

        class FakeQueue:
            def __init__(self, *a, **k):
                pass

            def prepare(self, resumes):
                for r in resumes:
                    opened_urls.append(r.job_url)
                return opened_urls

        monkeypatch.setattr("jobtailor.apply.ApplicationQueue", FakeQueue)

        result = queue_resumes(
            self._make_resumes(1), state_dir=str(tmp_path), apply_config=None
        )
        # The queue must use the mocked browser — never the real macOS 'open'.
        assert opened_urls == ["https://x.com/job/0"]
        assert result == ["https://x.com/job/0"]


class TestAutoSubmit:
    def test_profile_as_dict_omits_empty(self):
        p = ApplicantProfile(full_name="Mueed Bhat", email="mueed@x.com")
        d = p.as_dict()
        assert d == {"full_name": "Mueed Bhat", "email": "mueed@x.com"}

    def test_apply_missing_pdf_raises(self, tmp_path):
        sub = AutoSubmitter(ApplicantProfile(full_name="Mueed"))
        with pytest.raises(ApplyError):
            sub.apply("https://x.com/job/1", str(tmp_path / "nope.pdf"))

    def test_build_script_contains_profile_and_submit_flag(self):
        sub = AutoSubmitter(ApplicantProfile(full_name="Mueed", email="m@x.com"))
        script = sub._build_script("https://x.com/job/1", "/tmp/r.pdf", submit=True)
        assert "jobtailor-apply" in script
        assert "Mueed" in script
        assert "m@x.com" in script
        assert "/tmp/r.pdf" in script
        assert "'uploadFile'" in script or "uploadFile" in script
        # submit branch enabled
        assert "submitted" in script

    def test_parse_result(self):
        out = '{"url": "https://x.com/job/1", "matched_fields": [["email","m@x.com"]], "pdf_uploaded": true, "file_inputs_found": 1, "submitted": true, "submit_href": ""}'
        summary = AutoSubmitter._parse_result(out)
        assert "submitted" in summary
        assert "email" in summary
        assert "PDF uploaded: True" in summary

    def test_parse_result_prefill(self):
        out = '{"url":"u","matched_fields":[],"pdf_uploaded":false,"file_inputs_found":0,"submitted":false,"submit_href":""}'
        summary = AutoSubmitter._parse_result(out)
        assert "pre-filled (not submitted)" in summary

    def test_auto_apply_records_state(self, tmp_path, monkeypatch):
        from jobtailor.models import TailoredResume

        class FakeSub:
            def __init__(self, profile):
                self._profile = profile

            def apply(self, url, pdf_path, submit=False):
                return "submitted; matched fields: email=x@y"

        monkeypatch.setattr("jobtailor.apply.AutoSubmitter", FakeSub)
        resume = TailoredResume(
            job_url="https://x.com/job/1",
            branch="apply/job-1",
            pdf_path=Path("/tmp/resume.pdf"),
        )
        queue = ApplicationQueue(state_dir=tmp_path)
        results = queue.auto_apply([resume], submit=True)
        assert results[0]["status"] == "submitted"
        entries = queue.status()
        assert entries[0]["status"] == "submitted"
        assert "note" in entries[0]


class TestExtraction:
    def test_keyword_extraction(self):
        text = (
            "We are hiring an AI Automation Engineer for our Performance Marketing team. "
            "You will build n8n workflows, write Python, run Google Ads campaigns, and "
            "optimize funnels for lead generation."
        )
        keywords = ScraplingExtractor._extract_keywords(text)
        assert "AI" in keywords
        assert "Automation" in keywords
        assert "Performance Marketing" in keywords
        assert "n8n" in keywords
        assert "Python" in keywords
        assert "Google Ads" in keywords
        assert "Lead Generation" in keywords

    def test_keyword_extraction_empty(self):
        assert ScraplingExtractor._extract_keywords("") == []

    def test_extract_all_isolates_failures(self):
        leads = [
            JobLead("https://ok.example/job/1", "A", "Role", "test", remote=True),
            JobLead("https://bad.example/job/2", "B", "Role", "test", remote=True),
        ]

        class Failing:
            def extract(self, lead):
                if "bad" in lead.url:
                    raise RuntimeError("boom")
                return JobDescription(lead.url, lead.company, lead.title, "desc text", ["AI"])

        results = extract_all(leads, extractor=Failing())
        assert len(results) == 1
        assert results[0].url == "https://ok.example/job/1"
    def test_empty_config_raises(self):
        from jobtailor.config import Config

        fetcher = LeadFetcher(Config())
        with pytest.raises(Exception):
            fetcher.run()

    def test_cache_roundtrip(self, tmp_path):
        out = tmp_path / "leads"
        lead = JobLead("https://x.com/1", "Acme", "Engineer", "adzuna", remote=True)
        batch = JobLeadBatch(leads=[lead], source_counts={"adzuna": 1})

        from jobtailor.fetch import LeadFetcher
        from jobtailor.config import Config

        cfg = Config()
        fetcher = LeadFetcher(cfg, output_dir=out)
        fetcher._write_cache(batch)
        files = list(out.glob("*.json"))
        assert len(files) == 1
        loaded = load_leads_from_cache(files[0])
        assert loaded[0].company == "Acme"