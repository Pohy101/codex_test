from __future__ import annotations

from io import BytesIO
from typing import Sequence

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message, ReplyParameters

from src.bridge.message_router import MediaItem
from src.bridge.service import BridgeService
from src.retry import retry_with_backoff


def _entity_text(source_text: str, *, offset: int, length: int) -> str:
    if length <= 0:
        return ""
    return source_text[offset : offset + length]


def extract_telegram_media_items(message: Message) -> list[MediaItem]:
    media_items: list[MediaItem] = []

    if message.audio:
        media_items.append(
            MediaItem(
                kind="audio",
                platform_file_id=message.audio.file_id,
                platform_file_unique_id=message.audio.file_unique_id,
                filename=message.audio.file_name,
                mime_type=message.audio.mime_type,
                duration=message.audio.duration,
                file_size=message.audio.file_size,
                caption=message.caption,
            )
        )

    if message.voice:
        media_items.append(
            MediaItem(
                kind="voice",
                platform_file_id=message.voice.file_id,
                platform_file_unique_id=message.voice.file_unique_id,
                filename=f"voice_{message.voice.file_unique_id}.ogg",
                mime_type=message.voice.mime_type,
                duration=message.voice.duration,
                file_size=message.voice.file_size,
                caption=message.caption,
            )
        )

    if message.sticker:
        sticker_extension = "tgs" if message.sticker.is_animated else "webm" if message.sticker.is_video else "webp"
        media_items.append(
            MediaItem(
                kind="sticker",
                platform_file_id=message.sticker.file_id,
                platform_file_unique_id=message.sticker.file_unique_id,
                filename=f"sticker_{message.sticker.file_unique_id}.{sticker_extension}",
                mime_type=message.sticker.mime_type,
                file_size=message.sticker.file_size,
                emoji=message.sticker.emoji,
                set_name=message.sticker.set_name,
                is_animated=message.sticker.is_animated,
                is_video=message.sticker.is_video,
            )
        )

    if message.animation:
        media_items.append(
            MediaItem(
                kind="animation",
                platform_file_id=message.animation.file_id,
                platform_file_unique_id=message.animation.file_unique_id,
                filename=message.animation.file_name,
                mime_type=message.animation.mime_type,
                duration=message.animation.duration,
                file_size=message.animation.file_size,
                caption=message.caption,
            )
        )

    if message.video_note:
        media_items.append(
            MediaItem(
                kind="video_note",
                platform_file_id=message.video_note.file_id,
                platform_file_unique_id=message.video_note.file_unique_id,
                filename=f"video_note_{message.video_note.file_unique_id}.mp4",
                mime_type="video/mp4",
                duration=message.video_note.duration,
                file_size=message.video_note.file_size,
            )
        )

    if message.photo:
        largest_photo = message.photo[-1]
        media_items.append(
            MediaItem(
                kind="photo",
                platform_file_id=largest_photo.file_id,
                platform_file_unique_id=largest_photo.file_unique_id,
                filename=f"photo_{largest_photo.file_unique_id}.jpg",
                mime_type="image/jpeg",
                file_size=largest_photo.file_size,
                caption=message.caption,
            )
        )

    if message.video:
        media_items.append(
            MediaItem(
                kind="video",
                platform_file_id=message.video.file_id,
                platform_file_unique_id=message.video.file_unique_id,
                filename=message.video.file_name or f"video_{message.video.file_unique_id}.mp4",
                mime_type=message.video.mime_type,
                duration=message.video.duration,
                file_size=message.video.file_size,
                caption=message.caption,
            )
        )

    if message.document:
        media_items.append(
            MediaItem(
                kind="document",
                platform_file_id=message.document.file_id,
                platform_file_unique_id=message.document.file_unique_id,
                filename=message.document.file_name,
                mime_type=message.document.mime_type,
                file_size=message.document.file_size,
                caption=message.caption,
            )
        )

    rich_text = message.text or message.caption or ""
    rich_entities = list(message.entities or []) + list(message.caption_entities or [])
    for entity in rich_entities:
        if str(entity.type) != "custom_emoji":
            continue
        emoji_text = _entity_text(rich_text, offset=entity.offset, length=entity.length) or "[custom emoji]"
        media_items.append(
            MediaItem(
                kind="custom_emoji",
                custom_emoji_id=entity.custom_emoji_id,
                emoji=emoji_text,
                text_fallback=f"Custom emoji {emoji_text} (id: {entity.custom_emoji_id})",
            )
        )

    for reaction in _extract_reactions(message):
        media_items.append(
            MediaItem(
                kind="reaction",
                emoji=reaction,
                text_fallback=f"Reaction: {reaction}",
            )
        )

    return media_items


