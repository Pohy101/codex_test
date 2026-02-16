from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from src.bridge.dedup_store import BaseDedupStore, InMemoryDedupStore
from src.bridge.forward_mapping_store import BaseForwardMappingStore, ForwardContext, InMemoryForwardMappingStore
from src.bridge.rules import ForwardingRules, should_forward_discord, should_forward_telegram

DISCORD_LIMIT = 2000
TELEGRAM_LIMIT = 4096

DISCORD_FILE_SIZE_LIMIT = 25 * 1024 * 1024
TELEGRAM_FILE_SIZE_LIMIT = 50 * 1024 * 1024

_DISCORD_PREFIX = "[dc]"
_TELEGRAM_PREFIX = "[tg]"

_HIDDEN_DC_MARKER = "\u2063dc_mirror\u2063"
_HIDDEN_TG_MARKER = "\u2063tg_mirror\u2063"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaItem:
    kind: Literal[
        "photo",
        "video",
        "audio",
        "voice",
        "document",
        "sticker",
        "animation",
        "video_note",
        "custom_emoji",
        "reaction",
        "other",
    ]
    platform_file_id: str | None = None
    platform_file_unique_id: str | None = None
    url: str | None = None
    mime_type: str | None = None
    filename: str | None = None
    duration: int | None = None
    caption: str | None = None
    file_size: int | None = None
    data: bytes | None = None
    emoji: str | None = None
    set_name: str | None = None
    is_animated: bool | None = None
    is_video: bool | None = None
    custom_emoji_id: str | None = None
    text_fallback: str | None = None

    def render(self) -> str:
        name = self.filename or self.kind
        if self.url:
            return f"{name}: {self.url}"
        if self.platform_file_id:
            return f"{name} (id: {self.platform_file_id})"
        if self.text_fallback:
            return self.text_fallback
        return name


@dataclass
class IncomingMessage:
    platform: str
    chat_id: int
    thread_id: int | None = None
    author_name: str = ""
    author_id: str | None = None
    is_bot: bool = False
    content: str = ""
    message_id: str | None = None
    reply_to_message_id: str | None = None
    reply_to_author: str | None = None
    reply_to_text: str | None = None
    media_items: list[MediaItem] = field(default_factory=list)

    def marker_key(self) -> str:
        msg_id = self.message_id or ""
        if not msg_id:
            return ""
        thread_part = "" if self.thread_id is None else str(self.thread_id)
        return f"{self.platform}:{self.chat_id}:{thread_part}:{msg_id}"


