# Authoritative Run Chain Phase 1: Decision Packet + Central Dispatch Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the existing read-only `decision_tick` into the first backend-authoritative decision packet, then route all current `brain/continue` production dispatches through one gateway surface without rewriting the A/B/C lanes.

**Architecture:** Keep [`app/services/run_coordination.py`](E:\shortdrama_ai\saas - 副本\app\services\run_coordination.py) as the packet author, add a thin [`app/services/run_dispatch_gateway.py`](E:\shortdrama_ai\saas - 副本\app\services\run_dispatch_gateway.py) that validates and logs dispatch missions, and wrap the existing [`app/routes/workbench.py`](E:\shortdrama_ai\saas - 副本\app\routes\workbench.py) execution helpers behind that gateway as compatibility handlers. This slice stays backend-first and deliberately preserves the current queueing/finalization internals so the command hierarchy converges before deeper refactors.

**Tech Stack:** Python 3.11, FastAPI route/services, SQLAlchemy async sessions, existing `agent_runtime`, existing `project_brain`, existing `run_coordination`, pytest.

---

## File Structure

- Modify [`app/services/run_coordination.py`](E:\shortdrama_ai\saas - 副本\app\services\run_coordination.py)
  - Expand `DecisionTickResult` into the canonical Phase 1 packet contract.
  - Add packet helpers for lane selection, mission metadata, write scope, budget/risk hints, and failure policy.
  - Keep task-terminal observation behavior intact, but persist the richer packet.

- Create [`app/services/run_dispatch_gateway.py`](E:\shortdrama_ai\saas - 副本\app\services\run_dispatch_gateway.py)
  - Own the central dispatch skeleton.
  - Validate that only dispatchable authoritative packets can route work.
  - Publish one gateway event and update the owning run before calling a legacy execution handler.

- Modify [`app/routes/workbench.py`](E:\shortdrama_ai\saas - 副本\app\routes\workbench.py)
  - Replace direct production branches and post-planning dispatch with one gateway entry.
  - Add a compatibility packet builder that converts existing `brain/continue` state into the new packet shape.
  - Keep `_continue_generate_keyframes`, `_continue_generate_videos`, `_continue_plan_visual_assets`, and `_continue_plan_final_edit` as legacy handlers in this slice.

- Modify [`tests/unit/test_run_coordination.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_run_coordination.py)
  - Assert the new authoritative packet fields for execute/wait/recover/complete outcomes.

- Create [`tests/unit/test_run_dispatch_gateway.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_run_dispatch_gateway.py)
  - Lock the gateway’s validation, run update, and event-publish behavior.

- Modify [`tests/unit/test_project_continue.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_project_continue.py)
  - Lock the compatibility packet builder and prove `_dispatch_production_action` routes through the gateway.

- Optionally modify [`tests/integration/test_agent_events.py`](E:\shortdrama_ai\saas - 副本\tests\integration\test_agent_events.py)
  - Extend the existing `decision_tick` persistence assertion to cover the new packet fields.
  - Only run if `TEST_DATABASE_URL` becomes reachable again.

## Constraints

- Git is not usable in this workspace, so this plan uses test checkpoints instead of commit checkpoints.
- Local Postgres integration is currently blocked; unit coverage is required, integration coverage is optional in this slice.
- Do not rewrite the queue/task worker pipeline from scratch here. Phase 1 centralizes dispatch authority first and leaves deeper queue-internals cleanup for a later slice.

---

### Task 1: Expand `decision_tick` Into the Phase 1 Authoritative Packet

**Files:**
- Modify: [`app/services/run_coordination.py`](E:\shortdrama_ai\saas - 副本\app\services\run_coordination.py:24)
- Modify: [`tests/unit/test_run_coordination.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_run_coordination.py:23)

- [ ] **Step 1: Add failing packet-shape assertions to `tests/unit/test_run_coordination.py`**

Append these tests after the existing execute/wait/recover cases:

