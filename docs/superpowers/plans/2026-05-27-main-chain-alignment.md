# Main Chain Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align code and documentation around one authoritative 7-layer main chain, fix the detected chain breaks, and prove the loop with unit, route-contract, and database-backed end-to-end tests.

**Architecture:** Add a small orchestration layer that turns canonical `DecisionTickResult` packets into the only write-capable main-chain command path. Existing workbench and agent-run routes become adapters into this controller; terminal task observation can continue the run through the gateway instead of only writing debug events.

**Tech Stack:** FastAPI routes, SQLAlchemy async sessions, Celery task submission, pytest/pytest-asyncio, existing `agent_runs`, `run_coordination`, `run_dispatch_gateway`, `workbench`, and task hook modules.

---

## Completion Levels

### P0: Freeze The Contract

Purpose: make the target chain enforceable before code movement.

Exit criteria:

- `docs/main-chain-7-layer-code-verification.md` remains the diagnosis baseline.
- A new implementation contract documents exactly which path is authoritative.
- Tests still pass before behavior changes.

Verification:

```powershell
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py -q
```

Expected:

```text
19 passed
```

### P1: Add The Main Chain Controller

Purpose: create the missing L7 -> L4 bridge without changing every caller at once.

Exit criteria:

- `execute` decisions dispatch through `dispatch_authoritative_packet`.
- `wait`, `recover`, `blocked`, and `complete` decisions update/publish run state consistently.
- Terminal hook can call the controller in dry-run mode first, then active mode.

### P2: Replace Compatibility Command Sources

Purpose: make canonical `load_run_facts_from_snapshot -> evaluate_decision_tick` the source of production command packets.

Exit criteria:

- `_dispatch_production_action` no longer fabricates allowed compatibility packets for normal agent production.
- `production/start` is either a platform-specific compatibility entry with explicit docs or converted into canonical facts.
- B lane no longer directly owns write execution.

### P3: Lock The Boundary

Purpose: prevent future drift.

Exit criteria:

- Direct task APIs are marked and tested as platform-only.
- Main-chain routes cannot queue provider tasks except through gateway.
- `_maybe_finalize_run` cannot mark a run complete when L7 says another executable production stage exists.

### P4: Deep End-To-End Verification

Purpose: prove the Codex-style loop.

Exit criteria:

- Full DB-backed integration test covers `story -> keyframes -> videos -> final edit -> complete`.
- Failure path covers `task_failed -> recover/blocked -> human or retry`.
- Docs and tests describe the same chain.

---

## Files To Create Or Modify

Create:

- `docs/main-chain-implementation-contract.md`  
  Defines the authoritative 7-layer contract, allowed entry points, and direct/platform-only APIs.

- `app/services/main_chain_controller.py`  
  Owns L7 policy application: dispatch, wait, recover, blocked, complete.

- `app/services/main_chain_handlers.py`  
  Provides handler registry for canonical actions. Initially wraps existing workbench helpers; later tasks can move the handler internals out of routes.

- `tests/unit/test_main_chain_controller.py`  
  Unit tests for execute/wait/recover/blocked/complete behavior.

- `tests/integration/test_main_chain_loop.py`  
  Database-backed loop tests for terminal task -> decision -> dispatch.

Modify:

- `app/services/run_coordination.py`  
  Keep facts and packet generation here. Expose enough run/task context helpers for the controller.

- `app/services/run_dispatch_gateway.py`  
  Keep packet validation here. Add idempotency/write-scope assertions if not already enforced by controller.

- `app/tasks/_shared.py`  
  Replace observe-only terminal behavior with controller call after terminal task persistence.

- `app/routes/workbench.py`  
  Convert compatibility packet usage to canonical packet usage for normal main-chain production actions.

- `app/routes/agent_runs.py`  
  Restrict B lane writes to requested action intent; route writes through canonical controller/gateway.

- `app/services/agent_action_executor.py`  
  Return intent/deferred/answer results, not direct write execution for production actions.

- `app/services/agent_control_registry.py`  
  Split human-readable actions from write-executable actions.

- `app/main.py`  
  Mark `/api/batch/*` and `/api/tts/generate` as platform/direct-task paths in response metadata or route docs.

- `tests/unit/test_project_continue.py`  
  Update compatibility expectations to canonical packet expectations.

- `tests/unit/test_agent_runs_route_contract.py`  
  Update B-lane route contracts.

- `tests/unit/test_task_shared_run_coordination_hook.py`  
  Change terminal hook expectation from observe-only to controller invocation.

- `tests/integration/test_agent_events.py`  
  Keep decision event assertion and add dispatch/complete assertions where database is available.

---

## Task 1: P0 Contract Document

**Files:**

- Create: `docs/main-chain-implementation-contract.md`
- Test: documentation structure check with `Select-String`

- [ ] **Step 1: Write the contract document**

Create `docs/main-chain-implementation-contract.md` with this content:

