from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

import redis

from app.config import get_settings

SERVICE_LIMITS = {
    "seedance": 2,
    "seedream": 5,
    "doubao": 10,
    "kling": 2,
}

LOAD_TTL_SECONDS = 60 * 60


class KeyPoolError(RuntimeError):
    """Base key-pool error."""


class BackpressureError(KeyPoolError):
    """Raised when every key is saturated or cooling down."""


@dataclass(frozen=True, slots=True)
class KeyRecord:
    service: str
    name: str
    api_key: str
    max_concurrency: int


class KeyPool:
    # 同步实现，仅供 Celery worker（同步上下文）调用。
    # 不要在 async 路由或 async 函数中直接调用，Redis 操作会阻塞事件循环。
    def __init__(self) -> None:
        self._lock = RLock()
        self._redis_url: str | None = None
        self._redis: redis.Redis | None = None

    def acquire(self, service: str) -> tuple[str, str]:
        records = self._load_key_records(service)
        if not records:
            raise BackpressureError(f"No API keys configured for service '{service}'.")

        client = self._redis_client()
        ranked: list[tuple[int, KeyRecord]] = []

        for record in records:
            if client.exists(self._cooldown_key(record)):
                continue
            load = int(client.get(self._load_key(record)) or 0)
            ranked.append((load, record))

        if not ranked:
            raise BackpressureError(f"Service '{service}' has no available key right now.")

        for _, record in sorted(ranked, key=lambda item: (item[0], item[1].name)):
            pipe = client.pipeline()
            pipe.incr(self._load_key(record))
            pipe.expire(self._load_key(record), LOAD_TTL_SECONDS)
            pipe.incr(self._rpm_key(record))
            pipe.expire(self._rpm_key(record), 60)
            new_load, _, _, _ = pipe.execute()
            if int(new_load) <= record.max_concurrency:
                return record.name, record.api_key
            client.decr(self._load_key(record))

        raise BackpressureError(f"Service '{service}' is saturated across all configured keys.")

    def release(self, key_name: str) -> None:
        record = self._find_record(key_name)
        if record is None:
            return

        client = self._redis_client()
        new_value = client.decr(self._load_key(record))
        if int(new_value) < 0:
            client.set(self._load_key(record), 0)

    def report_error(self, key_name: str, error_type: str) -> None:
        record = self._find_record(key_name)
        if record is None:
            return

        lowered = error_type.lower()
        cooldown_seconds = 0
        auth_error = (
            "401" in lowered
            or "unauthorized" in lowered
            or "forbidden" in lowered
            or "403" in lowered
            or "invalid api key" in lowered
            or "invalid token" in lowered
            or "authentication" in lowered
        )
        parameter_error = "invalidparameter" in lowered or "invalid parameter" in lowered or "parameter `" in lowered
        if auth_error and not parameter_error:
            cooldown_seconds = 600
        elif "429" in lowered or "rate" in lowered or "quota" in lowered:
            cooldown_seconds = 60
        elif "500" in lowered or "timeout" in lowered or "connection" in lowered:
            cooldown_seconds = 30

        if not cooldown_seconds:
            # saturated/backpressure: release the load so the key is not stuck
            self.release(record.name)

        client = self._redis_client()
        burst_key = self._error_burst_key(record)
        burst_count = int(client.incr(burst_key))
        client.expire(burst_key, 300)
        if burst_count >= 3:
            cooldown_seconds = max(cooldown_seconds, 300)

        if cooldown_seconds > 0:
            client.setex(self._cooldown_key(record), cooldown_seconds, "1")

    def snapshot(self, service: str | None = None) -> dict[str, list[dict[str, Any]]]:
        services = [service] if service else sorted(SERVICE_LIMITS)
        client = self._redis_client()
        data: dict[str, list[dict[str, Any]]] = {}
        for service_name in services:
            rows: list[dict[str, Any]] = []
            for record in self._load_key_records(service_name):
                rows.append(
                    {
                        "name": record.name,
                        "load": int(client.get(self._load_key(record)) or 0),
                        "rpm": int(client.get(self._rpm_key(record)) or 0),
                        "cooldown_ttl": int(client.ttl(self._cooldown_key(record)) or 0),
                        "max_concurrency": record.max_concurrency,
                    }
                )
            data[service_name] = rows
        return data

    def _redis_client(self) -> redis.Redis:
        with self._lock:
            settings = self._reload_settings()
            if self._redis is None or self._redis_url != settings.redis_url:
                self._redis_url = settings.redis_url
                self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            return self._redis

    def _reload_settings(self):
        if hasattr(get_settings, "cache_clear"):
            get_settings.cache_clear()
        return get_settings()

    def _load_key_records(self, service: str) -> list[KeyRecord]:
        settings = self._reload_settings()
        raw_keys = self._service_keys(settings, service)
        limit = SERVICE_LIMITS.get(service, 1)
        return [
            KeyRecord(
                service=service,
                name=f"{service}_{index}",
                api_key=api_key,
                max_concurrency=limit,
            )
            for index, api_key in enumerate(raw_keys, start=1)
            if api_key
        ]

    def _service_keys(self, settings: Any, service: str) -> list[str]:
        attr_map = {
            "seedance": ("seedance_api_keys", "ark_api_key_list"),
            "seedream": ("seedream_api_keys", "ark_api_key_list"),
            "doubao": ("doubao_api_keys", "ark_api_key_list"),
            "kling": ("kling_api_key_list",),
        }
        for attr_name in attr_map.get(service, ("ark_api_key_list",)):
            value = getattr(settings, attr_name, None)
            if isinstance(value, list) and value:
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str) and value.strip():
                return [item.strip() for item in value.split(",") if item.strip()]
        return []

    def _find_record(self, key_name: str) -> KeyRecord | None:
        for service in SERVICE_LIMITS:
            for record in self._load_key_records(service):
                if record.name == key_name:
                    return record
        return None

    @staticmethod
    def _load_key(record: KeyRecord) -> str:
        return f"ark_key:{record.service}:{record.name}:load"

    @staticmethod
    def _cooldown_key(record: KeyRecord) -> str:
        return f"ark_key:{record.service}:{record.name}:cooldown"

    @staticmethod
    def _rpm_key(record: KeyRecord) -> str:
        return f"ark_key:{record.service}:{record.name}:rpm"

    @staticmethod
    def _error_burst_key(record: KeyRecord) -> str:
        return f"ark_key:{record.service}:{record.name}:error_burst"


key_pool = KeyPool()