```python
def test_execute_decision_packet_contains_authoritative_dispatch_fields():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}])
    )

    assert decision.packet_version == "main_run_chain_phase1"
    assert decision.selected_lane == "c_lane_production"
    assert decision.dispatchable is True
    assert decision.allowed_writes == ["tasks", "shot_rows", "agent_events", "agent_runs"]
    assert decision.mission["action"] == "generate_keyframes"
    assert decision.mission["lane"] == "c_lane_production"
    assert decision.mission["write_scope"] == ["tasks", "shot_rows", "agent_events", "agent_runs"]
    assert decision.budget["unit"] == "image_gen"
    assert decision.budget["target_count"] == 1
    assert decision.risk["level"] == "medium"
    assert decision.failure_policy["fallback_action"] == ""
    assert decision.evidence_refs[0]["kind"] == "shot_rows"


def test_wait_decision_packet_is_not_dispatchable():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}],
            tasks=[{"task_id": "task-1", "task_type": "image_gen", "status": "running"}],
        )
    )

    assert decision.packet_version == "main_run_chain_phase1"
    assert decision.selected_lane == "main_chain"
    assert decision.dispatchable is False
    assert decision.mission == {}
    assert decision.failure_policy["fallback_action"] == ""
    assert decision.budget["target_count"] == 0
```

- [ ] **Step 2: Run the coordination tests to verify the new contract fails**

Run:

```bash
python -m pytest tests/unit/test_run_coordination.py -q
```

Expected:

```text
AttributeError or TypeError for missing packet fields on DecisionTickResult
```

- [ ] **Step 3: Expand `DecisionTickResult` and route all packet creation through one helper**

In [`app/services/run_coordination.py`](E:\shortdrama_ai\saas - 副本\app\services\run_coordination.py), replace the dataclass definition and add the helper layer below it:

