"""Key Pool capacity visibility for the API layer.

Bridges the gap between API-level rate limiting and worker-level Key Pool
concurrency, so the dispatch layer knows downstream capacity before queuing tasks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.key_pool import key_pool, SERVICE_LIMITS

logger = logging.getLogger(__name__)

# Provider arg → Key Pool service name
PROVIDER_TO_SERVICE: dict[str, str] = {
    "seedance": "seedance",
    "seedream": "seedream",
    "kling": "kling",
    "doubao": "doubao",
}


@dataclass(frozen=True)
class CapacityStatus:
    service: str
    total_concurrency: int
    available_slots: int
    used_slots: int
    cooldown_keys: list[str]
    estimated_wait_sec: int
    key_details: list[dict] = field(default_factory=list)


def check_capacity_sync(provider: str) -> CapacityStatus:
    """Synchronous wrapper for Celery task context."""
    service = PROVIDER_TO_SERVICE.get(provider, provider)
    snapshot = key_pool.snapshot(service)
    return _build_status(service, snapshot)


def _build_status(service: str, snapshot_data: dict) -> CapacityStatus:
    rows = snapshot_data.get(service, [])
    if not rows:
        return CapacityStatus(
            service=service,
            total_concurrency=0,
            available_slots=0,
            used_slots=0,
            cooldown_keys=[],
            estimated_wait_sec=0,
        )

    total = sum(r["max_concurrency"] for r in rows)
    used = sum(r["load"] for r in rows)
    available = max(0, total - used)
    cooldown = [r["name"] for r in rows if r.get("cooldown_ttl", 0) > 0]

    # Estimate wait: if a key is in cooldown, use its TTL; otherwise
    # use avg task duration (60s for video, 15s for image) × queue depth
    avg_task_sec = _avg_task_duration(service)
    wait = 0
    if available == 0 and used > 0:
        # All slots busy — estimate based on avg task duration
        wait = avg_task_sec
    if cooldown:
        cooldown_ttls = [r.get("cooldown_ttl", 0) for r in rows if r.get("cooldown_ttl", 0) > 0]
        if cooldown_ttls:
            wait = max(wait, max(cooldown_ttls))

    return CapacityStatus(
        service=service,
        total_concurrency=total,
        available_slots=available,
        used_slots=used,
        cooldown_keys=cooldown,
        estimated_wait_sec=wait,
        key_details=rows,
    )


def _avg_task_duration(service: str) -> int:
    return {
        "seedance": 90,
        "kling": 90,
        "seedream": 20,
        "doubao": 10,
    }.get(service, 30)
