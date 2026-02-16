from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }

        for key in (
            "platform",
            "message_id",
            "chat_id",
            "target_chat_id",
            "target_channel_id",
            "author_id",
            "reason",
            "attempt",
            "status_code",
            "retry_delay_s",
            "operation",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(StructuredJsonFormatter())
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def generate_correlation_id(seed: str | None = None) -> str:
    if seed and seed.strip():
        return seed
    return uuid.uuid4().hex


@contextlib.contextmanager
def correlation_context(correlation_id: str) -> Iterator[None]:
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)