```markdown
# Main Chain Implementation Contract

**Authoritative chain:**

goal -> agent_run -> unified facts -> DecisionTickResult -> dispatch gateway -> lane handler -> terminal observation -> next decision

## Invariants

1. Production writes in an agent run must pass through `dispatch_authoritative_packet`.
2. Canonical production packets must come from `load_run_facts_from_snapshot -> evaluate_decision_tick`.
3. B lane may answer, diagnose, defer, or request an action, but it must not queue provider tasks directly.
4. Direct batch APIs are platform/direct-task paths, not agent main-chain paths.
5. A run is complete only when L7 returns `complete`, not merely when current sibling tasks are terminal.

## Allowed Main-Chain Entry Points

- `POST /api/agent-runs`
- `POST /api/agent-runs/{run_id}/actions/continue-step`
- `POST /api/projects/{project_id}/brain/continue`
- terminal task hook in `app/tasks/_shared.py`

## Platform-Only Direct Task Entry Points

- `POST /api/batch/generate-videos`
- `POST /api/batch/generate-images`
- `POST /api/tts/generate`
```

- [ ] **Step 2: Verify contract terms exist**

Run:

```powershell
Select-String -Path docs/main-chain-implementation-contract.md -Pattern 'Authoritative chain','dispatch_authoritative_packet','evaluate_decision_tick','Platform-Only'
```

Expected: four matching lines.

- [ ] **Step 3: Commit**

```powershell
git add docs/main-chain-implementation-contract.md
git commit -m "docs: define authoritative main chain contract"
```

---

## Task 2: P1 Controller Tests

**Files:**

- Create: `tests/unit/test_main_chain_controller.py`
- Create later in Task 3: `app/services/main_chain_controller.py`

- [ ] **Step 1: Write failing tests for L7 policy application**

Create `tests/unit/test_main_chain_controller.py`:

```python
import pytest

from app.services.run_coordination import DecisionTickResult


def packet(status="execute", action="generate_keyframes", dispatchable=True, allowed=True):
    mission = {
        "mission_id": "run-1:generate_keyframes",
        "lane": "c_lane_production",
        "action": action,
        "write_scope": ["tasks", "shot_rows", "agent_events", "agent_runs"],
        "idempotency_key": f"run-1:{action}",
    } if dispatchable else {}
    return DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status=status,
        action=action,
        stage_id=action,
        selected_lane="c_lane_production" if dispatchable else "main_chain",
        dispatchable=dispatchable,
        allowed=allowed,
        reason="ready",
        missing=[],
        fallback_action="",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
        evidence={"project_id": "project-1", "run_id": "run-1"},
        evidence_refs=[],
        candidate_actions=[],
        success_criteria=[],
        budget={"target_count": 1, "estimated_max_credits": 0, "unit": "image_gen"},
        risk={"level": "medium", "failed_task_count": 0, "requires_human": False},
        failure_policy={"fallback_action": "", "retryable": True, "require_human_confirmation": False},
        mission=mission,
    )


@pytest.mark.asyncio
async def test_execute_decision_dispatches_through_gateway(monkeypatch):
    from app.services import main_chain_controller

    observed = {"called": False}

    async def fake_dispatch(db, *, packet, context, handlers):
        observed["called"] = True
        return {"run_id": context.run_id, "queued_count": 1}

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fake_dispatch)

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(),
        context=main_chain_controller.MainChainContext(
            project_id="project-1",
            user_id=7,
            user_tier="pro",
            run_id="run-1",
            run_mode="autopilot",
        ),
        handlers={"generate_keyframes": lambda: {"not": "awaited"}},
    )

    assert observed["called"] is True
    assert result.status == "dispatched"
    assert result.dispatched is True


@pytest.mark.asyncio
async def test_wait_decision_does_not_dispatch(monkeypatch):
    from app.services import main_chain_controller

    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("wait decisions must not dispatch")

    async def fake_update(db, **kwargs):
        assert kwargs["status"] == "running"
        assert kwargs["current_phase"] == "wait_for_tasks"

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fail_dispatch)
    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", lambda *a, **k: None)

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(status="wait", action="wait_for_tasks", dispatchable=False, allowed=False),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={},
    )

    assert result.status == "waiting"
    assert result.dispatched is False


@pytest.mark.asyncio
async def test_complete_decision_marks_run_completed(monkeypatch):
    from app.services import main_chain_controller

    observed = {}

    async def fake_update(db, **kwargs):
        observed.update(kwargs)

    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", lambda *a, **k: None)

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(status="complete", action="writeback_review", dispatchable=False),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={},
    )

    assert observed["status"] == "completed"
    assert observed["current_phase"] == "writeback_review"
    assert result.status == "completed"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/unit/test_main_chain_controller.py -q
```

Expected: fail with `ImportError` or missing `main_chain_controller`.

- [ ] **Step 3: Commit failing test**

```powershell
git add tests/unit/test_main_chain_controller.py
git commit -m "test: specify main chain controller decisions"
```

