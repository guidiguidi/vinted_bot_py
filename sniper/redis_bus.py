"""
sniper/redis_bus.py — Redis Pub/Sub шина данных для AntiGravity Sniper.

Канал: ag:snipe
Формат payload: JSON с полями item_id, price, currency, title, url, photo_url,
                target_user_id, query_id, ts_found.

Предоставляет как async (для sniper), так и sync (для парсера) интерфейсы.
"""

import json
import time
from typing import AsyncIterator, Optional

from logger import get_logger

logger = get_logger(__name__)

CHANNEL = "ag:snipe"
REDIS_URL = "redis://localhost:6379/0"

# ---------------------------------------------------------------------------
# Async interface (for sniper daemon)
# ---------------------------------------------------------------------------

_async_redis = None


async def _get_async_redis():
    """Lazy-init async Redis connection."""
    global _async_redis
    if _async_redis is None:
        import redis.asyncio as aioredis

        _async_redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _async_redis


async def publish_snipe_trigger(payload: dict) -> bool:
    """Publish a snipe trigger to Redis (async version)."""
    try:
        r = await _get_async_redis()
        msg = json.dumps(payload, ensure_ascii=False)
        await r.publish(CHANNEL, msg)
        logger.debug(f"[Redis] Published to {CHANNEL}: item_id={payload.get('item_id')}")
        return True
    except Exception as e:
        logger.warning(f"[Redis] Async publish failed: {e}")
        return False


async def subscribe_snipe_triggers() -> AsyncIterator[dict]:
    """
    Subscribe to snipe triggers from Redis.
    Yields parsed JSON payloads as dicts.
    Reconnects automatically on errors.
    """
    while True:
        try:
            r = await _get_async_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(CHANNEL)
            logger.info(f"[Redis] Subscribed to channel: {CHANNEL}")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    yield data
                except json.JSONDecodeError as e:
                    logger.warning(f"[Redis] Bad JSON in message: {e}")
                    continue

        except Exception as e:
            logger.error(f"[Redis] Subscriber error, reconnecting in 2s: {e}")
            _reset_async_redis()
            import asyncio

            await asyncio.sleep(2)


def _reset_async_redis():
    """Reset the async Redis connection so it reconnects on next use."""
    global _async_redis
    _async_redis = None


# ---------------------------------------------------------------------------
# Sync interface (for parser process — core.py runs in a separate process)
# ---------------------------------------------------------------------------

_sync_redis = None


def _get_sync_redis():
    """Lazy-init sync Redis connection."""
    global _sync_redis
    if _sync_redis is None:
        import redis

        _sync_redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _sync_redis


def publish_snipe_trigger_sync(payload: dict) -> bool:
    """
    Publish a snipe trigger to Redis (sync version).
    Used by the parser (core.py) which runs in a multiprocessing.Process.
    """
    try:
        r = _get_sync_redis()
        msg = json.dumps(payload, ensure_ascii=False)
        r.publish(CHANNEL, msg)
        logger.debug(f"[Redis] Sync published to {CHANNEL}: item_id={payload.get('item_id')}")
        return True
    except Exception as e:
        logger.warning(f"[Redis] Sync publish failed (non-fatal): {e}")
        return False


def is_redis_available() -> bool:
    """Check if Redis is reachable. Non-blocking, returns False on any error."""
    try:
        r = _get_sync_redis()
        return r.ping()
    except Exception:
        return False
