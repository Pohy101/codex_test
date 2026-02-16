from __future__ import annotations

from dataclasses import dataclass, field

from src.bridge.dedup_store import BaseDedupStore
from src.bridge.message_router import IncomingMessage, MessageAttachment, MessageRouter
from src.bridge.rules import ForwardingRules
from src.config import BridgePair
from src.logging_setup import correlation_context, generate_correlation_id


@dataclass
class BridgeService:
    bridge_pairs: tuple[BridgePair, ...]
    forwarding_rules: ForwardingRules
    dedup_store: BaseDedupStore
    discord_client: object | None = None
    telegram_client: object | None = None
    routers: list[MessageRouter] = field(init=False)

    def __post_init__(self) -> None:
        self.routers = [
            MessageRouter(
                discord_channel_id=pair.discord_channel_id,
                telegram_chat_id=pair.telegram_chat_id,
                forwarding_rules=self.forwarding_rules,
                discord_client=self.discord_client,
                telegram_client=self.telegram_client,
                dedup_store=self.dedup_store,
            )
            for pair in self.bridge_pairs
        ]

    async def handle_discord_message(
        self,
        *,
        content: str,
        author_name: str,
        author_id: str | None,
        is_bot: bool,
        channel_id: int,
        message_id: str | None = None,
        attachments: list[MessageAttachment] | None = None,
        reply_to_author: str | None = None,
        reply_to_text: str | None = None,
    ) -> None:
        incoming = IncomingMessage(
            platform="discord",
            chat_id=channel_id,
            author_name=author_name,
            author_id=author_id,
            is_bot=is_bot,
            content=content,
            message_id=message_id,
            attachments=attachments or [],
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
        )
        correlation_id = generate_correlation_id(
            f"discord:{channel_id}:{message_id}" if message_id else None
        )
        with correlation_context(correlation_id):
            for router in self.routers:
                router.discord_client = self.discord_client
                router.telegram_client = self.telegram_client
                await router.route_discord_to_telegram(incoming)

    async def handle_telegram_message(
        self,
        *,
        content: str,
        author_name: str,
        author_id: str | None,
        is_bot: bool,
        chat_id: int,
        message_id: str | None = None,
        attachments: list[MessageAttachment] | None = None,
        reply_to_author: str | None = None,
        reply_to_text: str | None = None,
    ) -> None:
        incoming = IncomingMessage(
            platform="telegram",
            chat_id=chat_id,
            author_name=author_name,
            author_id=author_id,
            is_bot=is_bot,
            content=content,
            message_id=message_id,
            attachments=attachments or [],
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
        )
        correlation_id = generate_correlation_id(
            f"telegram:{chat_id}:{message_id}" if message_id else None
        )
        with correlation_context(correlation_id):
            for router in self.routers:
                router.discord_client = self.discord_client
                router.telegram_client = self.telegram_client
                await router.route_telegram_to_discord(incoming)