---

## Task 3: P1 Controller Implementation

**Files:**

- Create: `app/services/main_chain_controller.py`
- Test: `tests/unit/test_main_chain_controller.py`

- [ ] **Step 1: Implement controller types and dispatcher**

Create `app/services/main_chain_controller.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runtime import publish_agent_event, update_agent_run
from app.services.run_coordination import DecisionTickResult
from app.services.run_dispatch_gateway import DispatchGatewayContext, dispatch_authoritative_packet

GatewayHandler = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class MainChainContext:
    project_id: str
    user_id: int
    user_tier: str
    run_id: str
    run_mode: str


@dataclass(frozen=True)
class MainChainResult:
    status: str
    dispatched: bool
    decision: dict[str, Any]
    result: dict[str, Any] | None = None


async def apply_decision_packet(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: MainChainContext,
    handlers: dict[str, GatewayHandler],
) -> MainChainResult:
    if packet.status == "execute" and packet.dispatchable and packet.allowed:
        result = await dispatch_authoritative_packet(
            db,
            packet=packet,
            context=DispatchGatewayContext(
                project_id=context.project_id,
                user_id=context.user_id,
                user_tier=context.user_tier,
                run_id=context.run_id,
                run_mode=context.run_mode,
            ),
            handlers=handlers,
        )
        return MainChainResult("dispatched", True, packet.as_dict(), result)

    if packet.status == "wait":
        await _publish_state(db, packet=packet, context=context, status="running", phase=packet.action or "wait")
        return MainChainResult("waiting", False, packet.as_dict())

    if packet.status == "complete":
        await _publish_state(db, packet=packet, context=context, status="completed", phase=packet.stage_id or "writeback_review")
        return MainChainResult("completed", False, packet.as_dict())

    if packet.status == "recover":
        await _publish_state(db, packet=packet, context=context, status="blocked", phase="recover")
        return MainChainResult("recover", False, packet.as_dict())

    await _publish_state(db, packet=packet, context=context, status="blocked", phase=packet.stage_id or "blocked")
    return MainChainResult("blocked", False, packet.as_dict())


async def _publish_state(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: MainChainContext,
    status: str,
    phase: str,
) -> None:
    update_result = update_agent_run(
        db,
        run_id=context.run_id,
        status=status,
        current_phase=phase,
        summary=packet.reason,
        final_decision=packet.action,
    )
    if hasattr(update_result, "__await__"):
        await update_result

    publish_result = publish_agent_event(
        db,
        run_id=context.run_id,
        project_id=context.project_id,
        user_id=context.user_id,
        source="main_chain",
        event_type="decision",
        phase=phase,
        title="Main chain decision",
        detail=f"{packet.status}: {packet.action}",
        status=status,
        progress=None,
        meta={"decision_packet": packet.as_dict()},
        event_kind="decision",
        visibility="debug",
        summary=f"{packet.status}: {packet.action}",
        reason=packet.reason,
    )
    if hasattr(publish_result, "__await__"):
        await publish_result
```

- [ ] **Step 2: Run controller tests**

Run:

```powershell
python -m pytest tests/unit/test_main_chain_controller.py -q
```

Expected: three tests pass.

- [ ] **Step 3: Run existing gateway tests**

Run:

```powershell
python -m pytest tests/unit/test_run_dispatch_gateway.py -q
```

Expected: existing gateway tests pass.

- [ ] **Step 4: Commit controller**

```powershell
git add app/services/main_chain_controller.py tests/unit/test_main_chain_controller.py
git commit -m "feat: add main chain decision controller"
```

---

## Task 4: P1 Terminal Hook Uses Controller

**Files:**

- Modify: `app/tasks/_shared.py`
- Modify: `app/services/run_coordination.py`
- Modify: `tests/unit/test_task_shared_run_coordination_hook.py`
- Modify: `tests/unit/test_run_coordination.py`

- [ ] **Step 1: Add a test that terminal hook calls controller**

In `tests/unit/test_task_shared_run_coordination_hook.py`, add:

```python
@pytest.mark.asyncio
async def test_terminal_hook_applies_main_chain_controller(monkeypatch):
    from app.tasks import _shared

    observed = {"controller": False}

    async def fake_drain(task_id):
        return None

    async def fake_observe(task_id):
        return {"status": "execute", "action": "generate_keyframes"}

    async def fake_apply(task_id):
        observed["controller"] = True
        return {"status": "dispatched"}

    async def fake_finalize(task_id):
        return None

    monkeypatch.setattr(_shared, "_drain_pending_instruction", fake_drain)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", fake_observe)
    monkeypatch.setattr(_shared, "_apply_main_chain_after_task", fake_apply)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)
    monkeypatch.setattr(_shared, "_publish_async", lambda *a, **k: None)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", lambda *a, **k: None)

    async def persisted():
        return None

    await _shared._persist_and_publish(persisted(), "11111111-1111-1111-1111-111111111111", {"type": "task_complete"})

    assert observed["controller"] is True
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/unit/test_task_shared_run_coordination_hook.py::test_terminal_hook_applies_main_chain_controller -q
```

