import asyncio
import logging

from app.alerts.service import evaluate_alerts_once
from app.core.config import settings

log = logging.getLogger(__name__)


async def alert_evaluation_loop() -> None:
    while True:
        try:
            result = await evaluate_alerts_once()
            log.info(
                "alert evaluation cycle complete: evaluated=%s triggered=%s cooldown=%s unsupported=%s",
                result.evaluated_limits,
                result.triggered_limits,
                result.skipped_cooldown,
                result.skipped_unsupported,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("alert evaluation loop failed")
        await asyncio.sleep(settings.alert_evaluation_interval_seconds)
