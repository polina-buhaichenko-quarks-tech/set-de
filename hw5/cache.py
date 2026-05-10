"""
Redis read-through cache helpers.

The client is created lazily on first use so the module can be imported
without a live Redis connection (useful for tests).
"""
import json
import os

import redis

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True,
        )
    return _client


def get_cached(key: str) -> dict | None:
    raw = _get_client().get(key)
    return json.loads(raw) if raw else None


def set_cached(key: str, data: dict, ttl: int) -> None:
    _get_client().setex(key, ttl, json.dumps(data))