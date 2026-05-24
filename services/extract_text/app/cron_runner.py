from __future__ import annotations

import time
from datetime import datetime, timezone

from croniter import croniter
import structlog

logger = structlog.get_logger()


def run_forever(cron_expression: str, run_once) -> None:
    next_fire = croniter(cron_expression, datetime.now(timezone.utc)).get_next(datetime)
    logger.info("extract_text.scheduler.started", cron=cron_expression, next_fire=next_fire.isoformat())
    while True:
        now = datetime.now(timezone.utc)
        if now >= next_fire:
            run_once()
            next_fire = croniter(cron_expression, now).get_next(datetime)
            logger.info("extract_text.scheduler.next_fire", next_fire=next_fire.isoformat())
            continue
        sleep_seconds = max(1, int((next_fire - now).total_seconds()))
        time.sleep(min(30, sleep_seconds))