Expected: fail because `_apply_main_chain_after_task` does not exist.

- [ ] **Step 3: Implement terminal hook adapter**

In `app/tasks/_shared.py`, add this function beside `_observe_run_coordination_after_task`:

```python
async def _apply_main_chain_after_task(task_id: str) -> None:
    try:
        from app.services.main_chain_terminal import continue_main_chain_after_task

        await continue_main_chain_after_task(task_id)
    except Exception as exc:
        LOGGER.warning("Main chain continuation failed for %s: %s", task_id, exc)
```

Then update `_persist_and_publish`:

```python
    if payload.get("type") in ("task_complete", "task_failed"):
        await _drain_pending_instruction(task_id)
        await _observe_run_coordination_after_task(task_id)
        await _apply_main_chain_after_task(task_id)
        await _maybe_finalize_run(task_id)
```

And update `_persist_failed_and_publish`:

```python
    await _drain_pending_instruction(task_id)
    await _observe_run_coordination_after_task(task_id)
    await _apply_main_chain_after_task(task_id)
    await _maybe_finalize_run(task_id)
```

- [ ] **Step 4: Create terminal continuation service test**

Create `tests/unit/test_main_chain_terminal.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_continue_main_chain_after_task_ignores_non_dispatchable(monkeypatch):
    from app.services import main_chain_terminal

    monkeypatch.setattr(main_chain_terminal, "observe_task_terminal_decision_tick", lambda task_id: {"status": "wait", "action": "wait_for_tasks"})

    result = await main_chain_terminal.continue_main_chain_after_task("11111111-1111-1111-1111-111111111111")

    assert result["status"] == "waiting"
```

- [ ] **Step 5: Create `app/services/main_chain_terminal.py`**

Create:

```python
from __future__ import annotations

from typing import Any

from app.db import AsyncSessionLocal
from app.services.main_chain_controller import MainChainContext, apply_decision_packet
from app.services.main_chain_handlers import build_main_chain_handlers
from app.services.run_coordination import (
    DecisionTickResult,
    observe_task_terminal_decision_tick,
    task_run_context_for_main_chain,
)


async def continue_main_chain_after_task(task_id: str) -> dict[str, Any] | None:
    decision_dict = await observe_task_terminal_decision_tick(task_id)
    if not isinstance(decision_dict, dict):
        return None

    async with AsyncSessionLocal() as session:
        context_row = await task_run_context_for_main_chain(session, task_id)
        if not context_row:
            return None
        packet = _packet_from_dict(decision_dict)
        result = await apply_decision_packet(
            session,
            packet=packet,
            context=MainChainContext(
                project_id=str(context_row["project_id"]),
                user_id=int(context_row["user_id"]),
                user_tier=str(context_row.get("user_tier") or "free"),
                run_id=str(context_row["run_id"]),
                run_mode=str(context_row.get("run_mode") or "autopilot"),
            ),
            handlers=build_main_chain_handlers(
                session,
                project_id=str(context_row["project_id"]),
                user_id=int(context_row["user_id"]),
                user_tier=str(context_row.get("user_tier") or "free"),
                run_id=str(context_row["run_id"]),
                run_mode=str(context_row.get("run_mode") or "autopilot"),
            ),
        )
        await session.commit()
        return {"status": result.status, "dispatched": result.dispatched, "decision": result.decision}


def _packet_from_dict(data: dict[str, Any]) -> DecisionTickResult:
    return DecisionTickResult(**data)
```

- [ ] **Step 6: Expose run context helper**

In `app/services/run_coordination.py`, add:

```python
async def task_run_context_for_main_chain(session: AsyncSession, task_id: str) -> dict[str, Any] | None:
    context = await _task_run_context(session, task_id)
    if not context:
        return None
    return {
        **context,
        "user_tier": "free",
        "run_mode": "autopilot",
    }
```

- [ ] **Step 7: Run hook and coordination tests**

Run:

```powershell
python -m pytest tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_run_coordination.py tests/unit/test_main_chain_terminal.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add app/tasks/_shared.py app/services/run_coordination.py app/services/main_chain_terminal.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_main_chain_terminal.py
git commit -m "feat: continue main chain after terminal tasks"
```

---

## Task 5: P1 Handler Registry

**Files:**

- Create: `app/services/main_chain_handlers.py`
- Modify: `tests/unit/test_main_chain_controller.py`

- [ ] **Step 1: Add handler registry test**

Append to `tests/unit/test_main_chain_controller.py`:

```python
def test_handler_registry_exposes_production_actions():
    from app.services.main_chain_handlers import build_main_chain_handlers

    handlers = build_main_chain_handlers(
        object(),
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        run_id="run-1",
        run_mode="autopilot",
    )

    assert "generate_keyframes" in handlers
    assert "generate_videos" in handlers
    assert "plan_final_edit" in handlers
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/unit/test_main_chain_controller.py::test_handler_registry_exposes_production_actions -q
```

