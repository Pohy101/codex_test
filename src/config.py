from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required environment variables are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    telegram_bot_token: str
    discord_channel_id: int
    telegram_chat_id: int



def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Environment variable {name} is required")
    return value



def _require_int(name: str) -> int:
    raw = _require_env(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer") from exc



def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        discord_bot_token=_require_env("DISCORD_BOT_TOKEN"),
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        discord_channel_id=_require_int("DISCORD_CHANNEL_ID"),
        telegram_chat_id=_require_int("TELEGRAM_CHAT_ID"),
    )
