from __future__ import annotations

import discord

from src.bridge.service import BridgeService


class DiscordClient(discord.Client):
    def __init__(self, *, token: str, channel_id: int, bridge: BridgeService) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._token = token
        self._channel_id = channel_id
        self._bridge = bridge

    async def on_ready(self) -> None:
        user = self.user.name if self.user else "unknown"
        print(f"Discord client connected as {user}")

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user or message.author.bot:
            return

        await self._bridge.handle_discord_message(
            content=message.content,
            author_name=message.author.display_name,
            channel_id=message.channel.id,
        )

    async def start_client(self) -> None:
        await self.start(self._token)

    async def stop_client(self) -> None:
        if not self.is_closed():
            await self.close()

    async def send_message(self, text: str) -> None:
        channel = self.get_channel(self._channel_id)
        if channel is None:
            channel = await self.fetch_channel(self._channel_id)

        if isinstance(channel, discord.abc.Messageable):
            await channel.send(text)
            return

        raise RuntimeError("Configured Discord channel is not messageable")