```python
PACKET_VERSION = "main_run_chain_phase1"


@dataclass(frozen=True)
class DecisionTickResult:
    packet_version: str
    status: str
    action: str
    stage_id: str
    selected_lane: str
    dispatchable: bool
    allowed: bool
    reason: str
    missing: list[str]
    fallback_action: str
    active_task_count: int
    failed_task_count: int
    allowed_writes: list[str]
    evidence: dict[str, Any]
    evidence_refs: list[dict[str, Any]]
    candidate_actions: list[dict[str, Any]]
    success_criteria: list[str]
    budget: dict[str, Any]
    risk: dict[str, Any]
    failure_policy: dict[str, Any]
    mission: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decision_result(
    *,
    facts: UnifiedRunFacts,
    status: str,
    action: str,
    stage_id: str,
    allowed: bool,
    reason: str,
    missing: list[str],
    fallback_action: str,
    active_task_count: int,
    failed_task_count: int,
    candidates: list[dict[str, Any]],
    success_criteria: list[str],
) -> DecisionTickResult:
    lane = _selected_lane(action, status=status)
    fallback = fallback_action or ""
    dispatchable = status == "execute" and allowed and bool(action) and lane in {
        "a_lane_project_brain",
        "c_lane_production",
    }
    return DecisionTickResult(
        packet_version=PACKET_VERSION,
        status=status,
        action=action,
        stage_id=stage_id,
        selected_lane=lane,
        dispatchable=dispatchable,
        allowed=allowed,
        reason=reason,
        missing=missing,
        fallback_action=fallback,
        active_task_count=active_task_count,
        failed_task_count=failed_task_count,
        allowed_writes=_allowed_writes(action),
        evidence=_build_evidence(facts),
        evidence_refs=_evidence_refs(facts, action),
        candidate_actions=candidates,
        success_criteria=success_criteria,
        budget=_budget_hint(facts, action, status=status),
        risk=_risk_hint(action, failed_task_count=failed_task_count, status=status),
        failure_policy=_failure_policy(status=status, fallback_action=fallback),
        mission=_mission_payload(facts, action, stage_id=stage_id, lane=lane) if dispatchable else {},
    )


def _selected_lane(action: str, *, status: str) -> str:
    if status == "wait" or action.startswith("wait_") or not action:
        return "main_chain"
    return {
        "generate_story_plan": "a_lane_project_brain",
        "plan_visual_assets": "a_lane_project_brain",
        "lock_assets": "a_lane_project_brain",
        "generate_keyframes": "c_lane_production",
        "generate_videos": "c_lane_production",
        "plan_final_edit": "c_lane_production",
    }.get(action, "main_chain")


def _allowed_writes(action: str) -> list[str]:
    if action in {"generate_keyframes", "generate_videos"}:
        return ["tasks", "shot_rows", "agent_events", "agent_runs"]
    if action == "plan_visual_assets":
        return ["asset_refs", "project_workspace", "agent_events", "agent_runs"]
    if action == "plan_final_edit":
        return ["final_edit_plans", "project_workspace", "agent_events", "agent_runs"]
    if action == "generate_story_plan":
        return ["project_workspace", "shot_rows", "agent_events", "agent_runs"]
    return []


def _evidence_refs(facts: UnifiedRunFacts, action: str) -> list[dict[str, Any]]:
    refs = [{"kind": "shot_rows", "project_id": str(facts.run.get("project_id") or "")}]
    if facts.run.get("run_id") or facts.run.get("id"):
        refs.append({"kind": "agent_run", "run_id": str(facts.run.get("run_id") or facts.run.get("id") or "")})
    if action == "plan_final_edit":
        refs.append({"kind": "final_video_candidates", "selected_video_count": sum(1 for shot in facts.shots if shot.get("selected_video"))})
    return refs


def _budget_hint(facts: UnifiedRunFacts, action: str, *, status: str) -> dict[str, Any]:
    if status != "execute":
        return {"unit": "", "target_count": 0, "estimated_max_credits": None, "source": "non_dispatchable"}
    if action == "generate_keyframes":
        return {
            "unit": "image_gen",
            "target_count": max(0, len(facts.shots) - sum(1 for shot in facts.shots if shot.get("selected_image"))),
            "estimated_max_credits": None,
            "source": "fact_hint",
        }
    if action == "generate_videos":
        return {
            "unit": "video_gen_5s",
            "target_count": max(0, sum(1 for shot in facts.shots if shot.get("selected_image")) - sum(1 for shot in facts.shots if shot.get("selected_video"))),
            "estimated_max_credits": None,
            "source": "fact_hint",
        }
    return {"unit": "", "target_count": 0, "estimated_max_credits": None, "source": "fact_hint"}


def _risk_hint(action: str, *, failed_task_count: int, status: str) -> dict[str, Any]:
    level = "high" if action == "generate_videos" else "medium" if action in {"generate_keyframes", "plan_final_edit"} else "low"
    if status in {"recover", "blocked"} and failed_task_count > 0:
        level = "high"
    return {
        "level": level,
        "failed_task_count": failed_task_count,
        "requires_human": status in {"recover", "blocked"},
    }


def _failure_policy(*, status: str, fallback_action: str) -> dict[str, Any]:
    return {
        "fallback_action": fallback_action,
        "retryable": status in {"execute", "recover"},
        "require_human_confirmation": status in {"recover", "blocked"},
    }


def _mission_payload(
    facts: UnifiedRunFacts,
    action: str,
    *,
    stage_id: str,
    lane: str,
) -> dict[str, Any]:
    run_id = str(facts.run.get("run_id") or facts.run.get("id") or "")
    return {
        "mission_id": f"{run_id}:{stage_id or action}",
        "lane": lane,
        "action": action,
        "write_scope": _allowed_writes(action),
        "idempotency_key": f"{run_id}:{action}",
    }
```

Then replace each `return DecisionTickResult(...)` call in `evaluate_decision_tick` with `return _decision_result(...)`, preserving the current decision semantics and only enriching the payload shape.

- [ ] **Step 4: Run the updated coordination tests**

Run:

```bash
python -m pytest tests/unit/test_run_coordination.py -q
```

Expected:

```text
all selected tests passed
```

---

### Task 2: Add the Central Dispatch Gateway Skeleton

**Files:**
- Create: [`app/services/run_dispatch_gateway.py`](E:\shortdrama_ai\saas - 副本\app\services\run_dispatch_gateway.py)
- Create: [`tests/unit/test_run_dispatch_gateway.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_run_dispatch_gateway.py)

- [ ] **Step 1: Write failing gateway tests first**

Create [`tests/unit/test_run_dispatch_gateway.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_run_dispatch_gateway.py) with this content:

