from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


async def retry_with_backoff(
    operation_name: str,
    call: Callable[[], Awaitable[Any]],
    *,
    is_retryable: Callable[[Exception], tuple[bool, int | None]],
    max_attempts: int = 5,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            await call()
            return
        except Exception as exc:
            should_retry, status_code = is_retryable(exc)
            if not should_retry or attempt == max_attempts:
                raise

            delay_seconds = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
            logger.warning(
                "Retrying temporary API error",
                extra={
                    "operation": operation_name,
                    "attempt": attempt,
                    "status_code": status_code,
                    "retry_delay_s": delay_seconds,
                },
                exc_info=exc,
            )
            await asyncio.sleep(delay_seconds)
