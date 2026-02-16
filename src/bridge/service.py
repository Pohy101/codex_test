from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BridgeService:
    discord_channel_id: int
    telegram_chat_id: int
    discord_client: object | None = None
    telegram_client: object | None = None

    async def handle_discord_message(self, *, content: str, author_name: str, channel_id: int) -> None:
        if channel_id != self.discord_channel_id or not content.strip():
            return
        text = f"[Discord] {author_name}: {content}"
        await self.forward_to_telegram(text)

    async def handle_telegram_message(self, *, content: str, author_name: str, chat_id: int) -> None:
        if chat_id != self.telegram_chat_id or not content.strip():
            return
        text = f"[Telegram] {author_name}: {content}"
        await self.forward_to_discord(text)

    async def forward_to_discord(self, text: str) -> None:
        if self.discord_client is None:
            raise RuntimeError("Discord client is not configured")
        await self.discord_client.send_message(text)

    async def forward_to_telegram(self, text: str) -> None:
        if self.telegram_client is None:
            raise RuntimeError("Telegram client is not configured")
        await self.telegram_client.send_message(text)