```python
from types import SimpleNamespace

import pytest

from app.services import run_dispatch_gateway
from app.services.run_coordination import DecisionTickResult
from app.services.run_dispatch_gateway import DispatchGatewayContext


def packet(*, status="execute", action="generate_keyframes", lane="c_lane_production", dispatchable=True):
    return DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status=status,
        action=action,
        stage_id=action,
        selected_lane=lane,
        dispatchable=dispatchable,
        allowed=status == "execute",
        reason="ready",
        missing=[],
        fallback_action="request_human_confirmation" if status != "execute" else "",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
        evidence={"project_id": "project-1", "run_id": "run-1"},
        evidence_refs=[{"kind": "shot_rows", "project_id": "project-1"}],
        candidate_actions=[],
        success_criteria=[],
        budget={"estimated_max_credits": 80, "target_count": 1, "unit": "image_gen", "source": "compat"},
        risk={"level": "medium", "failed_task_count": 0, "requires_human": False},
        failure_policy={"fallback_action": "", "retryable": True, "require_human_confirmation": False},
        mission={
            "mission_id": "run-1:generate_keyframes",
            "lane": lane,
            "action": action,
            "write_scope": ["tasks", "shot_rows", "agent_events", "agent_runs"],
            "idempotency_key": "run-1:generate_keyframes",
        } if dispatchable else {},
    )


@pytest.mark.asyncio
async def test_dispatch_gateway_updates_run_publishes_event_and_calls_handler(monkeypatch):
    observed = {"updated": None, "published": None, "handled": False}

    async def fake_update(_db, **kwargs):
        observed["updated"] = kwargs

    async def fake_publish(_db, **kwargs):
        observed["published"] = kwargs
        return {"id": "event-1"}

    async def handler():
        observed["handled"] = True
        return {"queued_count": 2}

    monkeypatch.setattr(run_dispatch_gateway, "update_agent_run", fake_update)
    monkeypatch.setattr(run_dispatch_gateway, "publish_agent_event", fake_publish)

    result = await run_dispatch_gateway.dispatch_authoritative_packet(
        object(),
        packet=packet(),
        context=DispatchGatewayContext(
            project_id="project-1",
            user_id=7,
            user_tier="pro",
            run_id="run-1",
            run_mode="step",
        ),
        handlers={"generate_keyframes": handler},
    )

    assert observed["handled"] is True
    assert observed["updated"]["current_phase"] == "dispatch_gateway"
    assert observed["published"]["source"] == "dispatch_gateway"
    assert observed["published"]["meta"]["decision_packet"]["action"] == "generate_keyframes"
    assert result["queued_count"] == 2
    assert result["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_dispatch_gateway_rejects_non_dispatchable_packets(monkeypatch):
    async def fail_handler():
        raise AssertionError("handler should not run")

    monkeypatch.setattr(run_dispatch_gateway, "update_agent_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_dispatch_gateway, "publish_agent_event", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="not dispatchable"):
        await run_dispatch_gateway.dispatch_authoritative_packet(
            object(),
            packet=packet(status="wait", action="wait_for_tasks", lane="main_chain", dispatchable=False),
            context=DispatchGatewayContext(
                project_id="project-1",
                user_id=7,
                user_tier="pro",
                run_id="run-1",
                run_mode="step",
            ),
            handlers={"wait_for_tasks": fail_handler},
        )
```