Expected: fail because module is missing.

- [ ] **Step 3: Implement registry as an adapter**

Create `app/services/main_chain_handlers.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[], Awaitable[dict[str, Any]]]


def build_main_chain_handlers(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    user_tier: str,
    run_id: str,
    run_mode: str,
) -> dict[str, Handler]:
    from app.routes import workbench

    async def generate_keyframes() -> dict[str, Any]:
        before = await workbench._brain_for_gateway_handler(db, project_id=project_id, user_id=user_id)
        return await workbench._continue_generate_keyframes(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
        )

    async def generate_videos() -> dict[str, Any]:
        before = await workbench._brain_for_gateway_handler(db, project_id=project_id, user_id=user_id)
        return await workbench._continue_generate_videos(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
        )

    async def plan_final_edit() -> dict[str, Any]:
        before = await workbench._brain_for_gateway_handler(db, project_id=project_id, user_id=user_id)
        return await workbench._continue_plan_final_edit(
            db,
            project_id=project_id,
            user_id=user_id,
            before=before,
            run_id=run_id,
        )

    return {
        "generate_keyframes": generate_keyframes,
        "generate_videos": generate_videos,
        "plan_final_edit": plan_final_edit,
    }
```

- [ ] **Step 4: Add helper in `workbench.py`**

Add near other brain helpers:

```python
async def _brain_for_gateway_handler(db: AsyncSession, *, project_id: str, user_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """SELECT shot_index, prompt, duration, status, selected,
                      character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                      image_candidates_json, selected_image,
                      video_variants_json, selected_video, last_error,
                      created_at, updated_at
               FROM shot_rows
               WHERE project_id = :project_id AND user_id = :user_id
               ORDER BY shot_index ASC"""
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    rows = [_normalize_shot_row_row(row, project_id=project_id) for row in result.fetchall()]
    return build_project_brain(project_id, operational_shots=rows)
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/unit/test_main_chain_controller.py tests/unit/test_project_continue.py -q
```

Expected: selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add app/services/main_chain_handlers.py app/routes/workbench.py tests/unit/test_main_chain_controller.py
git commit -m "feat: register main chain production handlers"
```

---

## Task 6: P2 Canonical Packets For Workbench Dispatch

**Files:**

- Modify: `app/routes/workbench.py`
- Modify: `tests/unit/test_project_continue.py`

- [ ] **Step 1: Replace compatibility assertion with canonical packet test**

In `tests/unit/test_project_continue.py`, add:

```python
@pytest.mark.asyncio
async def test_dispatch_production_action_uses_canonical_decision_tick(monkeypatch):
    from app.routes import workbench

    observed = {}

    async def fake_load(db, *, run_id, user_id):
        observed["loaded_run_id"] = run_id
        return object()

    def fake_evaluate(facts):
        return workbench.DecisionTickResult(
            packet_version="main_run_chain_phase1",
            status="execute",
            action="generate_keyframes",
            stage_id="generate_keyframes",
            selected_lane="c_lane_production",
            dispatchable=True,
            allowed=True,
            reason="canonical",
            missing=[],
            fallback_action="",
            active_task_count=0,
            failed_task_count=0,
            allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
            evidence={},
            evidence_refs=[],
            candidate_actions=[],
            success_criteria=[],
            budget={},
            risk={},
            failure_policy={},
            mission={
                "mission_id": "run-1:generate_keyframes",
                "lane": "c_lane_production",
                "action": "generate_keyframes",
                "write_scope": ["tasks"],
                "idempotency_key": "run-1:generate_keyframes",
            },
        )

    async def fake_dispatch(db, *, packet, context, handlers):
        observed["packet_reason"] = packet.reason
        return {"run_id": context.run_id, "decision_packet": packet.as_dict()}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "evaluate_decision_tick", fake_evaluate)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="generate_keyframes",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_keyframe_count": 1}},
        name="project-1",
        run_id="run-1",
        run_mode="autopilot",
        result={},
        image_unit_price=1,
        video_unit_price=1,
    )

    assert observed["loaded_run_id"] == "run-1"
    assert observed["packet_reason"] == "canonical"
    assert result["decision_packet"]["reason"] == "canonical"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/unit/test_project_continue.py::test_dispatch_production_action_uses_canonical_decision_tick -q
```

Expected: fail because `_dispatch_production_action` still uses compatibility packet.

- [ ] **Step 3: Import canonical functions**

In `app/routes/workbench.py`, update imports:

```python
from app.services.run_coordination import (
    DecisionTickResult,
    evaluate_decision_tick,
    load_run_facts_from_snapshot,
)
```

- [ ] **Step 4: Change `_dispatch_production_action` packet creation**

Replace:

```python
    packet = _build_compatibility_decision_packet(...)
