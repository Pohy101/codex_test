from __future__ import annotations

from io import BytesIO

import aiohttp
import discord

from src.bridge.message_router import MediaItem
from src.bridge.service import BridgeService
from src.retry import retry_with_backoff


class DiscordClient(discord.Client):
    def __init__(self, *, token: str, bridge: BridgeService) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._token = token
        self._bridge = bridge

    async def on_ready(self) -> None:
        return

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
        reply_to_message_id = str(message.reference.message_id) if message.reference and message.reference.message_id else None

        if message.reference and message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
            ref = message.reference.resolved
            reply_to_author = ref.author.display_name
            reply_to_text = ref.content
        elif message.reference and message.reference.message_id:
            try:
                fetched = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                fetched = None
            if fetched is not None:
                reply_to_author = fetched.author.display_name
                reply_to_text = fetched.content

        media_items = [
            MediaItem(
                kind=self._kind_from_attachment(attachment),
                url=attachment.url,
                mime_type=attachment.content_type,
                filename=attachment.filename,
                file_size=attachment.size,
            )
            for attachment in message.attachments
        ]
        media_items.extend(
            MediaItem(kind="sticker", url=str(sticker.url), filename=f"sticker_{sticker.id}.png")
            for sticker in message.stickers
        )

        await self._bridge.handle_discord_message(
            content=message.content,
            author_name=message.author.display_name,
            author_id=str(message.author.id),
            is_bot=message.author.bot,
            channel_id=channel_id,
            thread_id=thread_id,
            message_id=str(message.id),
            media_items=media_items,
            reply_to_author=reply_to_author,
            reply_to_text=reply_to_text,
            reply_to_message_id=reply_to_message_id,
        )

    async def start_client(self) -> None:
        await self.start(self._token)

    async def stop_client(self) -> None:
        if not self.is_closed():
            await self.close()

    async def send_message(
        self,
        channel_id: int,
        text: str,
        *,
        reference_message_id: str | None = None,
    ) -> str:
        channel = await self._get_messageable_channel(channel_id)
        reference = self._reference(channel_id, reference_message_id)

        sent = await retry_with_backoff(
            "discord.send_message",
            lambda: channel.send(text, reference=reference),
            is_retryable=self._is_retryable,
        )
        return str(sent.id)

    async def send_photo(self, channel_id: int, data: bytes, **kwargs: object) -> str:
        return await self._send_file(channel_id, data, default_filename="photo.jpg", **kwargs)

    async def send_video(self, channel_id: int, data: bytes, **kwargs: object) -> str:
        return await self._send_file(channel_id, data, default_filename="video.mp4", **kwargs)

    async def send_audio(self, channel_id: int, data: bytes, **kwargs: object) -> str:
        return await self._send_file(channel_id, data, default_filename="audio.mp3", **kwargs)

    async def send_voice(self, channel_id: int, data: bytes, **kwargs: object) -> str:
        return await self._send_file(channel_id, data, default_filename="voice.ogg", **kwargs)

    async def send_document(self, channel_id: int, data: bytes, **kwargs: object) -> str:
        return await self._send_file(channel_id, data, default_filename="document.bin", **kwargs)

    async def send_sticker(self, channel_id: int, data: bytes, **kwargs: object) -> str:
        return await self._send_file(channel_id, data, default_filename="sticker.webp", **kwargs)

    async def download_attachment(self, url: str) -> bytes | None:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                return await response.read()

    async def _send_file(self, channel_id: int, data: bytes, *, default_filename: str, **kwargs: object) -> str:
        channel = await self._get_messageable_channel(channel_id)
        reference = self._reference(channel_id, kwargs.get("reference_message_id"))
        filename = str(kwargs.get("filename") or default_filename)

        caption = kwargs.get("caption")

        sent = await retry_with_backoff(
            "discord.send_file",
            lambda: channel.send(
                content=caption,
                file=discord.File(fp=BytesIO(data), filename=filename),
                reference=reference,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.id)

    async def _get_messageable_channel(self, channel_id: int) -> discord.abc.Messageable:
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)

        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("Configured Discord channel is not messageable")
        return channel

    @staticmethod
    def _reference(channel_id: int, reference_message_id: object) -> discord.MessageReference | None:
        if reference_message_id is None:
            return None
        return discord.MessageReference(
            message_id=int(reference_message_id),
            channel_id=channel_id,
            fail_if_not_exists=False,
        )

    @staticmethod
    def _kind_from_attachment(attachment: discord.Attachment) -> str:
        content_type = (attachment.content_type or "").lower()
        if content_type.startswith("image/"):
            if content_type == "image/gif":
                return "animation"
            return "photo"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("audio/"):
            return "audio"
        return "document"

    @staticmethod
    def _is_retryable(exc: Exception) -> tuple[bool, int | None]:
        if isinstance(exc, discord.HTTPException):
            status_code = exc.status
            return status_code in {429, 500, 502, 503, 504}, status_code
        return False, None
