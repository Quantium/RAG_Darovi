from __future__ import annotations

import gspread
import structlog

logger = structlog.get_logger()


class SheetsWriter:
    def __init__(self, credentials_path: str) -> None:
        self._gc = gspread.service_account(
            filename=credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )

    def write_rows(self, spreadsheet_id: str, sheet_name: str, rows: list[list[str]]) -> None:
        """Open a spreadsheet and append rows to a worksheet."""
        if not rows:
            return

        try:
            spreadsheet = self._gc.open_by_key(spreadsheet_id)

            try:
                worksheet = spreadsheet.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                # Create if not found: default 1000 rows, 26 columns (A-Z)
                worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=26)
                logger.info("sheets.worksheet_created", sheet=sheet_name)

            worksheet.append_rows(rows)
            logger.info("sheets.rows_appended", sheet=sheet_name, rows=len(rows))
        except Exception as exc:
            logger.error("sheets.write_error", spreadsheet_id=spreadsheet_id, error=str(exc))
            raise
