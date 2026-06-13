"""Stage evaluator — gate checks, status resolution, next-action recommendation.

All functions are pure: they accept plain data and return plain dicts.
No I/O, no side effects.
"""

from __future__ import annotations

from typing import Any, Callable

from app.services.state_machine.models import (
    GateRule,
    PRODUCTION_POLICIES,
    POLICY_VERSION,
    POLICY_BY_STAGE_ID,
    STAGE_BY_ACTION,
    STAGE_BY_ID,
    resolve_node_id,
)
from app.services.state_machine.stats import StatsAccumulator


def evaluate_production_stages(
    *,
    shots: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    production_run: dict[str, Any] | None = None,
    node_id_resolver: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate every production stage against current state.

    Returns one dict per policy, in policy order.
    """
    stats = _compute_stats(shots, tasks, production_run)
    completed: set[str] = set()
    rows: list[dict[str, Any]] = []

    resolve = node_id_resolver or (lambda a: resolve_node_id(a))

    for policy in PRODUCTION_POLICIES:
        gate = _evaluate_gate(policy, stats, completed)
        status = _resolve_status(policy, stats)
        if not gate["allowed"] and status != "completed":
            status = "blocked"
        if status == "completed":
            completed.add(policy.id)

        rows.append({
            "id": policy.id,
            "title": policy.title,
            "action": policy.action,
            "node_id": resolve(policy.action),
            "status": status,
            "source": _source_for(policy.id, stats, status),
            "progress": _progress_for(policy.progress_metric, stats, status),
            "gate": gate,
            "stats": stats,
            "policy": _policy_metadata(policy),
        })

    return rows


def evaluate_action_gate(
    action: str,
    *,
    shots: list[dict[str, Any]],
    tasks: list[dict[str, Any]] | None = None,
    production_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the gate for a single action (used by runtime)."""
    stage = STAGE_BY_ACTION.get(action)
    if not stage:
        return {"allowed": True, "action": action, "stage_id": "", "reason": "", "missing": [], "recovery": ""}

    for row in evaluate_production_stages(shots=shots, tasks=tasks or [], production_run=production_run):
        if row["id"] == stage.id:
            return {
                "allowed": row["gate"]["allowed"],
                "action": action,
                "stage_id": stage.id,
                "reason": row["gate"]["reason"],
                "missing": row["gate"]["missing"],
                "recovery": _recovery_from(row),
                "status": row["status"],
                "stats": row["stats"],
            }

    return {"allowed": True, "action": action, "stage_id": stage.id, "reason": "", "missing": [], "recovery": ""}


def recommend_next_action(
    *,
    shots: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    production_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the first action that is not yet completed."""
    for stage in evaluate_production_stages(shots=shots, tasks=tasks, production_run=production_run):
        if stage["status"] in {"pending", "blocked", "running"}:
            return {
                "action": stage["action"],
                "stage_id": stage["id"],
                "status": stage["status"],
                "reason": stage["gate"]["reason"],
                "allowed": stage["gate"]["allowed"],
            }
    return {"action": "writeback_review", "stage_id": "writeback_review", "status": "completed", "reason": "", "allowed": True}


# ── Internal helpers ────────────────────────────────────────────────────────


def _compute_stats(shots: list[dict[str, Any]], tasks: list[dict[str, Any]], production_run: dict[str, Any] | None) -> dict[str, Any]:
    """Single-pass statistics computation."""
    acc = StatsAccumulator()
    for shot in shots:
        acc.add_shot(shot)
    prod_status = str((production_run or {}).get("status") or "")
    for task in tasks:
        acc.add_task(task, production_status=prod_status)
    acc.set_production_run(production_run)
    return acc.finalize()


def _policy_metadata(policy) -> dict[str, Any]:
    data = policy.model_dump()
    data["version"] = POLICY_VERSION
    data["gate_rules"] = [
        {
            "metric": rule.condition.metric,
            "op": str(rule.condition.op),
            "expected": rule.condition.expected,
            "missing": rule.missing_item,
            "reason": rule.reason,
        }
        for rule in policy.gates
    ]
    data["status_rules"] = [
        {
            "status": rule.status,
            "conditions": [
                {"metric": condition.metric, "op": str(condition.op), "expected": condition.expected}
                for condition in rule.conditions
            ],
        }
        for rule in policy.status_rules
    ]
    return data


def _evaluate_gate(policy, stats: dict[str, Any], completed: set[str]) -> dict[str, Any]:
    """Check dependency gates for a policy."""
    missing: list[str] = [dep for dep in policy.depends_on if dep not in completed]
    reasons: list[str] = []
    for rule in policy.gates:
        if rule.condition.evaluate(stats):
            missing.append(rule.missing_item)
            reasons.append(rule.reason)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique_missing: list[str] = []
    for item in missing:
        if item not in seen:
            seen.add(item)
            unique_missing.append(item)

    return {
        "allowed": not unique_missing,
        "missing": unique_missing,
        "reason": reasons[0] if reasons else (
            f"Missing required prior stages: {', '.join(unique_missing)}" if unique_missing else ""
        ),
    }


def _resolve_status(policy, stats: dict[str, Any]) -> str:
    """Determine the current status of a policy given stats."""
    for rule in policy.status_rules:
        if rule.evaluate(stats):
            return rule.status
    return "blocked" if not policy.status_rules else "pending"


def _progress_for(metric: str, stats: dict[str, Any], status: str) -> int:
    if status == "completed":
        return 100
    if status == "blocked" or not metric:
        return 0
    if status == "running":
        return 50
    return int(100 * int(stats.get(metric) or 0) / max(1, int(stats.get("shot_count") or 0)))


def _source_for(stage_id: str, stats: dict[str, Any], status: str) -> str:
    if status in {"blocked", "pending"}:
        return "gate"
    if stage_id == "read_context":
        return "state_machine"
    if stage_id in {"generate_keyframes", "review_keyframes"} and stats.get("image_task_count", 0):
        return "run_evidence" if stats.get("image_task_done_count") or stats.get("image_task_active_count") else "project_state"
    if stage_id in {"generate_videos", "review_videos"} and stats.get("video_task_count", 0):
        return "run_evidence" if stats.get("video_task_done_count") or stats.get("video_task_active_count") else "project_state"
    return "project_state"


def _recovery_from(stage: dict[str, Any]) -> str:
    missing = set(stage.get("gate", {}).get("missing") or [])
    # Map common missing items to recovery actions
    if "shot_rows" in missing:
        return "generate_story_plan"
    if any(m in missing for m in ("selected_image", "generate_keyframes", "review_keyframes", "image_review_blockers")):
        return "generate_keyframes"
    if any(m in missing for m in ("selected_video", "generate_videos", "review_videos", "video_review_blockers")):
        return "generate_videos"
    if "final_video_url" in missing or "final_cut" in missing:
        return "plan_final_edit"
    if missing:
        return "fallback_reasoning"
    return ""
