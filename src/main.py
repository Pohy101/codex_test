from __future__ import annotations

import asyncio
import contextlib
import signal

from src.bridge.service import BridgeService
from src.clients.discord_client import DiscordClient
from src.clients.telegram_client import TelegramClient
from src.config import load_settings


async def run() -> None:
    settings = load_settings()

    bridge = BridgeService(
        bridge_pairs=settings.bridge_pairs,
        forwarding_rules=settings.forwarding_rules,
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

    discord_task = asyncio.create_task(discord_client.start_client(), name="discord-client")
    telegram_task = asyncio.create_task(telegram_client.start_client(), name="telegram-client")

    await stop_event.wait()

    await discord_client.stop_client()
    await telegram_client.stop_client()

    for task in (discord_task, telegram_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    asyncio.run(run())
