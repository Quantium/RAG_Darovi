from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import tiktoken


@dataclass
class Chunk:
    text: str
    source_file_id: str
    source_name: str
    document_type: str
    section_title: str
    chunk_index: int
    page_number: int | None = None


class DocumentChunker:
    def __init__(self, max_tokens: int = 512, overlap: int = 50) -> None:
        self._max_tokens = max_tokens
        self._overlap = overlap
        self._enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))

    def chunk(
        self, 
        text: str, 
        source_file_id: str, 
        source_name: str, 
        document_type: str
    ) -> list[Chunk]:
        """Split text into chunks based on document type and token limits."""
        if not text:
            return []

        chunks = []
        
        if document_type in ["doc", "docx"]:
            chunks = self._chunk_doc(text, source_file_id, source_name, document_type)
        elif document_type in ["sheet", "xlsx"]:
            chunks = self._chunk_sheet(text, source_file_id, source_name, document_type)
        elif document_type == "pdf":
            chunks = self._chunk_pdf(text, source_file_id, source_name, document_type)
        else:
            chunks = self._chunk_fallback(text, source_file_id, source_name, document_type)

        return chunks

    def _chunk_doc(self, text: str, source_file_id: str, source_name: str, doc_type: str) -> list[Chunk]:
        # Split by headings
        sections = re.split(r'^(#+ .*)$', text, flags=re.MULTILINE)
        
        results = []
        current_section_title = "Introduction"
        chunk_idx = 0
        
        # re.split returns [text_before, heading1, text_after1, heading2, text_after2, ...]
        # If it starts with a heading, first element is empty.
        i = 0
        if sections[0].strip():
            # First part before any heading
            sub_chunks = self._split_with_overlap(sections[0], self._max_tokens, self._overlap)
            for sc in sub_chunks:
                results.append(Chunk(sc, source_file_id, source_name, doc_type, current_section_title, chunk_idx))
                chunk_idx += 1
            i = 1
        else:
            i = 1

        while i < len(sections):
            current_section_title = sections[i].strip("# ").strip()
            section_body = sections[i+1] if i+1 < len(sections) else ""
            
            sub_chunks = self._split_with_overlap(section_body, self._max_tokens, self._overlap)
            for sc in sub_chunks:
                # Prepend heading to chunk text for context if it's not already there
                chunk_text = f"{sections[i].strip()}\n\n{sc}" if sc.strip() else sections[i].strip()
                results.append(Chunk(chunk_text, source_file_id, source_name, doc_type, current_section_title, chunk_idx))
                chunk_idx += 1
            i += 2
            
        return results

    def _chunk_pdf(self, text: str, source_file_id: str, source_name: str, doc_type: str) -> list[Chunk]:
        # Split by page markers
        pages = re.split(r'--- PAGE (\d+) ---', text)
        
        results = []
        chunk_idx = 0
        
        # [ignored, page_num1, content1, page_num2, content2, ...]
        for i in range(1, len(pages), 2):
            page_num = int(pages[i])
            content = pages[i+1]
            
            sub_chunks = self._split_with_overlap(content, self._max_tokens, self._overlap)
            for sc in sub_chunks:
                results.append(Chunk(sc, source_file_id, source_name, doc_type, "", chunk_idx, page_number=page_num))
                chunk_idx += 1
                
        if not results and text: # If no page markers found
             return self._chunk_fallback(text, source_file_id, source_name, doc_type)
             
        return results

    def _chunk_sheet(self, text: str, source_file_id: str, source_name: str, doc_type: str) -> list[Chunk]:
        # Split by sheet headers
        sheets = re.split(r'## Sheet: (.*?)\n', text)
        
        results = []
        chunk_idx = 0
        
        # [ignored, sheet_name1, content1, sheet_name2, content2, ...]
        for i in range(1, len(sheets), 2):
            sheet_name = sheets[i]
            content = sheets[i+1]
            
            # For sheets, we might want smaller chunks or row-based
            # Simple approach: split by rows but keep header
            lines = content.strip().splitlines()
            if not lines: continue
            
            header = lines[0] if len(lines) > 0 else ""
            rows = lines[1:] if len(lines) > 1 else []
            
            # Group rows to fit max_tokens
            current_rows = []
            for row in rows:
                current_text = "\n".join([header] + current_rows + [row])
                if self._count_tokens(current_text) > self._max_tokens and current_rows:
                    results.append(Chunk("\n".join([f"Sheet: {sheet_name}", header] + current_rows), 
                                         source_file_id, source_name, doc_type, sheet_name, chunk_idx))
                    chunk_idx += 1
                    current_rows = [row]
                else:
                    current_rows.append(row)
            
            if current_rows:
                results.append(Chunk("\n".join([f"Sheet: {sheet_name}", header] + current_rows), 
                                     source_file_id, source_name, doc_type, sheet_name, chunk_idx))
                chunk_idx += 1
                
        if not results and text:
             return self._chunk_fallback(text, source_file_id, source_name, doc_type)

        return results

    def _chunk_fallback(self, text: str, source_file_id: str, source_name: str, doc_type: str) -> list[Chunk]:
        sub_chunks = self._split_with_overlap(text, self._max_tokens, self._overlap)
        return [
            Chunk(sc, source_file_id, source_name, doc_type, "", i)
            for i, sc in enumerate(sub_chunks)
        ]

    def _split_with_overlap(self, text: str, max_tokens: int, overlap: int) -> list[str]:
        tokens = self._enc.encode(text)
        if not tokens:
            return []
            
        results = []
        start = 0
        while start < len(tokens):
            end = start + max_tokens
            chunk_tokens = tokens[start:end]
            results.append(self._enc.decode(chunk_tokens))
            
            if end >= len(tokens):
                break
            start = end - overlap
            
        return results
