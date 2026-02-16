from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from src.bridge.dedup_store import CompositeDedupStore, InMemoryDedupStore, RedisDedupStore
from src.bridge.service import BridgeService
from src.clients.discord_client import DiscordClient
from src.clients.telegram_client import TelegramClient
from src.config import load_settings
from src.logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def _heartbeat_task(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        logger.info("Bridge heartbeat")


async def run() -> None:
    configure_logging()
    settings = load_settings()

    dedup_store = InMemoryDedupStore(ttl_seconds=settings.dedup_ttl_seconds)
    if settings.dedup_redis_url:
        try:
            dedup_store = CompositeDedupStore(
                (
                    dedup_store,
                    RedisDedupStore(
                        redis_url=settings.dedup_redis_url,
                        ttl_seconds=settings.dedup_ttl_seconds,
                    ),
                )
            )
        except RuntimeError:
            logger.warning("Redis dedup store requested but redis dependency is missing")

    bridge = BridgeService(
        bridge_pairs=settings.bridge_pairs,
        forwarding_rules=settings.forwarding_rules,
        dedup_store=dedup_store,
    )

    discord_client = DiscordClient(
        token=settings.discord_bot_token,
        bridge=bridge,
    )
    telegram_client = TelegramClient(
        token=settings.telegram_bot_token,
        bridge=bridge,
    )

    bridge.discord_client = discord_client
    bridge.telegram_client = telegram_client

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def handle_shutdown() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, handle_shutdown)

    logger.info("Starting bridge clients")
    discord_task = asyncio.create_task(discord_client.start_client(), name="discord-client")
    telegram_task = asyncio.create_task(telegram_client.start_client(), name="telegram-client")
    heartbeat_task = asyncio.create_task(
        _heartbeat_task(settings.heartbeat_interval_seconds),
        name="bridge-heartbeat",
    )

    await stop_event.wait()

    logger.info("Stopping bridge clients")
    await discord_client.stop_client()
    await telegram_client.stop_client()

    for task in (discord_task, telegram_task, heartbeat_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    asyncio.run(run())