```

with:

```python
    facts = await load_run_facts_from_snapshot(db, run_id=run_id, user_id=user_id)
    if facts is None:
        packet = _build_compatibility_decision_packet(
            project_id=project_id,
            run_id=run_id,
            action=action,
            before=before,
            image_unit_price=image_unit_price,
            video_unit_price=video_unit_price,
            provider=provider,
        )
    else:
        packet = evaluate_decision_tick(facts)
        if packet.action != action:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "decision_action_mismatch",
                    "requested_action": action,
                    "canonical_action": packet.action,
                    "status": packet.status,
                },
            )
```

- [ ] **Step 5: Run project continue tests**

Run:

```powershell
python -m pytest tests/unit/test_project_continue.py -q
```

Expected: tests pass after updating old compatibility expectations to accept canonical path or explicit fallback path.

- [ ] **Step 6: Commit**

```powershell
git add app/routes/workbench.py tests/unit/test_project_continue.py
git commit -m "feat: use canonical decision packets for workbench dispatch"
```

---

## Task 7: P2 Restrict B Lane Writes

**Files:**

- Modify: `app/services/agent_action_executor.py`
- Modify: `app/services/agent_control_registry.py`
- Modify: `app/routes/agent_runs.py`
- Modify: `tests/unit/test_agent_action_executor.py`
- Modify: `tests/unit/test_agent_runs_route_contract.py`

- [ ] **Step 1: Add B lane intent-only tests**

In `tests/unit/test_agent_action_executor.py`, replace production-dispatch expectations with:

```python
@pytest.mark.asyncio
async def test_production_action_returns_requested_action_intent():
    result = await dispatch_agent_action(
        _context("generate_videos"),
        execute_continue_project=lambda body: None,
    )

    assert result.status == "requested_action"
    assert result.executor == "ActionIntentExecutor"
    assert result.result["requested_action"] == "generate_videos"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/unit/test_agent_action_executor.py::test_production_action_returns_requested_action_intent -q
```

Expected: fail because current executor returns `None` or dispatches selected actions.

- [ ] **Step 3: Split registry action sets**

In `app/services/agent_control_registry.py`, add:

```python
HUMAN_REQUESTABLE_ACTIONS: set[str] = {
    "status_query",
    "generate_story_plan",
    "plan_visual_assets",
    "generate_keyframes",
    "generate_videos",
    "plan_final_edit",
}

HUMAN_DIRECT_EXECUTABLE_ACTIONS: set[str] = {
    "status_query",
}

HUMAN_EXECUTABLE_ACTIONS = HUMAN_REQUESTABLE_ACTIONS
```

- [ ] **Step 4: Change `dispatch_agent_action` production behavior**

In `app/services/agent_action_executor.py`, before `return None`, add:

```python
    if context.action in {"generate_story_plan", "plan_visual_assets", "generate_keyframes", "generate_videos", "plan_final_edit"}:
        return ActionExecutionResult(
            status="requested_action",
            executor="ActionIntentExecutor",
            audit_action="agent_run.action_intent_requested",
            result={"requested_action": context.action, "continue_body": context.continue_body},
        )
```

Remove direct calls to `execute_continue_project` and `execute_final_edit` for production actions from this executor.

- [ ] **Step 5: Route requested action through canonical path**

In `app/routes/agent_runs.py`, where `execution.status == "requested_action"`, call the canonical continue route:

```python
if execution and execution.status == "requested_action":
    requested = dict(execution.result or {})
    continue_body = dict(requested.get("continue_body") or continue_body)
    continue_body["action"] = str(requested["requested_action"])
    result = await execute_continue_project(continue_body)
    ...
