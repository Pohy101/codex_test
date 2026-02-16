from __future__ import annotations

import discord

from src.bridge.message_router import MessageAttachment
from src.bridge.service import BridgeService


class DiscordClient(discord.Client):
    def __init__(self, *, token: str, bridge: BridgeService) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._token = token
        self._bridge = bridge

    async def on_ready(self) -> None:
        user = self.user.name if self.user else "unknown"
        print(f"Discord client connected as {user}")

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

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
            channel_id=message.channel.id,
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

        if isinstance(channel, discord.abc.Messageable):
            await channel.send(text)
            return

        raise RuntimeError("Configured Discord channel is not messageable")
