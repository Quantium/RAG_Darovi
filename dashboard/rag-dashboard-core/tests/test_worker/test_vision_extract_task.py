"""Tests for the vision_extract Celery task."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from src.vision.extractor import ExtractedDocumentSchema, VisionExtractionResult
from src.vision.sentinels import VISION_SENTINEL_TEMPLATE
from src.worker.tasks import vision_extract


def _convert_result() -> dict:
    return {
        "drive_file_id": "f1",
        "minio_text_key": "f1.txt",
        "minio_raw_key": "f1/scan.pdf",
        "name": "scan.pdf",
        "mime_type": "application/pdf",
        "document_type": "pdf",
    }


class TestVisionExtractTask:
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("src.worker.tasks.build_storage")
    @patch("src.worker.tasks.build_settings")
    def test_noop_when_no_sentinels(self, mock_settings, mock_storage_builder, mock_repo_builder):
        mock_settings.return_value = MagicMock()
        mock_storage = MagicMock()
        mock_storage.download.return_value = b"plain text without sentinels"
        mock_storage_builder.return_value = mock_storage
        mock_repo_builder.return_value = (MagicMock(), lambda: None)

        result = vision_extract(_convert_result())

        # No upload, no upsert when there is nothing to do.
        mock_storage.upload.assert_not_called()
        assert result["drive_file_id"] == "f1"

    @patch("src.worker.tasks.redis.Redis")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("src.worker.tasks.build_storage")
    @patch("src.worker.tasks.build_settings")
    def test_replaces_sentinel_with_vlm_text_and_persists_kv(
        self,
        mock_settings,
        mock_storage_builder,
        mock_repo_builder,
        mock_redis_cls,
    ):
        from config.settings import Settings
        from pydantic import SecretStr

        s = Settings(api_key=SecretStr(""))
        mock_settings.return_value = s

        text_key = "f1.txt"
        sentinel = VISION_SENTINEL_TEMPLATE.format(page=1)
        original_text = f"--- PAGE 1 ---\n\n{sentinel}"
        raw_pdf = b"%PDF-1.4 fake bytes for testing"

        mock_storage = MagicMock()
        # Two downloads: text first, raw second.
        mock_storage.download.side_effect = [original_text.encode("utf-8"), raw_pdf]
        mock_storage_builder.return_value = mock_storage

        mock_repo = MagicMock()
        mock_repo_builder.return_value = (mock_repo, lambda: None)

        kv = ExtractedDocumentSchema(
            document_type="invoice",
            issuer="ACME",
            issued_at=date(2026, 4, 15),
            total_amount="1234.56",
            currency="USD",
            parties=["ACME", "Buyer"],
            extras={"po": "PO-1"},
        )
        extraction = VisionExtractionResult(text="Transcribed page content", kv=kv)

        # Patch rasterize_page (avoids needing a real PDF) and the extractor.
        with patch("src.vision.rasterizer.convert_from_bytes") as mock_convert:
            from PIL import Image

            mock_convert.return_value = [Image.new("RGB", (10, 10), (255, 255, 255))]

            with patch("src.worker.tasks.OllamaVisionClient"), patch(
                "src.worker.tasks.VisionExtractor"
            ) as mock_extractor_cls:
                mock_extractor = mock_extractor_cls.return_value
                # asyncio.run inside the task will execute the coroutine; provide an async stub.
                async def _extract(_image_bytes):
                    return extraction

                mock_extractor.extract = _extract

                result = vision_extract(_convert_result())

        # The patched text was uploaded back to MinIO
        upload_call = mock_storage.upload.call_args
        assert upload_call.args[1] == text_key
        uploaded_text = upload_call.args[2].decode("utf-8")
        assert "Transcribed page content" in uploaded_text
        assert sentinel not in uploaded_text

        # KV row was upserted with the values from the VLM
        mock_repo.upsert_extracted_document_sync.assert_called_once()
        kwargs = mock_repo.upsert_extracted_document_sync.call_args.kwargs
        assert kwargs["issuer"] == "ACME"
        assert kwargs["currency"] == "USD"
        assert kwargs["parties"] == ["ACME", "Buyer"]
        assert kwargs["extras"] == {"po": "PO-1"}

        assert result["kv_summary"]["issuer"] == "ACME"

    @patch("src.worker.tasks.redis.Redis")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("src.worker.tasks.build_storage")
    @patch("src.worker.tasks.build_settings")
    def test_falls_back_to_tesseract_when_breaker_open(
        self,
        mock_settings,
        mock_storage_builder,
        mock_repo_builder,
        mock_redis_cls,
    ):
        from config.settings import Settings
        from pydantic import SecretStr

        s = Settings(api_key=SecretStr(""), vision_fallback_to_tesseract=True)
        mock_settings.return_value = s

        sentinel = VISION_SENTINEL_TEMPLATE.format(page=1)
        original_text = f"--- PAGE 1 ---\n\n{sentinel}"
        mock_storage = MagicMock()
        mock_storage.download.side_effect = [original_text.encode("utf-8"), b"%PDF-1.4 fake"]
        mock_storage_builder.return_value = mock_storage
        mock_repo_builder.return_value = (MagicMock(), lambda: None)

        with patch("src.worker.tasks.CircuitBreaker") as mock_cb_cls:
            cb = mock_cb_cls.return_value
            cb.allow.return_value = False  # breaker open

            with patch.object(
                __import__("src.converter.pdf_converter", fromlist=["PdfConverter"]).PdfConverter,
                "_ocr_page_tesseract",
                return_value="Tesseract recovered text",
            ):
                result = vision_extract(_convert_result())

        upload_call = mock_storage.upload.call_args
        uploaded_text = upload_call.args[2].decode("utf-8")
        assert "Tesseract recovered text" in uploaded_text
        assert sentinel not in uploaded_text
        assert result["drive_file_id"] == "f1"