```

Then ensure `execute_continue_project` goes through `continue_project_brain`, which Task 6 made canonical for production dispatch.

- [ ] **Step 6: Run B lane tests**

Run:

```powershell
python -m pytest tests/unit/test_agent_action_executor.py tests/unit/test_agent_runs_route_contract.py -q
```

Expected: all selected tests pass after contract updates.

- [ ] **Step 7: Commit**

```powershell
git add app/services/agent_action_executor.py app/services/agent_control_registry.py app/routes/agent_runs.py tests/unit/test_agent_action_executor.py tests/unit/test_agent_runs_route_contract.py
git commit -m "refactor: restrict b lane to action intent and diagnostics"
```

---

## Task 8: P3 Finalization Defers To L7

**Files:**

- Modify: `app/tasks/_shared.py`
- Modify: `tests/unit/test_task_shared_run_coordination_hook.py`

- [ ] **Step 1: Add test that executable next decision prevents premature completion**

In `tests/unit/test_task_shared_run_coordination_hook.py`, add:

```python
@pytest.mark.asyncio
async def test_maybe_finalize_run_skips_when_main_chain_dispatched(monkeypatch):
    from app.tasks import _shared

    observed = {"finalize": False}

    async def fake_apply(task_id):
        return {"status": "dispatched", "dispatched": True}

    async def fake_finalize(task_id):
        observed["finalize"] = True

    monkeypatch.setattr(_shared, "_drain_pending_instruction", lambda task_id: None)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", lambda task_id: None)
    monkeypatch.setattr(_shared, "_apply_main_chain_after_task", fake_apply)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)
    monkeypatch.setattr(_shared, "_publish_async", lambda *a, **k: None)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", lambda *a, **k: None)

    async def persisted():
        return None

    await _shared._persist_and_publish(persisted(), "11111111-1111-1111-1111-111111111111", {"type": "task_complete"})

    assert observed["finalize"] is False
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/unit/test_task_shared_run_coordination_hook.py::test_maybe_finalize_run_skips_when_main_chain_dispatched -q
```

Expected: fail because `_maybe_finalize_run` still runs unconditionally.

- [ ] **Step 3: Gate finalization on controller result**

In `_persist_and_publish`, change terminal block:

```python
    if payload.get("type") in ("task_complete", "task_failed"):
        await _drain_pending_instruction(task_id)
        await _observe_run_coordination_after_task(task_id)
        chain_result = await _apply_main_chain_after_task(task_id)
        if not isinstance(chain_result, dict) or not chain_result.get("dispatched"):
            await _maybe_finalize_run(task_id)
```

Make `_apply_main_chain_after_task` return the service result:

```python
        return await continue_main_chain_after_task(task_id)
```

Apply the same pattern in `_persist_failed_and_publish`.

- [ ] **Step 4: Run hook tests**

Run:

```powershell
python -m pytest tests/unit/test_task_shared_run_coordination_hook.py -q
```

Expected: selected hook tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/tasks/_shared.py tests/unit/test_task_shared_run_coordination_hook.py
git commit -m "fix: prevent premature run finalization after main chain dispatch"
```

---

## Task 9: P3 Mark Direct APIs As Platform-Only

**Files:**

- Modify: `app/main.py`
- Modify: `docs/main-chain-implementation-contract.md`
- Test: existing direct API tests if present, otherwise route metadata check

- [ ] **Step 1: Add response metadata to direct APIs**

In each direct endpoint response in `app/main.py`, include:

```python
main_chain_path="platform_direct_task"
```

If Pydantic response models do not allow the field, add a `meta` dict field to the response model used by these endpoints.

- [ ] **Step 2: Add doc contract line**

In `docs/main-chain-implementation-contract.md`, add under platform-only APIs:

```markdown
These endpoints may queue tasks directly for manual SaaS operations. They must not be used by agent main-chain routes to perform autonomous production.
```

- [ ] **Step 3: Verify no agent route calls direct APIs**

Run:

```powershell
rg -n "batch/generate|generate-images|generate-videos|tts/generate|submit_batch_tasks|submit_single_task" app/routes app/services
```

Expected: `submit_batch_tasks` and `submit_single_task` appear in platform service/main paths only, not in `app/routes/agent_runs.py`.

- [ ] **Step 4: Commit**

```powershell
git add app/main.py docs/main-chain-implementation-contract.md
git commit -m "docs: mark direct generation APIs as platform-only"
```

---

## Task 10: P4 Deep Integration Tests

**Files:**

- Create: `tests/integration/test_main_chain_loop.py`
- Modify: `tests/integration/test_agent_events.py`

- [ ] **Step 1: Create DB-backed loop test skeleton**

Create `tests/integration/test_main_chain_loop.py`:

```python
import os

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not available",
)


@pytest.mark.asyncio
async def test_terminal_keyframe_task_dispatches_next_video_stage(db_session, monkeypatch):
    from app.services import main_chain_handlers
    from app.tasks import _shared

    observed = {"video_handler": False}

    async def fake_handlers(db, **kwargs):
        async def generate_videos():
            observed["video_handler"] = True
            return {"queued_count": 1}

        return {"generate_videos": generate_videos}

    monkeypatch.setattr(main_chain_handlers, "build_main_chain_handlers", fake_handlers)

    task_id = await seed_agent_run_with_done_keyframe_and_pending_video(db_session)

    async def persisted():
        return None

    await _shared._persist_and_publish(persisted(), task_id, {"type": "task_complete"})

    assert observed["video_handler"] is True
```

- [ ] **Step 2: Add seed helper in the same test file**

Add concrete DB inserts matching existing integration style:

```python
async def seed_agent_run_with_done_keyframe_and_pending_video(db_session):
    # Use existing integration factories if available in tests/conftest.py.
    # If no factories exist, insert project, agent_run, shot_rows, and tasks rows directly with SQLAlchemy text().
    ...
```

Replace the ellipsis with the exact helper pattern already used in `tests/integration/test_agent_events.py`.

- [ ] **Step 3: Run integration test with DB**

Run:

```powershell
python -m pytest tests/integration/test_main_chain_loop.py -q -rs
```

