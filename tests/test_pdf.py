"""Tests for PDF ATS text-layer verification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jobtailor.pdf import PdfVerificationError, PdfVerifier


@pytest.fixture(scope="module")
def tectonic_pdf(tmp_path_factory):
    """Compile a minimal LaTeX doc to PDF with tectonic (or skip)."""
    tectonic = _find_tectonic()
    if tectonic is None:
        pytest.skip("tectonic not available")
    out = tmp_path_factory.mktemp("pdf")
    tex = out / "doc.tex"
    tex.write_text(
        r"""\documentclass{article}
\begin{document}
Mueed Nazir Bhat
mueed.nazir@gmail.com
+91 6006628812
Builds AI automation workflows in n8n.
\end{document}"""
    )
    try:
        subprocess.run([tectonic, "doc.tex"], cwd=str(out), capture_output=True, check=True)
    except subprocess.CalledProcessError:
        pytest.skip("tectonic compile failed")
    pdf = out / "doc.pdf"
    if not pdf.exists():
        pytest.skip("tectonic produced no pdf")
    return pdf


def _find_tectonic() -> str | None:
    cand = Path(sys.executable).parent / "tectonic"
    if cand.exists():
        return str(cand)
    import shutil

    return shutil.which("tectonic")


class TestPdfVerifier:
    def test_verifies_good_pdf(self, tectonic_pdf):
        v = PdfVerifier(required_terms=["mueed.nazir@gmail.com", "+91 6006628812"])
        report = v.verify(tectonic_pdf)
        assert report["ok"] is True
        assert report["pages"] == 1
        assert "Mueed" in report["text"]

    def test_flags_missing_contact_term(self, tectonic_pdf):
        v = PdfVerifier(required_terms=["nonexistent@example.com"])
        report = v.verify(tectonic_pdf)
        assert report["ok"] is False
        assert "nonexistent@example.com" in report["missing"]

    def test_phone_matches_across_formatting(self, tectonic_pdf):
        # The PDF text layer has "6006628812" (no spaces/country code); a
        # required term "+91 6006628812" must still be considered present.
        v = PdfVerifier(required_terms=["+91 6006628812"])
        report = v.verify(tectonic_pdf)
        assert report["ok"] is True
        assert report["missing"] == []

    def test_rejects_missing_file(self):
        v = PdfVerifier()
        with pytest.raises(PdfVerificationError):
            v.verify("/no/such/file.pdf")

    def test_extract_text_roundtrip(self, tectonic_pdf):
        v = PdfVerifier()
        text = v.extract_text(tectonic_pdf)
        assert "Mueed" in text
        assert "n8n" in text