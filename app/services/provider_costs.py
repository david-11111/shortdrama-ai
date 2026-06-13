from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.db import AsyncSessionLocal

LOGGER = logging.getLogger(__name__)


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def extract_billing_usage(result: Any) -> list[dict[str, Any]]:
    """Extract provider billing_usage records from nested task results."""
    records: list[dict[str, Any]] = []
    if isinstance(result, dict):
        usage = result.get("billing_usage")
        if isinstance(usage, dict):
            enriched = dict(usage)
            if result.get("task_id"):
                enriched.setdefault("provider_task_id", result.get("task_id"))
            if result.get("provider_order_no"):
                enriched.setdefault("provider_order_no", result.get("provider_order_no"))
            records.append(enriched)
        elif isinstance(usage, list):
            records.extend(item for item in usage if isinstance(item, dict))
        for value in result.values():
            records.extend(extract_billing_usage(value))
    elif isinstance(result, list):
        for item in result:
            records.extend(extract_billing_usage(item))
    return records


def record_provider_usage(
    *,
    task_id: str,
    user_id: str | int | None = None,
    result: Any,
    project_id: str | None = None,
    credits_charged: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    records = extract_billing_usage(result)
    if not records:
        return
    try:
        asyncio.run(_record_many(
            task_id=task_id,
            user_id=user_id,
            project_id=project_id,
            records=records,
            credits_charged=credits_charged,
            metadata=metadata or {},
        ))
    except Exception as exc:
        LOGGER.warning("Provider usage ledger write failed for task %s: %s", task_id, exc)


async def _record_many(
    *,
    task_id: str,
    user_id: str | int,
    project_id: str | None,
    records: list[dict[str, Any]],
    credits_charged: int | None,
    metadata: dict[str, Any],
) -> None:
    user_pk = int(user_id) if user_id is not None and str(user_id).isdigit() else None
    async with AsyncSessionLocal() as session:
        async with session.begin():
            task_meta = await _load_task_meta(session, task_id) if user_pk is None or not project_id else {}
            user_pk = user_pk or task_meta.get("user_id")
            project_id = project_id or task_meta.get("project_id")
            for record in records:
                estimate = await _estimate_cost(session, record)
                await session.execute(
                    text(
                        """
                        INSERT INTO provider_usage_costs (
                            task_id, user_id, project_id,
                            provider, service, model, billing_basis,
                            provider_task_id, provider_order_no,
                            input_usage, output_usage, total_usage, raw_usage,
                            unit_prices, estimated_cost_yuan, match_status,
                            credits_charged, metadata
                        )
                        VALUES (
                            CAST(:task_id AS uuid), :user_id, :project_id,
                            :provider, :service, :model, :billing_basis,
                            :provider_task_id, :provider_order_no,
                            CAST(:input_usage AS JSONB),
                            CAST(:output_usage AS JSONB),
                            CAST(:total_usage AS JSONB),
                            CAST(:raw_usage AS JSONB),
                            CAST(:unit_prices AS JSONB),
                            :estimated_cost_yuan, :match_status,
                            :credits_charged, CAST(:metadata AS JSONB)
                        )
                        """
                    ),
                    {
                        "task_id": task_id,
                        "user_id": user_pk,
                        "project_id": project_id,
                        "provider": str(record.get("provider") or "unknown"),
                        "service": str(record.get("service") or "unknown"),
                        "model": str(record.get("model") or "unknown"),
                        "billing_basis": str(record.get("billing_basis") or "unknown"),
                        "provider_task_id": record.get("provider_task_id"),
                        "provider_order_no": record.get("provider_order_no"),
                        "input_usage": _json(record.get("input")),
                        "output_usage": _json(record.get("output")),
                        "total_usage": _json(record.get("total")),
                        "raw_usage": _json(record.get("raw_usage")),
                        "unit_prices": _json(estimate["unit_prices"]),
                        "estimated_cost_yuan": estimate["cost"],
                        "match_status": estimate["match_status"],
                        "credits_charged": credits_charged,
                        "metadata": _json(metadata),
                    },
                )


async def _estimate_cost(session, record: dict[str, Any]) -> dict[str, Any]:
    rule = await _load_pricing_rule(session, record)
    if not rule:
        return {"cost": None, "unit_prices": {}, "match_status": "unpriced"}

    unit_prices = rule["unit_prices"] or {}
    basis = str(record.get("billing_basis") or "")
    input_usage = record.get("input") or {}
    output_usage = record.get("output") or {}
    total_usage = record.get("total") or {}
    cost = Decimal("0")

    if basis == "text_tokens":
        cost += _decimal(input_usage.get("prompt_tokens")) * _decimal(unit_prices.get("input_yuan_per_million_tokens")) / Decimal("1000000")
        cost += _decimal(input_usage.get("cached_tokens")) * _decimal(unit_prices.get("cached_yuan_per_million_tokens")) / Decimal("1000000")
        cost += _decimal(input_usage.get("cache_storage_token_hours")) * _decimal(unit_prices.get("cache_storage_yuan_per_million_token_hour")) / Decimal("1000000")
        cost += _decimal(output_usage.get("completion_tokens")) * _decimal(unit_prices.get("output_yuan_per_million_tokens")) / Decimal("1000000")
    elif basis == "image_generation":
        cost += _decimal(output_usage.get("images", 0)) * _decimal(unit_prices.get("output_yuan_per_image"))
        cost += _decimal(input_usage.get("reference_images", 0)) * _decimal(unit_prices.get("input_yuan_per_reference_image"))
        cost += _decimal(total_usage.get("raw_tokens", 0)) * _decimal(unit_prices.get("raw_yuan_per_million_tokens")) / Decimal("1000000")
    elif basis == "video_generation":
        cost += _decimal(output_usage.get("videos", 0)) * _decimal(unit_prices.get("output_yuan_per_video"))
        cost += _decimal(output_usage.get("duration_seconds", 0)) * _decimal(unit_prices.get("output_yuan_per_second"))
        cost += _decimal(input_usage.get("reference_images", 0)) * _decimal(unit_prices.get("input_yuan_per_reference_image"))
        cost += _decimal(total_usage.get("raw_tokens", 0)) * _decimal(unit_prices.get("raw_yuan_per_million_tokens")) / Decimal("1000000")

    return {
        "cost": cost.quantize(Decimal("0.000001")),
        "unit_prices": unit_prices,
        "match_status": "estimated",
    }


async def _load_pricing_rule(session, record: dict[str, Any]) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            """
            SELECT unit_prices
            FROM provider_pricing_rules
            WHERE provider = :provider
              AND service = :service
              AND active = TRUE
              AND model IN (:model, '*')
            ORDER BY CASE WHEN model = :model THEN 0 ELSE 1 END, effective_at DESC
            LIMIT 1
            """
        ),
        {
            "provider": str(record.get("provider") or "unknown"),
            "service": str(record.get("service") or "unknown"),
            "model": str(record.get("model") or "unknown"),
        },
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _load_task_meta(session, task_id: str) -> dict[str, Any]:
    result = await session.execute(
        text(
            """
            SELECT user_id, project_id
            FROM tasks
            WHERE task_id = CAST(:task_id AS uuid)
            LIMIT 1
            """
        ),
        {"task_id": task_id},
    )
    row = result.mappings().first()
    return dict(row) if row else {}
