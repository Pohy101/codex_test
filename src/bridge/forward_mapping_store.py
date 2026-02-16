from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ForwardContext:
    source_platform: str
    source_chat_id: int
    source_message_id: str
    target_platform: str
    target_chat_id: int
    target_message_id: str


class BaseForwardMappingStore:
    async def get_target_message_id(
        self,
        *,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str | None:
        raise NotImplementedError

    async def save_mapping(self, context: ForwardContext) -> None:
        raise NotImplementedError


@dataclass
class InMemoryForwardMappingStore(BaseForwardMappingStore):
    ttl_seconds: int = 300

    def __post_init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def get_target_message_id(
        self,
        *,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str | None:
        now = time.monotonic()
        key = self._build_key(
            source_platform=source_platform,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            target_platform=target_platform,
            target_chat_id=target_chat_id,
        )
        async with self._lock:
            self._purge_expired(now)
            cached = self._cache.get(key)
            if not cached:
                return None
            value, expires_at = cached
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            return value

    async def save_mapping(self, context: ForwardContext) -> None:
        now = time.monotonic()
        key = self._build_key(
            source_platform=context.source_platform,
            source_chat_id=context.source_chat_id,
            source_message_id=context.source_message_id,
            target_platform=context.target_platform,
            target_chat_id=context.target_chat_id,
        )
        async with self._lock:
            self._purge_expired(now)
            self._cache[key] = (context.target_message_id, now + self.ttl_seconds)

    @staticmethod
    def _build_key(
        *,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str:
        return (
            f"{source_platform}:{source_chat_id}:{source_message_id}:"
            f"{target_platform}:{target_chat_id}"
        )

    def _purge_expired(self, now: float) -> None:
        expired = [cache_key for cache_key, (_, exp) in self._cache.items() if exp <= now]
        for cache_key in expired:
            self._cache.pop(cache_key, None)


class SQLiteForwardMappingStore(BaseForwardMappingStore):
    def __init__(self, *, db_path: str, max_items: int = 1000) -> None:
        self._db_path = Path(db_path)
        self._max_items = max_items
        self._initialized = False
        self._lock = asyncio.Lock()

    async def get_target_message_id(
        self,
        *,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str | None:
        async with self._lock:
            await self._ensure_initialized()
            return await asyncio.to_thread(
                self._get_target_message_id_sync,
                source_platform,
                source_chat_id,
                source_message_id,
                target_platform,
                target_chat_id,
            )

    async def save_mapping(self, context: ForwardContext) -> None:
        async with self._lock:
            await self._ensure_initialized()
            await asyncio.to_thread(self._save_mapping_sync, context)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        await asyncio.to_thread(self._initialize_db_sync)
        self._initialized = True

    def _initialize_db_sync(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS forward_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_platform TEXT NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    source_message_id TEXT NOT NULL,
                    target_platform TEXT NOT NULL,
                    target_chat_id INTEGER NOT NULL,
                    target_message_id TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_forward_mappings_unique
                ON forward_mappings (
                    source_platform,
                    source_chat_id,
                    source_message_id,
                    target_platform,
                    target_chat_id
                )
                """
            )

    def _get_target_message_id_sync(
        self,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT target_message_id
                FROM forward_mappings
                WHERE source_platform = ?
                  AND source_chat_id = ?
                  AND source_message_id = ?
                  AND target_platform = ?
                  AND target_chat_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    source_platform,
                    source_chat_id,
                    source_message_id,
                    target_platform,
                    target_chat_id,
                ),
            ).fetchone()
        return str(row[0]) if row else None

    def _save_mapping_sync(self, context: ForwardContext) -> None:
        now_ts = int(time.time())
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO forward_mappings (
                    source_platform,
                    source_chat_id,
                    source_message_id,
                    target_platform,
                    target_chat_id,
                    target_message_id,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    source_platform,
                    source_chat_id,
                    source_message_id,
                    target_platform,
                    target_chat_id
                ) DO UPDATE SET
                    target_message_id = excluded.target_message_id,
                    updated_at = excluded.updated_at
                """,
                (
                    context.source_platform,
                    context.source_chat_id,
                    context.source_message_id,
                    context.target_platform,
                    context.target_chat_id,
                    context.target_message_id,
                    now_ts,
                ),
            )
            conn.execute(
                """
                DELETE FROM forward_mappings
                WHERE id NOT IN (
                    SELECT id
                    FROM forward_mappings
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (self._max_items,),
            )


class RedisForwardMappingStore(BaseForwardMappingStore):
    def __init__(
        self,
        *,
        redis_url: str,
        ttl_seconds: int = 300,
        namespace: str = "bridge:forward_map",
    ) -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("redis package is required for RedisForwardMappingStore") from exc

        self._redis_cls = Redis
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._namespace = namespace
        self._client: Redis | None = None

    async def _get_client(self):
        if self._client is None:
            self._client = self._redis_cls.from_url(self._redis_url, encoding="utf-8", decode_responses=True)
        return self._client

    async def get_target_message_id(
        self,
        *,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str | None:
        client = await self._get_client()
        key = self._build_key(
            source_platform=source_platform,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            target_platform=target_platform,
            target_chat_id=target_chat_id,
        )
        return await client.get(key)

    async def save_mapping(self, context: ForwardContext) -> None:
        client = await self._get_client()
        key = self._build_key(
            source_platform=context.source_platform,
            source_chat_id=context.source_chat_id,
            source_message_id=context.source_message_id,
            target_platform=context.target_platform,
            target_chat_id=context.target_chat_id,
        )
        await client.set(key, context.target_message_id, ex=self._ttl_seconds)

    def _build_key(
        self,
        *,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str:
        return (
            f"{self._namespace}:{source_platform}:{source_chat_id}:{source_message_id}:"
            f"{target_platform}:{target_chat_id}"
        )


class CompositeForwardMappingStore(BaseForwardMappingStore):
    def __init__(self, stores: tuple[BaseForwardMappingStore, ...]) -> None:
        self._stores = stores

    async def get_target_message_id(
        self,
        *,
        source_platform: str,
        source_chat_id: int,
        source_message_id: str,
        target_platform: str,
        target_chat_id: int,
    ) -> str | None:
        for store in self._stores:
            found = await store.get_target_message_id(
                source_platform=source_platform,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                target_platform=target_platform,
                target_chat_id=target_chat_id,
            )
            if found:
                return found
        return None

    async def save_mapping(self, context: ForwardContext) -> None:
        for store in self._stores:
            await store.save_mapping(context)