- [ ] **Step 2: Run the new gateway tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/test_run_dispatch_gateway.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.services.run_dispatch_gateway'
```

- [ ] **Step 3: Create the gateway service**

Create [`app/services/run_dispatch_gateway.py`](E:\shortdrama_ai\saas - 副本\app\services\run_dispatch_gateway.py) with this content:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runtime import publish_agent_event, update_agent_run
from app.services.run_coordination import DecisionTickResult

DispatchHandler = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class DispatchGatewayContext:
    project_id: str
    user_id: int
    user_tier: str
    run_id: str
    run_mode: str


async def dispatch_authoritative_packet(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: DispatchGatewayContext,
    handlers: dict[str, DispatchHandler],
) -> dict[str, Any]:
    mission = _validate_packet(packet)
    action = str(mission["action"])
    handler = handlers.get(action)
    if handler is None:
        raise ValueError(f"no gateway handler registered for action={action}")

    await update_agent_run(
        db,
        run_id=context.run_id,
        status="dispatching",
        current_phase="dispatch_gateway",
        summary=f"Dispatch gateway routing {action} via {packet.selected_lane}.",
        final_decision=action,
    )
    await publish_agent_event(
        db,
        run_id=context.run_id,
        project_id=context.project_id,
        user_id=context.user_id,
        source="dispatch_gateway",
        event_type="decision",
        phase="dispatch_gateway",
        title="Authoritative dispatch gateway",
        detail=f"{action} -> {packet.selected_lane}",
        status="dispatching",
        progress=55,
        meta={"decision_packet": packet.as_dict(), "mission": mission, "run_mode": context.run_mode},
        event_kind="decision",
        visibility="debug",
        summary=f"Dispatch {action}",
        reason=packet.reason,
    )

    result = dict(await handler())
    result.setdefault("run_id", context.run_id)
    result["decision_packet"] = packet.as_dict()
    return result


def _validate_packet(packet: DecisionTickResult) -> dict[str, Any]:
    if packet.status != "execute" or not packet.dispatchable or not packet.allowed:
        raise ValueError(f"packet is not dispatchable: status={packet.status} dispatchable={packet.dispatchable}")
    mission = dict(packet.mission or {})
    for key in ("mission_id", "lane", "action", "write_scope", "idempotency_key"):
        if not mission.get(key):
            raise ValueError(f"decision packet mission missing {key}")
    if str(mission["lane"]) not in {"a_lane_project_brain", "b_lane_agent_runs", "c_lane_production"}:
        raise ValueError(f"unsupported mission lane={mission['lane']}")
    if not isinstance(mission.get("write_scope"), list) or not mission["write_scope"]:
        raise ValueError("decision packet mission requires a non-empty write_scope")
    return mission
```

- [ ] **Step 4: Run gateway and packet tests together**

Run:

```bash
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py -q
```

Expected:

```text
all selected tests passed
```

---

### Task 3: Route `workbench` Production Paths Through the Gateway With Compatibility Packets

**Files:**
- Modify: [`app/routes/workbench.py`](E:\shortdrama_ai\saas - 副本\app\routes\workbench.py:930)
- Modify: [`tests/unit/test_project_continue.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_project_continue.py:111)

- [ ] **Step 1: Add failing compatibility-wrapper tests**

Append these tests to [`tests/unit/test_project_continue.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_project_continue.py):

```python
import pytest

from app.routes import workbench


def test_compatibility_packet_for_generate_videos_uses_c_lane_and_cost_hint():
    packet = workbench._build_compatibility_decision_packet(
        project_id="project-1",
        run_id="11111111-1111-1111-1111-111111111111",
        action="generate_videos",
        before={"signals": {"operational_pending_video_count": 7, "workspace_shot_count": 8}},
        image_unit_price=10,
        video_unit_price=80,
        provider="seedance",
    )

    assert packet.selected_lane == "c_lane_production"
    assert packet.budget["estimated_max_credits"] == 320
    assert packet.mission["provider"] == "seedance"
    assert packet.mission["write_scope"] == ["tasks", "shot_rows", "agent_events", "agent_runs"]


@pytest.mark.asyncio
async def test_dispatch_production_action_routes_through_gateway(monkeypatch):
    observed = {}

    async def fake_dispatch(_db, *, packet, context, handlers):
        observed["packet"] = packet
        observed["context"] = context
        observed["handler_names"] = sorted(handlers.keys())
        return {"ok": True}

    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="generate_keyframes",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_keyframe_count": 2, "workspace_shot_count": 2}},
        name="project-1",
        run_id="11111111-1111-1111-1111-111111111111",
        run_mode="step",
        result={"before": {}},
        image_unit_price=12,
        video_unit_price=80,
    )

    assert observed["packet"].action == "generate_keyframes"
    assert observed["packet"].selected_lane == "c_lane_production"
    assert observed["context"].run_id == "11111111-1111-1111-1111-111111111111"
    assert "generate_keyframes" in observed["handler_names"]
    assert result == {"ok": True}
```