def _extract_reactions(message: Message) -> list[str]:
    values: list[str] = []
    raw_reactions = getattr(message, "reactions", None) or getattr(message, "reaction", None)
    if not raw_reactions:
        return values
    for item in raw_reactions:
        emoji = getattr(item, "emoji", None)
        if emoji:
            values.append(str(emoji))
    return values


def render_telegram_fallback_text(media_items: Sequence[MediaItem]) -> str:
    fallback_lines = [item.render() for item in media_items if item.platform_file_id is None and item.text_fallback]
    return "\n".join(fallback_lines).strip()


class TelegramClient:
    def __init__(self, *, token: str, bridge: BridgeService) -> None:
        self._bridge = bridge
        self._bot = Bot(token=token)
        self._dispatcher = Dispatcher()
        self._router = Router()
        self._register_handlers()
        self._dispatcher.include_router(self._router)

    def _register_handlers(self) -> None:
        @self._router.message(Command("start"))
        async def start_command(message: Message) -> None:
            await message.answer("Bridge bot is running.")

        @self._router.message()
        async def forward_message(message: Message) -> None:
            if message.from_user is None:
                return

            media_items = extract_telegram_media_items(message)
            content = (message.text or message.caption or "").strip()
            fallback_text = render_telegram_fallback_text(media_items)
            if fallback_text:
                content = f"{content}\n{fallback_text}".strip()

            if not content and not media_items:
                return

            reply_to_author = None
            reply_to_text = None
            reply_to_message_id = None
            if message.reply_to_message:
                reply_to_message_id = str(message.reply_to_message.message_id)
                if message.reply_to_message.from_user:
                    reply_to_author = (
                        message.reply_to_message.from_user.full_name
                        or str(message.reply_to_message.from_user.id)
                    )
                reply_to_text = message.reply_to_message.text or message.reply_to_message.caption

            author = message.from_user.full_name or str(message.from_user.id)
            await self._bridge.handle_telegram_message(
                content=content,
                author_name=author,
                author_id=str(message.from_user.id),
                is_bot=message.from_user.is_bot,
                chat_id=message.chat.id,
                thread_id=message.message_thread_id,
                message_id=str(message.message_id),
                media_items=media_items,
                reply_to_author=reply_to_author,
                reply_to_text=reply_to_text,
                reply_to_message_id=reply_to_message_id,
            )

    async def start_client(self) -> None:
        await self._dispatcher.start_polling(self._bot)

    async def stop_client(self) -> None:
        await self._bot.session.close()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
        reply_to_message_id: str | None = None,
    ) -> str:
        reply_parameters = self._reply_parameters(reply_to_message_id)

        sent = await retry_with_backoff(
            "telegram.send_message",
            lambda: self._bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=message_thread_id,
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_photo(
        self,
        chat_id: int,
        data: bytes,
        *,
        filename: str | None = None,
        caption: str | None = None,
        mime_type: str | None = None,
        duration: int | None = None,
        message_thread_id: int | None = None,
        reply_to_message_id: str | None = None,
    ) -> str:
        del mime_type, duration
        input_file = self._input_file(data, filename or "photo.jpg")
        reply_parameters = self._reply_parameters(reply_to_message_id)
        sent = await retry_with_backoff(
            "telegram.send_photo",
            lambda: self._bot.send_photo(
                chat_id=chat_id,
                photo=input_file,
                caption=caption,
                message_thread_id=message_thread_id,
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_video(self, chat_id: int, data: bytes, **kwargs: object) -> str:
        input_file = self._input_file(data, str(kwargs.get("filename") or "video.mp4"))
        reply_parameters = self._reply_parameters(kwargs.get("reply_to_message_id"))
        sent = await retry_with_backoff(
            "telegram.send_video",
            lambda: self._bot.send_video(
                chat_id=chat_id,
                video=input_file,
                caption=kwargs.get("caption"),
                duration=kwargs.get("duration"),
                message_thread_id=kwargs.get("message_thread_id"),
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_video_note(self, chat_id: int, data: bytes, **kwargs: object) -> str:
        input_file = self._input_file(data, str(kwargs.get("filename") or "video_note.mp4"))
        reply_parameters = self._reply_parameters(kwargs.get("reply_to_message_id"))
        sent = await retry_with_backoff(
            "telegram.send_video_note",
            lambda: self._bot.send_video_note(
                chat_id=chat_id,
                video_note=input_file,
                duration=kwargs.get("duration"),
                message_thread_id=kwargs.get("message_thread_id"),
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_audio(self, chat_id: int, data: bytes, **kwargs: object) -> str:
        input_file = self._input_file(data, str(kwargs.get("filename") or "audio.mp3"))
        reply_parameters = self._reply_parameters(kwargs.get("reply_to_message_id"))
        sent = await retry_with_backoff(
            "telegram.send_audio",
            lambda: self._bot.send_audio(
                chat_id=chat_id,
                audio=input_file,
                caption=kwargs.get("caption"),
                duration=kwargs.get("duration"),
                message_thread_id=kwargs.get("message_thread_id"),
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_voice(self, chat_id: int, data: bytes, **kwargs: object) -> str:
        input_file = self._input_file(data, str(kwargs.get("filename") or "voice.ogg"))
        reply_parameters = self._reply_parameters(kwargs.get("reply_to_message_id"))
        sent = await retry_with_backoff(
            "telegram.send_voice",
            lambda: self._bot.send_voice(
                chat_id=chat_id,
                voice=input_file,
                caption=kwargs.get("caption"),
                duration=kwargs.get("duration"),
                message_thread_id=kwargs.get("message_thread_id"),
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_document(self, chat_id: int, data: bytes, **kwargs: object) -> str:
        input_file = self._input_file(data, str(kwargs.get("filename") or "document.bin"))
        reply_parameters = self._reply_parameters(kwargs.get("reply_to_message_id"))
        sent = await retry_with_backoff(
            "telegram.send_document",
            lambda: self._bot.send_document(
                chat_id=chat_id,
                document=input_file,
                caption=kwargs.get("caption"),
                message_thread_id=kwargs.get("message_thread_id"),
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_sticker(self, chat_id: int, data: bytes, **kwargs: object) -> str:
        input_file = self._input_file(data, str(kwargs.get("filename") or "sticker.webp"))
        reply_parameters = self._reply_parameters(kwargs.get("reply_to_message_id"))
        sent = await retry_with_backoff(
            "telegram.send_sticker",
            lambda: self._bot.send_sticker(
                chat_id=chat_id,
                sticker=input_file,
                message_thread_id=kwargs.get("message_thread_id"),
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def send_animation(self, chat_id: int, data: bytes, **kwargs: object) -> str:
        input_file = self._input_file(data, str(kwargs.get("filename") or "animation.gif"))
        reply_parameters = self._reply_parameters(kwargs.get("reply_to_message_id"))
        sent = await retry_with_backoff(
            "telegram.send_animation",
            lambda: self._bot.send_animation(
                chat_id=chat_id,
                animation=input_file,
                caption=kwargs.get("caption"),
                duration=kwargs.get("duration"),
                message_thread_id=kwargs.get("message_thread_id"),
                reply_parameters=reply_parameters,
            ),
            is_retryable=self._is_retryable,
        )
        return str(sent.message_id)

    async def download_file_by_id(self, file_id: str) -> bytes | None:
        file = await retry_with_backoff(
            "telegram.get_file",
            lambda: self._bot.get_file(file_id),
            is_retryable=self._is_retryable,
        )
        if not file.file_path:
            return None

        buffer = BytesIO()
        await retry_with_backoff(
            "telegram.download_file",
            lambda: self._bot.download_file(file.file_path, destination=buffer),
            is_retryable=self._is_retryable,
        )
        return buffer.getvalue()

    @staticmethod
    def _input_file(data: bytes, filename: str) -> BufferedInputFile:
        return BufferedInputFile(data, filename=filename)

    @staticmethod
    def _reply_parameters(reply_to_message_id: object) -> ReplyParameters | None:
        if reply_to_message_id is None:
            return None
        return ReplyParameters(message_id=int(reply_to_message_id))

    @staticmethod
    def _is_retryable(exc: Exception) -> tuple[bool, int | None]:
        if isinstance(exc, TelegramRetryAfter):
            return True, 429
        if isinstance(exc, TelegramServerError):
            return True, 500
        if isinstance(exc, TelegramNetworkError):
            return True, 503
        return False, None
