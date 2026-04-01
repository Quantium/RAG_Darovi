from __future__ import annotations

import io

import docx
import structlog

from src.converter.base import FileConverter

logger = structlog.get_logger()


class DocxConverter(FileConverter):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Convert Microsoft Word .docx to plain text."""
        logger.info("converter.docx.start", file_name=file_name)
        
        if not raw_bytes:
            return ""

        try:
            doc = docx.Document(io.BytesIO(raw_bytes))
            output = []
            
            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue
                
                # Try to map styles to markdown if possible
                style = para.style.name if para.style else ""
                if "Heading 1" in style:
                    output.append(f"# {text}")
                elif "Heading 2" in style:
                    output.append(f"## {text}")
                elif "Heading 3" in style:
                    output.append(f"### {text}")
                else:
                    output.append(text)
            
            # Extract tables
            for table in doc.tables:
                table_text = self._format_table(table)
                if table_text:
                    output.append("\n" + table_text)
                    
            return "\n\n".join(output)
        except Exception as e:
            logger.error("converter.docx.error", file_name=file_name, error=str(e))
            raise

    def _format_table(self, table: docx.table.Table) -> str:
        lines = []
        for i, row in enumerate(table.rows):
            cells = [cell.text.strip() for cell in row.cells]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
        return "\n".join(lines)
