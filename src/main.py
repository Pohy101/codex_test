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
        discord_channel_id=settings.discord_channel_id,
        telegram_chat_id=settings.telegram_chat_id,
    )

    discord_client = DiscordClient(
        token=settings.discord_bot_token,
        channel_id=settings.discord_channel_id,
        bridge=bridge,
    )
    telegram_client = TelegramClient(
        token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
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