- [ ] **Step 2: Run the workbench compatibility tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/test_project_continue.py -q
```

Expected:

```text
AttributeError for missing _build_compatibility_decision_packet or TypeError because _dispatch_production_action does not yet accept the new arguments
```

- [ ] **Step 3: Add the compatibility packet builder and route through the gateway**

In [`app/routes/workbench.py`](E:\shortdrama_ai\saas - 副本\app\routes\workbench.py), add these imports near the top:

```python
from app.services.run_coordination import DecisionTickResult
from app.services.run_dispatch_gateway import DispatchGatewayContext, dispatch_authoritative_packet
```

Add these helpers immediately above `_dispatch_production_action`:

```python
def _build_compatibility_decision_packet(
    *,
    project_id: str,
    run_id: str,
    action: str,
    before: dict[str, Any],
    image_unit_price: int,
    video_unit_price: int,
    provider: str = "seedance",
) -> DecisionTickResult:
    signals = before.get("signals") if isinstance(before.get("signals"), dict) else {}
    lane = {
        "plan_visual_assets": "a_lane_project_brain",
        "generate_keyframes": "c_lane_production",
        "generate_videos": "c_lane_production",
        "plan_final_edit": "c_lane_production",
    }.get(action, "main_chain")
    estimated_max_credits = _compatibility_cost_hint(
        action,
        signals=signals,
        image_unit_price=image_unit_price,
        video_unit_price=video_unit_price,
    )
    write_scope = _compatibility_write_scope(action)
    stage_id = {
        "plan_visual_assets": "plan_visual_assets",
        "generate_keyframes": "generate_keyframes",
        "generate_videos": "generate_videos",
        "plan_final_edit": "final_cut",
    }.get(action, action)
    return DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status="execute",
        action=action,
        stage_id=stage_id,
        selected_lane=lane,
        dispatchable=True,
        allowed=True,
        reason="Legacy brain/continue compatibility wrapper routed through the authoritative dispatch gateway.",
        missing=[],
        fallback_action="request_human_confirmation",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=write_scope,
        evidence={
            "project_id": project_id,
            "run_id": run_id,
            "shot_count": int(signals.get("workspace_shot_count") or signals.get("operational_shot_count") or 0),
        },
        evidence_refs=[
            {"kind": "shot_rows", "project_id": project_id},
            {"kind": "agent_run", "run_id": run_id},
        ],
        candidate_actions=[{"action": action, "stage_id": stage_id, "status": "pending", "allowed": True, "reason": ""}],
        success_criteria=[],
        budget={
            "unit": "video_gen_5s" if action == "generate_videos" else "image_gen" if action == "generate_keyframes" else "",
            "target_count": _compatibility_target_count(action, signals=signals),
            "estimated_max_credits": estimated_max_credits,
            "source": "workbench_compatibility",
        },
        risk={
            "level": "high" if action == "generate_videos" else "medium" if action in {"generate_keyframes", "plan_final_edit"} else "low",
            "failed_task_count": 0,
            "requires_human": False,
        },
        failure_policy={
            "fallback_action": "request_human_confirmation",
            "retryable": action in {"generate_keyframes", "generate_videos"},
            "require_human_confirmation": False,
        },
        mission={
            "mission_id": f"{run_id}:{action}",
            "lane": lane,
            "action": action,
            "write_scope": write_scope,
            "idempotency_key": f"{run_id}:{action}",
            "provider": provider if action == "generate_videos" else "",
        },
    )


def _compatibility_target_count(action: str, *, signals: dict[str, Any]) -> int:
    if action == "generate_keyframes":
        return min(BRAIN_KEYFRAME_BATCH_MAX, int(signals.get("operational_pending_keyframe_count") or 0))
    if action == "generate_videos":
        return min(BRAIN_VIDEO_BATCH_MAX, int(signals.get("operational_pending_video_count") or 0))
    return 0


def _compatibility_cost_hint(
    action: str,
    *,
    signals: dict[str, Any],
    image_unit_price: int,
    video_unit_price: int,
) -> int:
    if action == "generate_keyframes":
        return _compatibility_target_count(action, signals=signals) * image_unit_price
    if action == "generate_videos":
        return _compatibility_target_count(action, signals=signals) * video_unit_price
    return 0


