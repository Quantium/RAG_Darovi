from __future__ import annotations

import io

import openpyxl
import structlog

from src.converter.base import FileConverter

logger = structlog.get_logger()


class XlsxConverter(FileConverter):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Convert Microsoft Excel .xlsx to formatted markdown-like text."""
        logger.info("converter.xlsx.start", file_name=file_name)
        
        if not raw_bytes:
            return ""

        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
            output = []
            
            for sheet in wb.worksheets:
                output.append(f"## Sheet: {sheet.title}\n")
                
                # Extract rows as CSV-like pipe separated values
                rows = list(sheet.iter_rows(values_only=True))
                if not rows:
                    output.append("(Empty)")
                    continue
                
                for i, row in enumerate(rows):
                    # Filter out completely empty rows
                    if not any(cell is not None for cell in row):
                        continue
                    
                    cells = [str(cell) if cell is not None else "" for cell in row]
                    output.append("| " + " | ".join(cells) + " |")
                    
                    if i == 0:  # Header separator
                         output.append("| " + " | ".join(["---"] * len(cells)) + " |")
                
                output.append("")  # Spacing between sheets
                
            return "\n".join(output)
        except Exception as e:
            logger.error("converter.xlsx.error", file_name=file_name, error=str(e))
            raise
