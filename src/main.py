from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import uvicorn

from src.admin.app import AdminContext, create_admin_app
from src.admin.store import BridgePairStore
from src.bridge.dedup_store import CompositeDedupStore, InMemoryDedupStore, RedisDedupStore
from src.bridge.forward_mapping_store import SQLiteForwardMappingStore
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

    forward_mapping_store = SQLiteForwardMappingStore(
        db_path=settings.forward_mapping_sqlite_path,
        max_items=settings.forward_mapping_max_items,
    )

    bridge_pair_store = BridgePairStore(settings.bridge_pairs_store_path)
    stored_pairs = bridge_pair_store.initialize(settings.bridge_pairs)

    bridge = BridgeService(
        bridge_pairs=tuple(pair.to_bridge_pair() for pair in stored_pairs),
        forwarding_rules=settings.forwarding_rules,
        dedup_store=dedup_store,
        forward_mapping_store=forward_mapping_store,
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
    stop_wait_task = asyncio.create_task(stop_event.wait(), name="stop-wait")

    tasks = (discord_task, telegram_task)

    try:
        done, _ = await asyncio.wait(
            (*tasks, stop_wait_task),
            return_when=asyncio.FIRST_COMPLETED,
        )

        if stop_wait_task not in done:
            for task in done:
                if task is stop_wait_task:
                    continue

                if task.cancelled():
                    raise RuntimeError(f"{task.get_name()} was cancelled during startup")

                exc = task.exception()
                if exc is not None:
                    raise RuntimeError(f"{task.get_name()} failed during startup") from exc

                raise RuntimeError(f"{task.get_name()} exited unexpectedly")
    finally:
        stop_wait_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_wait_task

        await discord_client.stop_client()
        await telegram_client.stop_client()

        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    asyncio.run(run())
