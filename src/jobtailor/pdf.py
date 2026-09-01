"""Stage 4: compile tailored resumes to PDF with Tectonic.

Each tailored resume lives in output/tailored/<slug>/ (a full LaTeX
directory produced by stage 3). Compile it in place and copy the
resulting PDF to output/resumes/<slug>.pdf.

After compiling, each PDF is verified the way an ATS parser sees it:
the embedded text layer is extracted (pypdf, no system deps) and checked
for contact details as literal text, a sane page count, and that the text
didn't collapse into garbage. This catches LaTeX PDFs that "look fine in
the .tex" but extract as gibberish to applicant tracking systems.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from jobtailor.models import TailoredResume


class PdfError(Exception):
    """Raised when PDF compilation fails."""


class PdfVerificationError(Exception):
    """Raised when a compiled PDF fails the ATS text-layer check."""


class PdfVerifier:
    """Verify a compiled PDF the way an ATS parser reads it.

    Extracts the PDF's embedded text layer and checks that contact details
    survive as literal, searchable text with a sane page count and a
    readable text density. Uses pypdf (pure Python, no system deps) so it
    runs anywhere tectonic does.
    """

    def __init__(self, required_terms: list[str] | None = None, max_pages: int = 4):
        self._required = required_terms or []
        self._max_pages = max_pages

    def extract_text(self, pdf: str | Path) -> str:
        """Return the PDF's text layer, or raise PdfVerificationError."""
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency always installed
            raise PdfVerificationError(f"pypdf not installed: {exc}") from exc
        try:
            reader = PdfReader(str(pdf))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001 - any pypdf failure is a verification fail
            raise PdfVerificationError(f"could not read PDF text layer: {exc}") from exc

    def verify(self, pdf: str | Path) -> dict:
        """Run the checks; returns a report dict, raising on hard failures.

        Returns: {"text": str, "pages": int, "missing": [terms], "ok": bool}
        """
        from pypdf import PdfReader

        try:
            reader = PdfReader(str(pdf))
        except Exception as exc:  # noqa: BLE001
            raise PdfVerificationError(f"could not open PDF: {exc}") from exc
        pages = len(reader.pages)
        if pages < 1 or pages > self._max_pages:
            raise PdfVerificationError(f"unexpected page count: {pages}")

        text = self.extract_text(pdf)
        normalized = " ".join(text.split()).lower()
        if self._required:
            if not text.strip():
                raise PdfVerificationError("PDF text layer is empty — ATS will see nothing")
            if len(normalized) < 20:
                raise PdfVerificationError("PDF text layer too sparse to be ATS-parseable")

        missing = [t for t in self._required if not self._present(t, normalized)]
        return {"text": text, "pages": pages, "missing": missing, "ok": not missing}

    @staticmethod
    def _present(term: str, normalized_text: str) -> bool:
        """Check a required term is extractable, normalizing phone numbers.

        A phone written as "+91 60066 28812" on the resume should match a
        required term "+91 6006628812" even though spacing differs. So for
        phone-like terms we compare by digits only.
        """
        term = term.lower()
        if term in normalized_text:
            return True
        digits = "".join(ch for ch in term if ch.isdigit())
        if len(digits) >= 10:
            text_digits = "".join(ch for ch in normalized_text if ch.isdigit())
            return digits in text_digits
        return False


def _resolve_tectonic() -> str:
    """Find tectonic, tolerating LaunchAgent's minimal PATH."""
    candidates = [Path(sys.executable).parent / "tectonic"]
    for cand in candidates:
        if cand.exists():
            return str(cand)
    found = shutil.which("tectonic")
    if found:
        return found
    raise PdfError("tectonic not found on PATH. Install it: brew install tectonic")


class PdfExporter:
    def __init__(
        self,
        tailored_dir: str | Path = "output/tailored",
        output_dir: str | Path = "output/resumes",
        verifier: PdfVerifier | None = None,
    ):
        self._tailored_dir = Path(tailored_dir)
        self._output_dir = Path(output_dir)
        self._tectonic = _resolve_tectonic()
        self._verifier = verifier or PdfVerifier()

    def export(self, result: TailoredResume) -> Path:
        """Compile the tailored resume for `result.branch` into a PDF.

        After compiling, the PDF is ATS-verified (text layer + page count).
        Verification problems raise PdfVerificationError so a broken PDF is
        never silently handed to an applicant.
        """
        src = self._tailored_dir / result.branch
        if not (src / "resume.tex").exists():
            raise PdfError(f"No tailored resume found at {src}")

        self._run(self._tectonic, "resume.tex", cwd=src)
        pdf = src / "resume.pdf"
        if not pdf.exists():
            raise PdfError(f"Tectonic produced no resume.pdf for {result.branch}")

        dest = self._output_dir / f"{result.branch}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, dest)

        self._verify(dest, result)
        result.pdf_path = dest
        return dest

    def _verify(self, dest: Path, result: TailoredResume) -> None:
        """ATS-check the compiled PDF; warn (not fail) on missing contact terms."""
        try:
            report = self._verifier.verify(dest)
        except PdfVerificationError as exc:
            raise PdfError(f"ATS check failed for {result.branch}: {exc}") from exc
        if report["missing"]:
            print(
                f"  [warn] {result.branch}: ATS text layer missing contact terms: "
                f"{', '.join(report['missing'])}"
            )

    def _run(self, *cmd: str, cwd: Path) -> None:
        subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )


def export_all(
    results: list[TailoredResume],
    tailored_dir: str | Path = "output/tailored",
    required_terms: list[str] | None = None,
) -> list[Path]:
    """Export PDFs for all tailored resumes, isolating failures per job."""
    exporter = PdfExporter(tailored_dir, verifier=PdfVerifier(required_terms))
    paths: list[Path] = []
    for result in results:
        try:
            paths.append(exporter.export(result))
        except Exception as exc:  # noqa: BLE001 - per-job isolation
            print(f"[warn] PDF export failed for {result.branch}: {exc}")
    return paths
