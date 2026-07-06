from legal_assistant.domain.models import LegalDocument
from legal_assistant.infrastructure.chunkers import PersianLegalHierarchicalChunker


def test_persian_legal_chunker_preserves_hierarchy_and_note_metadata() -> None:
    text = """کتاب اول
باب اول
فصل دوم
ماده ۱۰ - قراردادهای خصوصی نسبت به کسانی که آن را منعقد نموده‌اند نافذ است.
تبصره ۱ - این تبصره برای نمونه است.
تبصره ۲ - تبصره دوم باید جداگانه حفظ شود.
ماده ۱۱: اموال بر دو قسم است."""
    document = LegalDocument(
        id="civil-code",
        title="قانون مدنی",
        source_uri="file:///laws/civil-code.txt",
        jurisdiction="IR",
        document_type="law",
        text=text,
        parser_name="fake",
        metadata={"page_start": 1, "page_end": 2},
    )

    chunks = PersianLegalHierarchicalChunker().chunk(document)

    assert len(chunks) == 4
    assert [chunk.hierarchy.article_number for chunk in chunks] == ["10", "10", "10", "11"]
    assert [chunk.hierarchy.note_number for chunk in chunks] == [None, "1", "2", None]
    assert all(chunk.metadata["book"] == "کتاب اول" for chunk in chunks)
    assert all(chunk.metadata["bab"] == "باب اول" for chunk in chunks)
    assert all(chunk.metadata["fasl"] == "فصل دوم" for chunk in chunks)
    assert chunks[0].metadata["char_start"] < chunks[0].metadata["char_end"]
    assert chunks[0].metadata["chunking_strategy"] == "iranian_legal_hierarchical_v1"
    assert "ماده 10" in chunks[0].citations[0]
    assert "تبصره 1" in chunks[1].citations[0]


def test_persian_legal_chunker_handles_arabic_digits() -> None:
    document = LegalDocument(
        id="sample-law",
        title="قانون نمونه",
        source_uri="file:///sample.txt",
        jurisdiction="IR",
        document_type="law",
        text="ماده ١٢ - متن ماده\nتبصره ٢ - متن تبصره",
    )

    chunks = PersianLegalHierarchicalChunker().chunk(document)

    assert [chunk.hierarchy.article_number for chunk in chunks] == ["12", "12"]
    assert chunks[1].hierarchy.note_number == "2"
