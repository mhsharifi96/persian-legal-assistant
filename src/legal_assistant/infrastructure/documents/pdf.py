from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


class PyPdfTextExtractor:
    def extract(self, path: Path) -> str:
        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()