def _compatibility_write_scope(action: str) -> list[str]:
    if action in {"generate_keyframes", "generate_videos"}:
        return ["tasks", "shot_rows", "agent_events", "agent_runs"]
    if action == "plan_visual_assets":
        return ["asset_refs", "project_workspace", "agent_events", "agent_runs"]
    if action == "plan_final_edit":
        return ["final_edit_plans", "project_workspace", "agent_events", "agent_runs"]
    return []
```

Then replace `_dispatch_production_action` with this gateway-backed version:

```python
async def _dispatch_production_action(
    db: AsyncSession,
    *,
    action: str,
    project_id: str,
    user_id: int,
    user_tier: str,
    before: dict[str, Any],
    name: str,
    run_id: str,
    run_mode: str,
    result: dict[str, Any],
    image_unit_price: int,
    video_unit_price: int,
    provider: str = "seedance",
    semantic_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet = _build_compatibility_decision_packet(
        project_id=project_id,
        run_id=run_id,
        action=action,
        before=before,
        image_unit_price=image_unit_price,
        video_unit_price=video_unit_price,
        provider=provider,
    )
    handlers = {
        "generate_keyframes": lambda: _continue_generate_keyframes(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
            semantic_control=semantic_control,
        ),
        "plan_visual_assets": lambda: _continue_plan_visual_assets(
            db,
            project_id=project_id,
            user_id=user_id,
            before=before,
            name=name,
            run_id=run_id,
        ),
        "generate_videos": lambda: _continue_generate_videos(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
            provider=provider,
            semantic_control=semantic_control,
        ),
        "plan_final_edit": lambda: _continue_plan_final_edit(
            db,
            project_id=project_id,
            user_id=user_id,
            before=before,
            name=name,
            run_id=run_id,
        ),
    }
    return await dispatch_authoritative_packet(
        db,
        packet=packet,
        context=DispatchGatewayContext(
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            run_id=run_id,
            run_mode=run_mode,
        ),
        handlers=handlers,
    )
```

Finally, replace the four direct action branches inside `continue_project_brain` so they all call `_dispatch_production_action(...)` instead of calling `_continue_*` directly, and update the post-planning dispatch call at [`app/routes/workbench.py`](E:\shortdrama_ai\saas - 副本\app\routes\workbench.py:1285) to pass the new pricing and compatibility arguments:

```python
return await _dispatch_production_action(
    db,
    action=action,
    project_id=project_id,
    user_id=user_id,
    user_tier=str(current_user.get("tier") or "free"),
    before=current_brain,
    name=str(row.name if row else project_id),
    run_id=run_id,
    run_mode=run_mode,
    result={"project_id": project_id, "before": current_brain},
    image_unit_price=image_unit_price,
    video_unit_price=video_unit_price,
    provider=str((body or {}).get("video_provider") or "seedance"),
    semantic_control={key: (body or {}).get(key) for key in ("intent_brief", "semantic_plan", "constraint_packet", "verification_plan", "human_routing")},
)
```

Use the same call shape for the post-planning branch, but leave `provider` and `semantic_control` at their defaults unless the caller already has them.

- [ ] **Step 4: Run the workbench compatibility tests**

Run:

```bash
python -m pytest tests/unit/test_project_continue.py -q
```

Expected:

```text
all selected tests passed
```

---

### Task 4: Regression Verification and Optional Integration Check

**Files:**
- Read: [`tests/unit/test_task_shared_run_coordination_hook.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_task_shared_run_coordination_hook.py)
- Read: [`tests/unit/test_agent_run_state_machine.py`](E:\shortdrama_ai\saas - 副本\tests\unit\test_agent_run_state_machine.py)
- Optional Modify: [`tests/integration/test_agent_events.py`](E:\shortdrama_ai\saas - 副本\tests\integration\test_agent_events.py:345)

- [ ] **Step 1: Run the focused unit regression suite**

Run:

