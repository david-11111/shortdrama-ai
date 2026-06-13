"""Compatibility shim — delegates to ``app.services.state_machine``.

All new code should import from ``app.services.state_machine`` directly.
This module exists only to preserve existing call sites during the
migration; it will be removed in a future cleanup pass.
"""
from __future__ import annotations

from typing import Any

from app.services.state_machine import (
    PRODUCTION_POLICIES,
    PRODUCTION_STAGES,
    POLICY_BY_STAGE_ID,
    STAGE_BY_ACTION,
    STAGE_BY_ID,
    infer_continue_action,
    infer_continue_action_decision,
    evaluate_action_gate,
    evaluate_production_stages,
    recommend_next_action,
    validate_policy_graph,
)

# Re-export all public symbols
__all__ = [
    "PRODUCTION_POLICIES",
    "PRODUCTION_STAGES",
    "POLICY_BY_STAGE_ID",
    "STAGE_BY_ACTION",
    "STAGE_BY_ID",
    "infer_continue_action",
    "infer_continue_action_decision",
    "evaluate_action_gate",
    "evaluate_production_stages",
    "recommend_next_action",
    "validate_policy_graph",
]

# Legacy type aliases — deprecated, kept for backward compatibility
TERMINAL_DONE = {"done", "completed"}
TERMINAL_FAILED = {"failed", "dead_letter", "cancelled"}
ACTIVE_STATUSES = {"created", "queued", "pending", "running", "retrying", "dispatching", "verifying", "writing_back", "generating_image", "generating_video", "provider_waiting", "provider_requesting"}
BLOCKING_REVIEW_STATUSES = {"needs_review", "regenerate", "failed", "fail", "rejected", "blocked"}
POLICY_VERSION = "commercial_production_policy_v2"

# Legacy function stubs — delegate to new implementation
def _stats(shots, tasks, production_run=None):
    from app.services.state_machine.stats import StatsAccumulator
    acc = StatsAccumulator()
    for s in shots: acc.add_shot(s)
    for t in tasks: acc.add_task(t, production_status=str((production_run or {}).get("status") or ""))
    acc.set_production_run(production_run)
    return acc.finalize()

# ── Legacy dataclass exports ────────────────────────────────────────────────

from dataclasses import dataclass, field  # noqa: E402

# Recreate the legacy ProductionStage tuple-based structure
# This will be removed after all callers migrate to Pydantic models
from app.services.state_machine.models import PRODUCTION_POLICIES as _POLICIES

@dataclass(frozen=True)
class ProductionStage:
    """Legacy dataclass — prefer using ``ProductionPolicy`` from models."""
    id: str
    title: str
    action: str
    required_before: tuple[str, ...] = ()

# Build PRODUCTION_STAGES from the new policy definitions
PRODUCTION_STAGES = tuple(
    ProductionStage(id=p.id, title=p.title, action=p.action, required_before=p.depends_on)
    for p in _POLICIES
)

GateRule = tuple[tuple[str, str, Any], str, str]
Condition = tuple[str, str, Any]
PolicySpec = tuple[str, str, str, tuple[str, ...], tuple[tuple[tuple[str, str, Any], str, str], ...], tuple[tuple[str, tuple[tuple[str, str, Any], ...]]], str]
