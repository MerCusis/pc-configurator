"""Общий асинхронный клиент Redis (кэш, лимиты, сессии)."""
import logging

from redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)


async def check_redis() -> bool:
    try:
        return bool(await redis_client.ping())
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False