```bash
python -m pytest \
  tests/unit/test_run_coordination.py \
  tests/unit/test_run_dispatch_gateway.py \
  tests/unit/test_project_continue.py \
  tests/unit/test_task_shared_run_coordination_hook.py \
  tests/unit/test_agent_run_state_machine.py \
  -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 2: If the gateway work changed route-side event payloads, extend the integration assertion**

If `TEST_DATABASE_URL` is available again, update [`tests/integration/test_agent_events.py`](E:\shortdrama_ai\saas - 副本\tests\integration\test_agent_events.py) by extending the existing `decision_tick` assertion block:

```python
    assert packet.get("packet_version") == "main_run_chain_phase1"
    assert "selected_lane" in packet
    assert "failure_policy" in packet
    assert "mission" in packet
    assert "evidence_refs" in packet
```

- [ ] **Step 3: Run the optional integration check only when DB connectivity is restored**

Run:

```bash
python -m pytest tests/integration/test_agent_events.py -q -k decision_tick
```

Expected:

```text
selected integration test passed
```

If the environment still cannot reach `TEST_DATABASE_URL`, record the skip and rely on the unit suite above.

- [ ] **Step 4: Record the implementation result at the bottom of this plan**

Append this section after execution:

```markdown
## Implementation Result

- Expanded `run_coordination` from a read-only tick into the Phase 1 authoritative decision packet contract.
- Added `run_dispatch_gateway.py` as the single backend dispatch entry for current `brain/continue` production actions.
- Routed direct and post-planning workbench dispatches through the gateway using compatibility packets.
- Verification:
  - `python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_project_continue.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_agent_run_state_machine.py -q`
  - Result: [paste exact pytest summary]
- Optional integration:
  - `python -m pytest tests/integration/test_agent_events.py -q -k decision_tick`
  - Result: [paste exact pass summary or record skipped because TEST_DATABASE_URL was unreachable]
- Git:
  - Git operations were not used because this workspace still points at a missing gitdir.
```

---

## Acceptance Criteria

- `DecisionTickResult` persists a Phase 1 packet with lane, dispatchability, mission metadata, failure policy, risk hints, budget hints, allowed writes, and evidence references.
- The task-terminal `decision_tick` event still writes exactly once per terminal task, but now stores the richer packet.
- There is one new backend dispatch service, and it is the only route-level entry used for current `brain/continue` production actions.
- Direct `generate_keyframes`, `plan_visual_assets`, `generate_videos`, and `plan_final_edit` branches no longer call legacy handlers directly; they go through the gateway.
- The post-planning dispatch path no longer dispatches work directly; it also goes through the gateway.
- Existing `_continue_*` functions remain as compatibility handlers in this slice rather than being rewritten.
- No frontend convergence work is introduced.
- No new automatic continuation loop is introduced beyond the existing task-terminal observer.

## Implementation Result

- Expanded `run_coordination` from a read-only tick into the Phase 1 authoritative decision packet contract.
- Added `run_dispatch_gateway.py` as the single backend dispatch entry for current `brain/continue` production actions.
- Routed direct and post-planning workbench dispatches through the gateway using compatibility packets.
- Verification:
  - `python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_project_continue.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_agent_run_state_machine.py -q`
  - Result: `50 passed in 2.47s`
- Optional integration:
  - `python -m pytest tests/integration/test_agent_events.py -q -k decision_tick`
  - Result: not run in this session because local Postgres / `TEST_DATABASE_URL` remains an environment constraint in the approved handoff.
- Git:
  - Git operations were not used because this workspace still points at a missing gitdir.

## Self-Review

- Spec coverage: Task 1 hardens the decision packet; Task 2 adds the central dispatch gateway skeleton; Task 3 moves the current authoritative backend entry (`brain/continue`) onto that gateway while keeping compatibility handlers; Task 4 verifies the backend-only slice.
- Placeholder scan: Each code-changing step includes concrete code blocks, exact file paths, and exact commands. There are no `TODO` or “similar to previous task” placeholders.
- Type consistency: `packet_version`, `selected_lane`, `dispatchable`, `allowed_writes`, `budget`, `risk`, `failure_policy`, and `mission` use the same names across service code, gateway code, and tests.
- Scope check: This plan intentionally does not converge the frontend, does not rewrite task worker internals, and does not add autonomous recovery execution. It only establishes the authoritative packet and gateway skeleton.
