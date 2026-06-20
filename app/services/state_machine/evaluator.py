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
    ReworkTrigger,
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

    When a stage's ``rework_triggers`` are active, the stage itself is
    marked ``rework_needed`` and the *rework_to* field points to the
    target stage ID so callers (especially ``recommend_next_action``)
    can redirect execution.
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

        # ── Rework detection ────────────────────────────────────────────
        rework = _evaluate_rework_triggers(policy, stats, completed)

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
            "rework": rework,  # added field
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
    """Return the first action that is not yet completed.

    Rework triggers take priority over normal forward progression:
    if a stage's rework condition is active we redirect to the
    ``rework_to`` stage instead of returning the stage itself.
    """
    for stage in evaluate_production_stages(shots=shots, tasks=tasks, production_run=production_run):
        # ── Rework redirect ──────────────────────────────────────────
        rework = stage.get("rework") or {}
        if rework.get("triggered") and rework.get("rework_to"):
            # Map back_to stage ID to its action
            back_stage = STAGE_BY_ID.get(rework["rework_to"])
            back_action = back_stage.action if back_stage else rework["rework_to"]
            gate = stage.get("gate", {})
            return {
                "action": back_action,
                "stage_id": rework["rework_to"],
                "status": "pending",
                "reason": rework.get("reason") or gate.get("reason", ""),
                "allowed": True,
                "rework_redirect": {
                    "from_stage": stage["id"],
                    "rework_to": rework["rework_to"],
                    "scope": rework.get("scope", "affected"),
                    "affects_shots": rework.get("affects_shots", []),
                    "depth": rework.get("depth", "shallow"),
                    "max_retries": rework.get("max_retries", 3),
                    "retry_exhausted_action": rework.get("retry_exhausted_action", "skip_shot"),
                    "missing": gate.get("missing", []),
                },
            }

        if stage["status"] in {"pending", "blocked", "running"}:
            return {
                "action": stage["action"],
                "stage_id": stage["id"],
                "status": stage["status"],
                "reason": stage["gate"]["reason"],
                "allowed": stage["gate"]["allowed"],
            }
    return {"action": "writeback_review", "stage_id": "writeback_review", "status": "completed", "reason": "", "allowed": True}


def should_escalate(
    rework_redirect: dict[str, Any],
    attempt: int,
) -> str:
    """Check whether auto-rework should escalate.

    Returns ``"proceed"`` if the rework can continue, or the escalation
    action (``"skip_shot"`` / ``"human_review"``) if retries are exhausted.

    ``attempt`` is 1-based: the first rework is attempt 1.
    """
    max_retries = rework_redirect.get("max_retries", 3)
    if attempt > max_retries:
        return rework_redirect.get("retry_exhausted_action", "skip_shot")
    return "proceed"


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


def _evaluate_rework_triggers(
    policy,
    stats: dict[str, Any],
    completed: set[str],
) -> dict[str, Any]:
    """Check rework triggers for *policy*.

    Returns a dict::

        {"triggered": True, "rework_to": "generate_keyframes",
         "scope": "affected", "reason": "..."}
        # or
        {"triggered": False}

    Guards (all must pass for rework to fire):

    1. **back_to stage is completed** — the target of the rework must
       have finished at least once.  This prevents false positives
       during initial forward progression (e.g. "no selected images yet"
       would happily trigger "go back to generate_keyframes" before
       generate_keyframes has even run).

    2. **All upstream deps of back_to are still in completed** — if a
       stage *before* the back_to target somehow regressed, the system
       should fix that first rather than jumping to the rework target.
       This prevents phantom reworks when ancestor stages unexpectedly
       revert.
    """
    if not policy.rework_triggers:
        return {"triggered": False}

    # Guard 1: back_to stage must have completed at least once
    relevant = [
        t for t in policy.rework_triggers
        if t.back_to in completed
    ]
    if not relevant:
        return {"triggered": False}

    # Guard 2: all ancestors of back_to must also still be completed
    # (don't jump to rework if an earlier stage regressed).
    for trigger in relevant:
        back_stage = POLICY_BY_STAGE_ID.get(trigger.back_to)
        if back_stage:
            for dep in back_stage.depends_on:
                if dep not in completed:
                    return {"triggered": False}
    if not relevant:
        return {"triggered": False}

    for trigger in relevant:
        if trigger.condition.evaluate(stats):
            # Determine which shots are affected
            affects_shots: list[int] = []
            if trigger.scope == "affected":
                affects_shots = stats.get("image_blocking_shots") or stats.get("video_blocking_shots") or []
            return {
                "triggered": True,
                "rework_to": trigger.back_to,
                "scope": trigger.scope,
                "affects_shots": affects_shots,
                "depth": trigger.depth,
                "max_retries": trigger.max_retries,
                "retry_exhausted_action": trigger.retry_exhausted_action,
                "reason": trigger.reason or (
                    f"Rework triggered: {trigger.condition.metric} "
                    f"{trigger.condition.op} {trigger.condition.expected}"
                ),
            }
    return {"triggered": False}
