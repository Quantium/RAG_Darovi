from __future__ import annotations

import structlog
from config.settings import Settings

logger = structlog.get_logger()


class MilvusStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        logger.info("milvus_store.init", endpoint=settings.milvus_endpoint)

    def delete_by_source(self, source_id: str) -> None:
        """Placeholder for deleting vectors by source ID in Milvus."""
        logger.info("milvus_store.delete_by_source", source_id=source_id, status="placeholder_called")
        # Actual implementation will be in Phase 5
