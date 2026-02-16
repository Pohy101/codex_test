from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

DISCORD_LIMIT = 2000
TELEGRAM_LIMIT = 4096

_DISCORD_PREFIX = "[dc]"
_TELEGRAM_PREFIX = "[tg]"

_HIDDEN_DC_MARKER = "\u2063dc_mirror\u2063"
_HIDDEN_TG_MARKER = "\u2063tg_mirror\u2063"


@dataclass(frozen=True)
class MessageAttachment:
    filename: str | None = None
    url: str | None = None

    def render(self) -> str:
        if self.filename and self.url:
            return f"{self.filename}: {self.url}"
        return self.url or self.filename or "attachment"


@dataclass
class IncomingMessage:
    platform: str
    chat_id: int
    author_name: str
    content: str = ""
    message_id: str | None = None
    reply_to_author: str | None = None
    reply_to_text: str | None = None
    attachments: list[MessageAttachment] = field(default_factory=list)

    def marker_key(self) -> str:
        msg_id = self.message_id or ""
        return f"{self.platform}:{self.chat_id}:{msg_id}" if msg_id else ""


class MessageRouter:
    def __init__(
        self,
        *,
        discord_channel_id: int,
        telegram_chat_id: int,
        discord_client: object | None = None,
        telegram_client: object | None = None,
        marker_cache_size: int = 2000,
    ) -> None:
        self.discord_channel_id = discord_channel_id
        self.telegram_chat_id = telegram_chat_id
        self.discord_client = discord_client
        self.telegram_client = telegram_client
        self._marker_cache_size = marker_cache_size
        self._marker_cache: deque[str] = deque(maxlen=marker_cache_size)
        self._marker_lookup: set[str] = set()

    async def route_discord_to_telegram(self, message: IncomingMessage) -> None:
        if message.chat_id != self.discord_channel_id:
            return
        if self._is_mirrored(message):
            return

        payload = self._format_message(
            message,
            source_prefix=_DISCORD_PREFIX,
            max_len=TELEGRAM_LIMIT,
            hidden_marker=_HIDDEN_DC_MARKER,
        )
        if not payload.strip():
            return

        self._remember_marker(message)
        await self._send_to_telegram(payload)

    async def route_telegram_to_discord(self, message: IncomingMessage) -> None:
        if message.chat_id != self.telegram_chat_id:
            return
        if self._is_mirrored(message):
            return

        payload = self._format_message(
            message,
            source_prefix=_TELEGRAM_PREFIX,
            max_len=DISCORD_LIMIT,
            hidden_marker=_HIDDEN_TG_MARKER,
        )
        if not payload.strip():
            return

        self._remember_marker(message)
        await self._send_to_discord(payload)

    def _format_message(
        self,
        message: IncomingMessage,
        *,
        source_prefix: str,
        max_len: int,
        hidden_marker: str,
    ) -> str:
        lines: list[str] = [f"{source_prefix} {message.author_name}: {message.content.strip()}".rstrip()]

        if message.reply_to_text:
            reply_author = message.reply_to_author or "unknown"
            reply_excerpt = self._safe_truncate(message.reply_to_text.strip(), 180)
            lines.insert(0, f"↪ reply to {reply_author}: {reply_excerpt}")

        if message.attachments:
            lines.append("Attachments:")
            lines.extend(f"- {attachment.render()}" for attachment in message.attachments)

        merged = "\n".join(line for line in lines if line.strip())
        safe_limit = max_len - len(hidden_marker)
        return f"{self._safe_truncate(merged, safe_limit)}{hidden_marker}"

    @staticmethod
    def _safe_truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        ellipsis = "…"
        return f"{text[: limit - len(ellipsis)].rstrip()}{ellipsis}"

    def _is_mirrored(self, message: IncomingMessage) -> bool:
        if _HIDDEN_DC_MARKER in message.content or _HIDDEN_TG_MARKER in message.content:
            return True
        key = message.marker_key()
        return bool(key) and key in self._marker_lookup

    def _remember_marker(self, message: IncomingMessage) -> None:
        key = message.marker_key()
        if not key:
            return
        if key in self._marker_lookup:
            return

        if len(self._marker_cache) == self._marker_cache_size:
            expired = self._marker_cache[0]
            self._marker_lookup.discard(expired)

        self._marker_cache.append(key)
        self._marker_lookup.add(key)

    async def _send_to_discord(self, text: str) -> None:
        if self.discord_client is None:
            raise RuntimeError("Discord client is not configured")
        await self.discord_client.send_message(text)

    async def _send_to_telegram(self, text: str) -> None:
        if self.telegram_client is None:
            raise RuntimeError("Telegram client is not configured")
        await self.telegram_client.send_message(text)