class MessageRouter:
    def __init__(
        self,
        *,
        discord_channel_id: int,
        telegram_chat_id: int,
        telegram_thread_id: int | None = None,
        discord_thread_id: int | None = None,
        forwarding_rules: ForwardingRules,
        discord_client: object | None = None,
        telegram_client: object | None = None,
        dedup_store: BaseDedupStore | None = None,
        forward_mapping_store: BaseForwardMappingStore | None = None,
    ) -> None:
        self.discord_channel_id = discord_channel_id
        self.telegram_chat_id = telegram_chat_id
        self.telegram_thread_id = telegram_thread_id
        self.discord_thread_id = discord_thread_id
        self.forwarding_rules = forwarding_rules
        self.discord_client = discord_client
        self.telegram_client = telegram_client
        self._dedup_store = dedup_store or InMemoryDedupStore()
        self._forward_mapping_store = forward_mapping_store or InMemoryForwardMappingStore()

    async def route_discord_to_telegram(self, message: IncomingMessage) -> None:
        if message.chat_id != self.discord_channel_id:
            return
        if self.discord_thread_id is not None and message.thread_id != self.discord_thread_id:
            return
        if await self._is_mirrored(message):
            logger.debug("Reject Discord forward: mirrored message", extra={"message_id": message.message_id})
            return

        should_forward, reason = should_forward_discord(
            author_id=message.author_id,
            is_bot=message.is_bot,
            content=message.content,
            rules=self.forwarding_rules,
        )
        if not should_forward:
            logger.debug(
                "Reject Discord forward by rules",
                extra={"reason": reason, "author_id": message.author_id, "message_id": message.message_id},
            )
            return

        target_reply_to_message_id = await self._resolve_target_reply_id(
            message=message,
            target_platform="telegram",
            target_chat_id=self.telegram_chat_id,
        )

        payload = self._format_message(
            message,
            source_prefix=_DISCORD_PREFIX,
            max_len=TELEGRAM_LIMIT,
            hidden_marker=_HIDDEN_DC_MARKER,
            include_reply_fallback=not bool(target_reply_to_message_id),
        )

        target_message_id = None
        if payload.strip():
            target_message_id = await self._send_to_telegram(
                self.telegram_chat_id,
                payload,
                message_thread_id=self.telegram_thread_id,
                reply_to_message_id=target_reply_to_message_id,
            )

        for media_item in message.media_items:
            await self._forward_media_to_telegram(
                media_item,
                chat_id=self.telegram_chat_id,
                message_thread_id=self.telegram_thread_id,
                reply_to_message_id=target_reply_to_message_id,
            )

        if not payload.strip() and not message.media_items:
            logger.debug("Reject Discord forward: empty payload", extra={"message_id": message.message_id})
            return

        await self._store_mapping(
            message=message,
            target_platform="telegram",
            target_chat_id=self.telegram_chat_id,
            target_message_id=target_message_id,
        )

    async def route_telegram_to_discord(self, message: IncomingMessage) -> None:
        if message.chat_id != self.telegram_chat_id:
            return
        if self.telegram_thread_id is not None and message.thread_id != self.telegram_thread_id:
            return
        if await self._is_mirrored(message):
            logger.debug("Reject Telegram forward: mirrored message", extra={"message_id": message.message_id})
            return

        should_forward, reason = should_forward_telegram(
            author_id=message.author_id,
            is_bot=message.is_bot,
            content=message.content,
            rules=self.forwarding_rules,
        )
        if not should_forward:
            logger.debug(
                "Reject Telegram forward by rules",
                extra={"reason": reason, "author_id": message.author_id, "message_id": message.message_id},
            )
            return

        target_reply_to_message_id = await self._resolve_target_reply_id(
            message=message,
            target_platform="discord",
            target_chat_id=self.discord_channel_id,
        )

        payload = self._format_message(
            message,
            source_prefix=_TELEGRAM_PREFIX,
            max_len=DISCORD_LIMIT,
            hidden_marker=_HIDDEN_TG_MARKER,
            include_reply_fallback=not bool(target_reply_to_message_id),
        )

        target_message_id = None
        if payload.strip():
            target_message_id = await self._send_to_discord(
                self.discord_channel_id,
                payload,
                reference_message_id=target_reply_to_message_id,
            )

        for media_item in message.media_items:
            await self._forward_media_to_discord(
                media_item,
                channel_id=self.discord_channel_id,
                reference_message_id=target_reply_to_message_id,
            )

        if not payload.strip() and not message.media_items:
            logger.debug("Reject Telegram forward: empty payload", extra={"message_id": message.message_id})
            return

        await self._store_mapping(
            message=message,
            target_platform="discord",
            target_chat_id=self.discord_channel_id,
            target_message_id=target_message_id,
        )

    def _format_message(
        self,
        message: IncomingMessage,
        *,
        source_prefix: str,
        max_len: int,
        hidden_marker: str,
        include_reply_fallback: bool,
    ) -> str:
        lines: list[str] = [f"{source_prefix} {message.author_name}: {message.content.strip()}".rstrip()]

        if include_reply_fallback and message.reply_to_text:
            reply_author = message.reply_to_author or "unknown"
            reply_excerpt = self._safe_truncate(message.reply_to_text.strip(), 180)
            lines.insert(0, f"↪ reply to {reply_author}: {reply_excerpt}")

        if message.media_items:
            lines.append("Attachments:")
            lines.extend(f"- {media_item.render()}" for media_item in message.media_items)

        merged = "\n".join(line for line in lines if line.strip())
        safe_limit = max_len - len(hidden_marker)
        return f"{self._safe_truncate(merged, safe_limit)}{hidden_marker}"

    @staticmethod
    def _safe_truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        ellipsis = "…"
        return f"{text[: limit - len(ellipsis)].rstrip()}{ellipsis}"

    async def _is_mirrored(self, message: IncomingMessage) -> bool:
        if _HIDDEN_DC_MARKER in message.content or _HIDDEN_TG_MARKER in message.content:
            return True
        key = message.marker_key()
        if not key:
            return False
        return await self._dedup_store.seen_or_add(key)

    async def _resolve_target_reply_id(
        self,
        *,
        message: IncomingMessage,
        target_platform: str,
        target_chat_id: int,
    ) -> str | None:
        if not message.reply_to_message_id:
            return None

        return await self._forward_mapping_store.get_target_message_id(
            source_platform=message.platform,
            source_chat_id=message.chat_id,
            source_message_id=message.reply_to_message_id,
            target_platform=target_platform,
            target_chat_id=target_chat_id,
        )

    async def _store_mapping(
        self,
        *,
        message: IncomingMessage,
        target_platform: str,
        target_chat_id: int,
        target_message_id: str | None,
    ) -> None:
        if not message.message_id or not target_message_id:
            return

        await self._forward_mapping_store.save_mapping(
            ForwardContext(
                source_platform=message.platform,
                source_chat_id=message.chat_id,
                source_message_id=message.message_id,
                target_platform=target_platform,
                target_chat_id=target_chat_id,
                target_message_id=target_message_id,
            )
        )

    async def _send_to_discord(
        self,
        channel_id: int,
        text: str,
        *,
        reference_message_id: str | None = None,
    ) -> str | None:
        if self.discord_client is None:
            raise RuntimeError("Discord client is not configured")
        return await self.discord_client.send_message(
            channel_id,
            text,
            reference_message_id=reference_message_id,
        )

    async def _send_to_telegram(
        self,
        chat_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
        reply_to_message_id: str | None = None,
    ) -> str | None:
        if self.telegram_client is None:
            raise RuntimeError("Telegram client is not configured")
        return await self.telegram_client.send_message(
            chat_id,
            text,
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id,
        )

    async def _forward_media_to_discord(
        self,
        media_item: MediaItem,
        *,
        channel_id: int,
        reference_message_id: str | None,
    ) -> None:
        if self.discord_client is None:
            raise RuntimeError("Discord client is not configured")

        data = media_item.data
        if data is None and media_item.platform_file_id and self.telegram_client is not None:
            data = await self.telegram_client.download_file_by_id(media_item.platform_file_id)

        if data is None:
            await self._send_to_discord(
                channel_id,
                self._unsupported_media_fallback(media_item, "discord"),
                reference_message_id=reference_message_id,
            )
            return

        if len(data) > DISCORD_FILE_SIZE_LIMIT:
            await self._send_to_discord(
                channel_id,
                self._size_limit_fallback(media_item, len(data), DISCORD_FILE_SIZE_LIMIT, "discord"),
                reference_message_id=reference_message_id,
            )
            return

        senders = {
            "photo": self.discord_client.send_photo,
            "video": self.discord_client.send_video,
            "video_note": self.discord_client.send_video,
            "audio": self.discord_client.send_audio,
            "voice": self.discord_client.send_voice,
            "document": self.discord_client.send_document,
            "sticker": self.discord_client.send_sticker,
            "animation": self.discord_client.send_video,
        }
        sender = senders.get(media_item.kind)
        if sender is None:
            await self._send_to_discord(
                channel_id,
                self._unsupported_media_fallback(media_item, "discord"),
                reference_message_id=reference_message_id,
            )
            return

        await sender(
            channel_id,
            data,
            filename=media_item.filename,
            caption=media_item.caption,
            mime_type=media_item.mime_type,
            reference_message_id=reference_message_id,
        )

    async def _forward_media_to_telegram(
        self,
        media_item: MediaItem,
        *,
        chat_id: int,
        message_thread_id: int | None,
        reply_to_message_id: str | None,
    ) -> None:
        if self.telegram_client is None:
            raise RuntimeError("Telegram client is not configured")

        data = media_item.data
        if data is None and media_item.url and self.discord_client is not None:
            data = await self.discord_client.download_attachment(media_item.url)

        if data is None:
            await self._send_to_telegram(
                chat_id,
                self._unsupported_media_fallback(media_item, "telegram"),
                message_thread_id=message_thread_id,
                reply_to_message_id=reply_to_message_id,
            )
            return

        if len(data) > TELEGRAM_FILE_SIZE_LIMIT:
            await self._send_to_telegram(
                chat_id,
                self._size_limit_fallback(media_item, len(data), TELEGRAM_FILE_SIZE_LIMIT, "telegram"),
                message_thread_id=message_thread_id,
                reply_to_message_id=reply_to_message_id,
            )
            return

        senders = {
            "photo": self.telegram_client.send_photo,
            "video": self.telegram_client.send_video,
            "video_note": self.telegram_client.send_video_note,
            "audio": self.telegram_client.send_audio,
            "voice": self.telegram_client.send_voice,
            "document": self.telegram_client.send_document,
            "sticker": self.telegram_client.send_sticker,
            "animation": self.telegram_client.send_animation,
        }
        sender = senders.get(media_item.kind)
        if sender is None:
            await self._send_to_telegram(
                chat_id,
                self._unsupported_media_fallback(media_item, "telegram"),
                message_thread_id=message_thread_id,
                reply_to_message_id=reply_to_message_id,
            )
            return

        await sender(
            chat_id,
            data,
            filename=media_item.filename,
            caption=media_item.caption,
            mime_type=media_item.mime_type,
            duration=media_item.duration,
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id,
        )

    @staticmethod
    def _unsupported_media_fallback(media_item: MediaItem, platform: str) -> str:
        details = media_item.url or media_item.platform_file_id or "no source"
        return f"Unsupported media type '{media_item.kind}' for {platform}. Source: {details}"

    @staticmethod
    def _size_limit_fallback(media_item: MediaItem, actual_size: int, limit_size: int, platform: str) -> str:
        details = media_item.url or media_item.platform_file_id or media_item.filename or media_item.kind
        return (
            f"Cannot forward {media_item.kind} to {platform}: file too large "
            f"({actual_size} bytes > {limit_size} bytes). Source: {details}"
        )
