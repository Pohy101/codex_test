from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


class BaseDedupStore:
    async def seen_or_add(self, key: str) -> bool:
        raise NotImplementedError


@dataclass
class InMemoryDedupStore(BaseDedupStore):
    ttl_seconds: int = 300

    def __post_init__(self) -> None:
        self._cache: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def seen_or_add(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            self._purge_expired(now)
            expires_at = self._cache.get(key)
            if expires_at and expires_at > now:
                return True

            self._cache[key] = now + self.ttl_seconds
            return False

    def _purge_expired(self, now: float) -> None:
        expired = [cache_key for cache_key, exp in self._cache.items() if exp <= now]
        for cache_key in expired:
            self._cache.pop(cache_key, None)


class RedisDedupStore(BaseDedupStore):
    def __init__(self, *, redis_url: str, ttl_seconds: int = 300, namespace: str = "bridge:dedup") -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("redis package is required for RedisDedupStore") from exc

        self._redis_cls = Redis
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._namespace = namespace
        self._client: Redis | None = None

    async def _get_client(self):
        if self._client is None:
            self._client = self._redis_cls.from_url(self._redis_url, encoding="utf-8", decode_responses=True)
        return self._client

    async def seen_or_add(self, key: str) -> bool:
        client = await self._get_client()
        namespaced_key = f"{self._namespace}:{key}"
        created = await client.set(namespaced_key, "1", ex=self._ttl_seconds, nx=True)
        return not bool(created)


class CompositeDedupStore(BaseDedupStore):
    def __init__(self, stores: tuple[BaseDedupStore, ...]) -> None:
        self._stores = stores

    async def seen_or_add(self, key: str) -> bool:
        seen = False
        for store in self._stores:
            seen = await store.seen_or_add(key) or seen
        return seen