Expected with DB: test passes.  
Expected without DB: skipped with `TEST_DATABASE_URL is not available`.

- [ ] **Step 4: Extend existing agent events test**

In `tests/integration/test_agent_events.py`, after the existing decision tick assertion, add assertions for:

```python
assert packet["packet_version"] == "main_run_chain_phase1"
assert packet["status"] in {"execute", "wait", "recover", "blocked", "complete"}
```

- [ ] **Step 5: Commit**

```powershell
git add tests/integration/test_main_chain_loop.py tests/integration/test_agent_events.py
git commit -m "test: cover main chain terminal continuation loop"
```

---

## Task 11: P4 Documentation Sync

**Files:**

- Modify: `docs/main-chain-function-tree-diagnosis.md`
- Modify: `docs/main-chain-7-layer-code-verification.md`
- Modify: `docs/main-chain-implementation-contract.md`

- [ ] **Step 1: Update diagnosis status**

In `docs/main-chain-7-layer-code-verification.md`, add a new section:

```markdown
## Implementation Alignment Status

The original diagnosis found that L7 was observational. After implementation, terminal observation calls the main-chain controller, and executable packets are routed back through `dispatch_authoritative_packet`.
```

- [ ] **Step 2: Update function tree**

In `docs/main-chain-function-tree-diagnosis.md`, change the current-code chain to:

```text
Terminal Hook
-> observe_task_terminal_decision_tick
-> main_chain_controller.apply_decision_packet
-> dispatch_authoritative_packet OR wait/recover/blocked/complete
```

- [ ] **Step 3: Verify docs mention all layers**

Run:

```powershell
Select-String -Path docs/main-chain-function-tree-diagnosis.md,docs/main-chain-7-layer-code-verification.md,docs/main-chain-implementation-contract.md -Pattern 'L1','L2','L3','L4','L5','L6','L7','dispatch_authoritative_packet'
```

Expected: matches in all main-chain docs.

- [ ] **Step 4: Commit**

```powershell
git add docs/main-chain-function-tree-diagnosis.md docs/main-chain-7-layer-code-verification.md docs/main-chain-implementation-contract.md
git commit -m "docs: align main chain documentation with implementation"
```

---

## Final Verification Matrix

Run after all tasks:

```powershell
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_main_chain_controller.py tests/unit/test_main_chain_terminal.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_project_continue.py tests/unit/test_agent_action_executor.py tests/unit/test_agent_runs_route_contract.py -q
```

Expected:

```text
all selected unit tests passed
```

Run integration tests:

```powershell
python -m pytest tests/integration/test_agent_events.py tests/integration/test_main_chain_loop.py -q -rs
```

Expected with `TEST_DATABASE_URL`:

```text
integration tests passed
```

Expected without `TEST_DATABASE_URL`:

```text
database-backed tests skipped with explicit reason
```

Run route/API drift check:

```powershell
rg -n "_build_compatibility_decision_packet|director_export_preview\\(|submit_batch_tasks|submit_single_task|celery_app.send_task" app/routes app/services app/tasks
```

Expected interpretation:

- `_build_compatibility_decision_packet` appears only in explicitly documented compatibility fallback.
- `director_export_preview(` is not called directly from B lane write execution.
- `submit_batch_tasks` and `submit_single_task` appear only in platform direct-task paths.
- `celery_app.send_task` appears in C-lane handlers or direct platform APIs, not in B lane.

Run docs check:

```powershell
Select-String -Path docs/main-chain-implementation-contract.md,docs/main-chain-7-layer-code-verification.md -Pattern 'authoritative','platform/direct-task','L7','dispatch_authoritative_packet'
```

Expected: each concept appears in docs.

---

## Rollback And Risk Control

If P1 terminal continuation creates duplicate dispatch:

1. Disable active continuation by making `_apply_main_chain_after_task` call observe-only.
2. Keep decision event writing intact.
3. Re-run `tests/unit/test_run_coordination.py` and `tests/unit/test_task_shared_run_coordination_hook.py`.

If canonical packet conversion blocks workbench actions:

1. Keep fallback to `_build_compatibility_decision_packet` only when `load_run_facts_from_snapshot` returns `None`.
2. Add an event with `source="compatibility_fallback"` so fallback use is visible.
3. Treat each fallback event as a bug to remove.

If B lane route contract breaks UI behavior:

1. Preserve status and diagnostic answers.
2. Convert production actions into requested action intent.
3. Route requested action through `continue_project_brain`, then through canonical packet and gateway.

---

## Definition Of Done

The project is aligned when all are true:

1. A terminal task can trigger the next safe production action without a user click.
2. The next action is represented as `DecisionTickResult`.
3. Production actions dispatch through `dispatch_authoritative_packet`.
4. B lane cannot directly queue provider work or final edit output.
5. Direct task APIs are documented and tested as platform-only.
6. `_maybe_finalize_run` does not complete a run while L7 can still execute another stage.
7. Docs and tests describe the same 7-layer chain.
