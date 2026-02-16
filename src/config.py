from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from src.bridge.rules import ForwardingRules


class ConfigError(ValueError):
    """Raised when required environment variables are missing or invalid."""


@dataclass(frozen=True)
class BridgePair:
    discord_channel_id: int
    telegram_chat_id: int


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    telegram_bot_token: str
    bridge_pairs: tuple[BridgePair, ...]
    forwarding_rules: ForwardingRules


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


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ConfigError(f"Environment variable {name} must be a boolean")


def _parse_json_env(name: str, fallback: object) -> object:
    value = os.getenv(name)
    if value is None:
        return fallback

    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Environment variable {name} must contain valid JSON") from exc


def _parse_bridge_pairs() -> tuple[BridgePair, ...]:
    raw_pairs = _parse_json_env("BRIDGE_PAIRS", None)
    if raw_pairs is None:
        return (
            BridgePair(
                discord_channel_id=_require_int("DISCORD_CHANNEL_ID"),
                telegram_chat_id=_require_int("TELEGRAM_CHAT_ID"),
            ),
        )

    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ConfigError("Environment variable BRIDGE_PAIRS must be a non-empty JSON array")

    pairs: list[BridgePair] = []
    for idx, item in enumerate(raw_pairs):
        if not isinstance(item, dict):
            raise ConfigError(f"BRIDGE_PAIRS[{idx}] must be an object")

        try:
            discord_channel_id = int(item["discord_channel_id"])
            telegram_chat_id = int(item["telegram_chat_id"])
        except KeyError as exc:
            raise ConfigError(
                f"BRIDGE_PAIRS[{idx}] must include discord_channel_id and telegram_chat_id"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"BRIDGE_PAIRS[{idx}] discord_channel_id and telegram_chat_id must be integers"
            ) from exc

        pairs.append(
            BridgePair(
                discord_channel_id=discord_channel_id,
                telegram_chat_id=telegram_chat_id,
            )
        )

    return tuple(pairs)


def _parse_forwarding_rules() -> ForwardingRules:
    whitelist_raw = _parse_json_env("WHITELIST_USERS", [])
    blacklist_raw = _parse_json_env("BLACKLIST_USERS", [])
    excluded_commands_raw = _parse_json_env("EXCLUDED_COMMANDS", ["/start", "!admin"])

    if not isinstance(whitelist_raw, list) or not all(isinstance(item, (str, int)) for item in whitelist_raw):
        raise ConfigError("WHITELIST_USERS must be a JSON array of strings or numbers")
    if not isinstance(blacklist_raw, list) or not all(isinstance(item, (str, int)) for item in blacklist_raw):
        raise ConfigError("BLACKLIST_USERS must be a JSON array of strings or numbers")
    if not isinstance(excluded_commands_raw, list) or not all(isinstance(item, str) for item in excluded_commands_raw):
        raise ConfigError("EXCLUDED_COMMANDS must be a JSON array of strings")

    whitelist_users = frozenset(str(item).strip() for item in whitelist_raw if str(item).strip())
    blacklist_users = frozenset(str(item).strip() for item in blacklist_raw if str(item).strip())
    excluded_commands = tuple(item.strip() for item in excluded_commands_raw if item.strip())

    return ForwardingRules(
        whitelist_users=whitelist_users,
        blacklist_users=blacklist_users,
        excluded_commands=excluded_commands,
        ignore_bots=_parse_bool_env("IGNORE_BOTS", True),
    )


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        discord_bot_token=_require_env("DISCORD_BOT_TOKEN"),
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        bridge_pairs=_parse_bridge_pairs(),
        forwarding_rules=_parse_forwarding_rules(),
    )
