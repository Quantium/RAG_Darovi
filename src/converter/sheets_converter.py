from __future__ import annotations

import csv
import io

import structlog

from src.converter.base import FileConverter

logger = structlog.get_logger()


class SheetsConverter(FileConverter):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Convert Google Sheets CSV export to formatted markdown-like text."""
        logger.info("converter.sheets.start", file_name=file_name)
        
        if not raw_bytes:
            return ""

        try:
            content = raw_bytes.decode("utf-8")
            
            # Detect if it has multiple sheets based on "Sheet: " or "--- SHEET: " markers
            if "Sheet: " in content or "--- SHEET: " in content:
                return self._process_multi_sheet(content)
            else:
                return self._process_single_sheet(content, "Sheet 1")
                
        except Exception as e:
            logger.error("converter.sheets.error", file_name=file_name, error=str(e))
            raise

    def _process_multi_sheet(self, content: str) -> str:
        sections = []
        # Split by what looks like sheet headers
        # This is a bit naive but should work for the provided test cases
        import re
        parts = re.split(r'(?:Sheet: |--- SHEET: )(.*?)\n', content)
        
        # re.split with capture groups returns [ignored, name1, content1, name2, content2, ...]
        if len(parts) > 1:
            for i in range(1, len(parts), 2):
                name = parts[i].strip().strip("- ")
                sheet_content = parts[i+1]
                sections.append(self._process_single_sheet(sheet_content, name))
        else:
            # Fallback if split didn't work as expected
            sections.append(self._process_single_sheet(content, "Data"))
            
        return "\n\n".join(sections)

    def _process_single_sheet(self, csv_text: str, sheet_name: str) -> str:
        if not csv_text.strip():
            return f"## Sheet: {sheet_name}\n\n(Empty)"

        output = [f"## Sheet: {sheet_name}\n"]
        
        reader = csv.reader(io.StringIO(csv_text.strip()))
        for row in reader:
            if not row:
                continue
            # Format row as pipe-separated values for markdown-ish look
            output.append("| " + " | ".join(row) + " |")
            
            # Add separator after header
            if len(output) == 2:
                output.append("| " + " | ".join(["---"] * len(row)) + " |")
        
        return "\n".join(output)
