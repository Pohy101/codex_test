from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from src.config import BridgePair


@dataclass(frozen=True)
class StoredBridgePair:
    id: str
    discord_channel_id: int
    telegram_chat_id: int

    def to_bridge_pair(self) -> BridgePair:
        return BridgePair(
            discord_channel_id=self.discord_channel_id,
            telegram_chat_id=self.telegram_chat_id,
        )


class BridgePairStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load(self) -> list[StoredBridgePair]:
        if not self._path.exists():
            return []

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Bridge pair store must contain a JSON array")

        pairs: list[StoredBridgePair] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"Bridge pair at index {idx} must be an object")
            try:
                pair_id = str(item["id"])
                discord_channel_id = int(item["discord_channel_id"])
                telegram_chat_id = int(item["telegram_chat_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Bridge pair at index {idx} has invalid schema") from exc
            pairs.append(
                StoredBridgePair(
                    id=pair_id,
                    discord_channel_id=discord_channel_id,
                    telegram_chat_id=telegram_chat_id,
                )
            )
        return pairs

    def save(self, pairs: list[StoredBridgePair]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "id": pair.id,
                "discord_channel_id": pair.discord_channel_id,
                "telegram_chat_id": pair.telegram_chat_id,
            }
            for pair in pairs
        ]
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def initialize(self, fallback_pairs: tuple[BridgePair, ...]) -> list[StoredBridgePair]:
        pairs = self.load()
        if pairs:
            return pairs

        pairs = [
            StoredBridgePair(
                id=str(uuid4()),
                discord_channel_id=pair.discord_channel_id,
                telegram_chat_id=pair.telegram_chat_id,
            )
            for pair in fallback_pairs
        ]
        self.save(pairs)
        return pairs
