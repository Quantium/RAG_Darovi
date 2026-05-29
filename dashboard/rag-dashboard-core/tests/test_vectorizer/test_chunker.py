"""Tests for src/vectorizer/chunker.py — turns GREEN in Phase 3."""

from __future__ import annotations


from src.vectorizer.chunker import DocumentChunker


class TestDocumentChunker:
    def test_chunk_by_headings(self, sample_text):
        """Verify that Markdown headings produce multiple chunks with heading content."""
        chunker = DocumentChunker()
        chunks = chunker.chunk(sample_text, source_file_id="f1", source_name="report.pdf", document_type="doc")
        assert len(chunks) > 1
        assert any("Revenue" in c.text for c in chunks)

    def test_chunk_metadata_includes_source(self, sample_text):
        """Verify each chunk carries the correct source_file_id and an integer chunk_index."""
        chunker = DocumentChunker()
        chunks = chunker.chunk(sample_text, source_file_id="f1", source_name="report.pdf", document_type="doc")
        for chunk in chunks:
            assert chunk.source_file_id == "f1"
            assert isinstance(chunk.chunk_index, int)

    def test_chunk_metadata_includes_section(self, sample_text):
        """Verify at least one chunk has a non-empty section_title derived from headings."""
        chunker = DocumentChunker()
        chunks = chunker.chunk(sample_text, source_file_id="f1", source_name="report.pdf", document_type="doc")
        assert any(c.section_title != "" for c in chunks)

    def test_chunk_respects_max_tokens(self):
        """Verify no chunk exceeds the max_tokens limit (with a small overlap buffer)."""
        long_text = "word " * 2000
        chunker = DocumentChunker(max_tokens=512)
        chunks = chunker.chunk(long_text, source_file_id="f1", source_name="long.txt", document_type="doc")
        for chunk in chunks:
            assert len(chunk.text.split()) <= 520  # small buffer for overlap

    def test_chunk_overlap(self):
        """Verify that consecutive chunks share tokens at their boundary (overlap is applied)."""
        long_text = " ".join(f"word{i}" for i in range(1000))
        chunker = DocumentChunker(max_tokens=512, overlap=50)
        chunks = chunker.chunk(long_text, source_file_id="f1", source_name="long.txt", document_type="doc")
        if len(chunks) >= 2:
            end_of_first = set(chunks[0].text.split()[-50:])
            start_of_second = set(chunks[1].text.split()[:50])
            assert len(end_of_first & start_of_second) > 0

    def test_csv_chunk_preserves_headers(self):
        """Verify sheet chunks include the column header row from the original CSV text."""
        csv_text = "## Sheet: Data\nName,Age\nAlice,30\nBob,25"
        chunker = DocumentChunker()
        chunks = chunker.chunk(csv_text, source_file_id="f1", source_name="data.csv", document_type="sheet")
        for chunk in chunks:
            assert "Name" in chunk.text or "Sheet" in chunk.text

    def test_empty_text_returns_empty_list(self):
        """Verify chunking an empty string returns an empty list without error."""
        chunker = DocumentChunker()
        chunks = chunker.chunk("", source_file_id="f1", source_name="empty.txt", document_type="doc")
        assert chunks == []
