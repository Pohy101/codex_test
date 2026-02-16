from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.bridge.service import BridgeService


class TelegramClient:
    def __init__(self, *, token: str, chat_id: int, bridge: BridgeService) -> None:
        self._chat_id = chat_id
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
            if message.chat.id != self._chat_id:
                return
            if message.from_user is None or message.from_user.is_bot:
                return
            if message.text is None:
                return

            author = message.from_user.full_name or str(message.from_user.id)
            await self._bridge.handle_telegram_message(
                content=message.text,
                author_name=author,
                chat_id=message.chat.id,
            )

    async def start_client(self) -> None:
        await self._dispatcher.start_polling(self._bot)

    async def stop_client(self) -> None:
        await self._bot.session.close()

    async def send_message(self, text: str) -> None:
        await self._bot.send_message(chat_id=self._chat_id, text=text)
