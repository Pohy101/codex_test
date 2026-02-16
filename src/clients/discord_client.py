from __future__ import annotations

import logging

import discord

from src.bridge.message_router import MessageAttachment
from src.bridge.service import BridgeService
from src.retry import retry_with_backoff

logger = logging.getLogger(__name__)


class DiscordClient(discord.Client):
    def __init__(self, *, token: str, bridge: BridgeService) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._token = token
        self._bridge = bridge

    async def on_ready(self) -> None:
        user = self.user.name if self.user else "unknown"
        logger.info("Discord client connected", extra={"author_id": user})

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        channel_id = message.channel.id
        thread_id = None
        if isinstance(message.channel, discord.Thread):
            thread_id = message.channel.id
            channel_id = message.channel.parent_id or message.channel.id

        reply_to_author = None
        reply_to_text = None
        if message.reference and message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
            ref = message.reference.resolved
            reply_to_author = ref.author.display_name
            reply_to_text = ref.content

        attachments = [
            MessageAttachment(filename=attachment.filename, url=attachment.url)
            for attachment in message.attachments
        ]

        await self._bridge.handle_discord_message(
            content=message.content,
            author_name=message.author.display_name,
            author_id=str(message.author.id),
            is_bot=message.author.bot,
            channel_id=channel_id,
            thread_id=thread_id,
            message_id=str(message.id),
            attachments=attachments,
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
        )

    async def start_client(self) -> None:
        await self.start(self._token)

    async def stop_client(self) -> None:
        if not self.is_closed():
            await self.close()

    async def send_message(self, channel_id: int, text: str) -> None:
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)

        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("Configured Discord channel is not messageable")

        def _is_retryable(exc: Exception) -> tuple[bool, int | None]:
            if isinstance(exc, discord.HTTPException):
                status_code = exc.status
                return status_code in {429, 500, 502, 503, 504}, status_code
            return False, None

        await retry_with_backoff(
            "discord.send_message",
            lambda: channel.send(text),
            is_retryable=_is_retryable,
        )
