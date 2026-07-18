from __future__ import annotations

import json
from pathlib import Path

import pytest

from legal_assistant.infrastructure.parsers.local_file import (
    LocalFileDocumentParser,
    UnsupportedDocumentFormatError,
)


def test_jsonl_parser_maps_flexible_records_to_legal_documents(tmp_path: Path) -> None:
    source = tmp_path / "documents.jsonl"
    records = [
        {
            "id": "civil-law",
            "title": "قانون مدنی",
            "url": "https://example.test/civil-law",
            "document_type": "law",
            "text": "ماده ۱ - متن قانون",
            "category": "حقوق مدنی",
        },
        {"content": "متن عمومی", "metadata": {"language": "fa"}},
    ]
    source.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )

    documents = LocalFileDocumentParser().parse(str(source))

    assert len(documents) == 2
    assert documents[0].title == "قانون مدنی"
    assert documents[0].source_uri == "https://example.test/civil-law"
    assert documents[0].document_type == "law"
    assert documents[0].metadata["source_format"] == "jsonl"
    assert documents[0].metadata["category"] == "حقوق مدنی"
    assert documents[1].metadata["language"] == "fa"
    assert documents[0].id != documents[1].id


def test_local_parser_rejects_unknown_file_format(tmp_path: Path) -> None:
    source = tmp_path / "document.txt"
    source.write_text("text", encoding="utf-8")

    with pytest.raises(UnsupportedDocumentFormatError, match="Supported formats"):
        LocalFileDocumentParser().parse(str(source))


def test_docx_parser_extracts_paragraphs_and_tables(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    source = tmp_path / "contract.docx"
    word_document = docx.Document()
    word_document.add_paragraph("عنوان قرارداد")
    table = word_document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "طرف اول"
    table.cell(0, 1).text = "طرف دوم"
    word_document.save(source)

    document = LocalFileDocumentParser().parse(str(source))[0]

    assert "عنوان قرارداد" in document.text
    assert "طرف اول\tطرف دوم" in document.text
    assert document.metadata["source_format"] == "docx"


def test_xlsx_parser_returns_one_document_per_sheet(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "laws.xlsx"
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "قوانین"
    first.append(["عنوان", "متن"])
    second = workbook.create_sheet("آراء")
    second.append(["شماره", 12])
    workbook.save(source)

    documents = LocalFileDocumentParser().parse(str(source))

    assert [document.metadata["sheet_name"] for document in documents] == ["قوانین", "آراء"]
    assert "عنوان\tمتن" in documents[0].text
    assert documents[0].id != documents[1].id


def test_pdf_parser_records_page_count(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    source = tmp_path / "law.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with source.open("wb") as handle:
        writer.write(handle)

    document = LocalFileDocumentParser().parse(str(source))[0]

    assert document.metadata["source_format"] == "pdf"
    assert document.metadata["page_count"] == 1
