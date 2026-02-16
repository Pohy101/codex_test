from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from src.bridge.dedup_store import BaseDedupStore
from src.bridge.forward_mapping_store import BaseForwardMappingStore
from src.bridge.message_router import IncomingMessage, MediaItem, MessageRouter
from src.bridge.rules import ForwardingRules
from src.config import BridgePair
from src.logging_setup import correlation_context, generate_correlation_id


@dataclass
class BridgeService:
    bridge_pairs: tuple[BridgePair, ...]
    forwarding_rules: ForwardingRules
    dedup_store: BaseDedupStore
    forward_mapping_store: BaseForwardMappingStore
    discord_client: object | None = None
    telegram_client: object | None = None
    routers: list[MessageRouter] = field(init=False)
    _routers_lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._routers_lock = asyncio.Lock()
        self.routers = self._build_routers(self.bridge_pairs)

    def _build_routers(self, bridge_pairs: tuple[BridgePair, ...]) -> list[MessageRouter]:
        return [
            MessageRouter(
                discord_channel_id=pair.discord_channel_id,
                telegram_chat_id=pair.telegram_chat_id,
                telegram_thread_id=pair.telegram_thread_id,
                discord_thread_id=pair.discord_thread_id,
                forwarding_rules=self.forwarding_rules,
                discord_client=self.discord_client,
                telegram_client=self.telegram_client,
                dedup_store=self.dedup_store,
                forward_mapping_store=self.forward_mapping_store,
            )
            for pair in bridge_pairs
        ]

    async def update_bridge_pairs(self, bridge_pairs: tuple[BridgePair, ...]) -> None:
        async with self._routers_lock:
            self.bridge_pairs = bridge_pairs
            self.routers = self._build_routers(bridge_pairs)

    async def _routers_snapshot(self) -> tuple[MessageRouter, ...]:
        async with self._routers_lock:
            return tuple(self.routers)

    async def handle_discord_message(
        self,
        *,
        content: str,
        author_name: str,
        author_id: str | None,
        is_bot: bool,
        channel_id: int,
        thread_id: int | None = None,
        message_id: str | None = None,
        media_items: list[MediaItem] | None = None,
        reply_to_author: str | None = None,
        reply_to_text: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> None:
        incoming = IncomingMessage(
            platform="discord",
            chat_id=channel_id,
            thread_id=thread_id,
            author_name=author_name,
            author_id=author_id,
            is_bot=is_bot,
            content=content,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            media_items=media_items or [],
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
        )
        correlation_id = generate_correlation_id(
            f"discord:{channel_id}:{thread_id}:{message_id}" if message_id else None
        )
        routers = await self._routers_snapshot()
        with correlation_context(correlation_id):
            for router in routers:
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
        thread_id: int | None = None,
        message_id: str | None = None,
        media_items: list[MediaItem] | None = None,
        reply_to_author: str | None = None,
        reply_to_text: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> None:
        incoming = IncomingMessage(
            platform="telegram",
            chat_id=chat_id,
            thread_id=thread_id,
            author_name=author_name,
            author_id=author_id,
            is_bot=is_bot,
            content=content,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            media_items=media_items or [],
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
        )
        correlation_id = generate_correlation_id(
            f"telegram:{chat_id}:{thread_id}:{message_id}" if message_id else None
        )
        routers = await self._routers_snapshot()
        with correlation_context(correlation_id):
            for router in routers:
                router.discord_client = self.discord_client
                router.telegram_client = self.telegram_client
                await router.route_telegram_to_discord(incoming)
