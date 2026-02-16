from __future__ import annotations

from dataclasses import dataclass, field

from src.bridge.message_router import IncomingMessage, MessageAttachment, MessageRouter


@dataclass
class BridgeService:
    discord_channel_id: int
    telegram_chat_id: int
    discord_client: object | None = None
    telegram_client: object | None = None
    router: MessageRouter = field(init=False)

    def __post_init__(self) -> None:
        self.router = MessageRouter(
            discord_channel_id=self.discord_channel_id,
            telegram_chat_id=self.telegram_chat_id,
            discord_client=self.discord_client,
            telegram_client=self.telegram_client,
        )

    async def handle_discord_message(
        self,
        *,
        content: str,
        author_name: str,
        channel_id: int,
        message_id: str | None = None,
        attachments: list[MessageAttachment] | None = None,
        reply_to_author: str | None = None,
        reply_to_text: str | None = None,
    ) -> None:
        self.router.discord_client = self.discord_client
        self.router.telegram_client = self.telegram_client
        incoming = IncomingMessage(
            platform="discord",
            chat_id=channel_id,
            author_name=author_name,
            content=content,
            message_id=message_id,
            attachments=attachments or [],
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
        )
        await self.router.route_discord_to_telegram(incoming)

    async def handle_telegram_message(
        self,
        *,
        content: str,
        author_name: str,
        chat_id: int,
        message_id: str | None = None,
        attachments: list[MessageAttachment] | None = None,
        reply_to_author: str | None = None,
        reply_to_text: str | None = None,
    ) -> None:
        self.router.discord_client = self.discord_client
        self.router.telegram_client = self.telegram_client
        incoming = IncomingMessage(
            platform="telegram",
            chat_id=chat_id,
            author_name=author_name,
            content=content,
            message_id=message_id,
            attachments=attachments or [],
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
        )
        await self.router.route_telegram_to_discord(incoming)
