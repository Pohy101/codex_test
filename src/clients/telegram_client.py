from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.filters import Command
from aiogram.types import Message

from src.bridge.message_router import MessageAttachment
from src.bridge.service import BridgeService
from src.retry import retry_with_backoff


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

            content = (message.text or message.caption or "").strip()
            attachments: list[MessageAttachment] = []

            if message.photo:
                largest_photo = message.photo[-1]
                attachments.append(
                    MessageAttachment(
                        filename=f"photo_{largest_photo.file_unique_id}.jpg",
                        url=None,
                    )
                )
            if message.document:
                attachments.append(
                    MessageAttachment(
                        filename=message.document.file_name,
                        url=None,
                    )
                )
            if message.video:
                attachments.append(
                    MessageAttachment(
                        filename=message.video.file_name or f"video_{message.video.file_unique_id}.mp4",
                        url=None,
                    )
                )

            if not content and not attachments:
                return

            reply_to_author = None
            reply_to_text = None
            if message.reply_to_message and message.reply_to_message.from_user:
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
                attachments=attachments,
                reply_to_author=reply_to_author,
                reply_to_text=reply_to_text,
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
    ) -> None:
        def _is_retryable(exc: Exception) -> tuple[bool, int | None]:
            if isinstance(exc, TelegramRetryAfter):
                return True, 429
            if isinstance(exc, TelegramServerError):
                return True, 500
            if isinstance(exc, TelegramNetworkError):
                return True, 503
            return False, None

        await retry_with_backoff(
            "telegram.send_message",
            lambda: self._bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=message_thread_id,
            ),
            is_retryable=_is_retryable,
        )
