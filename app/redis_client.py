import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff

from app.config import get_settings


settings = get_settings()

REDIS_CLIENT_OPTIONS = dict(
    max_connections=50,
    socket_connect_timeout=5,
    socket_timeout=10,
    retry_on_timeout=True,
    retry=Retry(backoff=ExponentialBackoff(cap=2, base=0.5), retries=3),
    health_check_interval=30,
)

redis_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    decode_responses=True,
    **REDIS_CLIENT_OPTIONS,
)

redis_client = aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> aioredis.Redis:
    return redis_client


def make_redis_client() -> aioredis.Redis:
    return aioredis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        **REDIS_CLIENT_OPTIONS,
    )
