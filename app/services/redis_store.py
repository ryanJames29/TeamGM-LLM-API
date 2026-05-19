import json
import logging

from redis.asyncio import Redis

from app.config import Settings
from app.types import JsonObject, JsonValue

logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def connect_redis(settings: Settings) -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await _redis.ping()
        logger.info("Connected to Redis at %s", settings.redis_url)
    return _redis


async def disconnect_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Disconnected from Redis")


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis is not connected. Start the API with ENABLE_NHL_JOBS=true.")
    return _redis


async def redis_get_json(key: str) -> JsonValue | None:
    raw = await get_redis().get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def safe_redis_get_json(key: str) -> JsonValue | None:
    try:
        return await redis_get_json(key)
    except RuntimeError:
        return None


async def safe_redis_hlen(hash_key: str) -> int | None:
    try:
        return int(await get_redis().hlen(hash_key))
    except (RuntimeError, TypeError, ValueError):
        return None


async def redis_set_json(key: str, value: JsonValue, *, ttl_seconds: int | None = None) -> None:
    payload = json.dumps(value, default=str)
    if ttl_seconds is not None:
        await get_redis().set(key, payload, ex=ttl_seconds)
    else:
        await get_redis().set(key, payload)


async def redis_hset_json(hash_key: str, field: str, value: JsonValue) -> None:
    await get_redis().hset(hash_key, field, json.dumps(value, default=str))


async def redis_hget_json(hash_key: str, field: str) -> JsonValue | None:
    raw = await get_redis().hget(hash_key, field)
    if raw is None:
        return None
    return json.loads(raw)


async def redis_hgetall_json(hash_key: str) -> dict[str, JsonValue]:
    raw_map = await get_redis().hgetall(hash_key)
    result: dict[str, JsonValue] = {}
    for field, raw in raw_map.items():
        result[field] = json.loads(raw)
    return result


async def redis_hmset_json(hash_key: str, mapping: dict[str, JsonObject]) -> None:
    if not mapping:
        return
    encoded = {k: json.dumps(v, default=str) for k, v in mapping.items()}
    await get_redis().hset(hash_key, mapping=encoded)


async def redis_replace_hash_json(hash_key: str, mapping: dict[str, JsonObject]) -> None:
    redis = get_redis()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(hash_key)
        if mapping:
            encoded = {k: json.dumps(v, default=str) for k, v in mapping.items()}
            pipe.hset(hash_key, mapping=encoded)
        await pipe.execute()
