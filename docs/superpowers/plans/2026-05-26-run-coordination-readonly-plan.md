# Run Coordination Readonly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first narrow Run Coordination Layer slice: a read-only decision tick that unifies A/B/C lane facts and records what the system should do next without dispatching new work.

**Architecture:** Add `app/services/run_coordination.py` as a coordinator boundary around the existing state-machine policy in `app/services/agent_run_state_machine.py`. The coordinator consumes normalized facts from snapshots or pure test fixtures, emits a structured decision packet, and can be called after task terminal events only to log a recommendation. It does not replace `project_brain`, `agent_runs`, or `VideoProductionRunner`, and it does not auto-dispatch in this slice.

**Tech Stack:** Python 3.11, FastAPI service modules, SQLAlchemy async sessions, existing `agent_run_state_machine`, existing `agent_run_snapshot`, pytest.

---

## File Structure

- Create `app/services/run_coordination.py`
  - Owns `UnifiedRunFacts`, `DecisionTickResult`, pure `evaluate_decision_tick`, snapshot adapter, and read-only task-terminal observer.
  - Depends on `agent_run_state_machine` for deterministic production policy.
  - Depends on `agent_run_snapshot` only in the async adapter, not in the pure decision function.

- Create `tests/unit/test_run_coordination.py`
  - Pure unit tests for decision tick behavior with no database.
  - Locks the first desired Codex-style loop behavior: decide, wait, recover, complete.

- Modify `app/tasks/_shared.py`
  - Adds `_observe_run_coordination_after_task(task_id)`.
  - Calls the observer after terminal task publish and before `_maybe_finalize_run(task_id)`.
  - Keeps current finalization behavior unchanged for this slice.

- Create `tests/unit/test_task_shared_run_coordination_hook.py`
  - Unit test proving the terminal task path calls the coordination observer before finalization.
  - Uses monkeypatches and does not require Redis or database.

## Scope Boundary

This plan intentionally does not implement automatic continuation. The first slice only answers and records:

```text
given unified facts -> what should the run do next, and why?
```

Automatic dispatch comes after the logged recommendations are correct in real runs.

## Decision Packet Contract

The first decision packet must contain these fields:

```python
{
    "status": "execute | wait | recover | blocked | complete",
    "action": "generate_story_plan | generate_keyframes | generate_videos | plan_final_edit | wait_for_tasks | ...",
    "stage_id": "state-machine stage id",
    "allowed": True,
    "reason": "human-readable policy reason",
    "missing": [],
    "fallback_action": "",
    "active_task_count": 0,
    "failed_task_count": 0,
    "evidence": {
        "shot_count": 0,
        "selected_image_count": 0,
        "selected_video_count": 0,
        "final_video_url": "",
    },
    "candidate_actions": [],
    "success_criteria": [],
}
```

---

### Task 1: Pure Coordination Tests

**Files:**
- Create: `tests/unit/test_run_coordination.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_run_coordination.py` with this content:

```python
from app.services.run_coordination import UnifiedRunFacts, evaluate_decision_tick


def facts(*, shots=None, tasks=None, production_run=None, run=None):
    return UnifiedRunFacts(
        run=run or {"run_id": "run-1", "project_id": "project-1", "goal": "make a short drama"},
        shots=shots or [],
        tasks=tasks or [],
        production_run=production_run or {},
        source="unit_test",
    )


def test_empty_run_executes_story_plan():
    decision = evaluate_decision_tick(facts())

    assert decision.status == "execute"
    assert decision.action == "generate_story_plan"
    assert decision.stage_id == "generate_story_plan"
    assert decision.allowed is True
    assert decision.evidence["shot_count"] == 0
    assert "Generate script" in decision.success_criteria[0]


def test_shots_without_images_execute_keyframes():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}])
    )

    assert decision.status == "execute"
    assert decision.action == "generate_keyframes"
    assert decision.stage_id == "generate_keyframes"
    assert decision.allowed is True
    assert decision.evidence["shot_count"] == 1


def test_selected_images_execute_videos():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": ""}])
    )

    assert decision.status == "execute"
    assert decision.action == "generate_videos"
    assert decision.stage_id == "generate_videos"
    assert decision.allowed is True
    assert decision.evidence["selected_image_count"] == 1


def test_selected_videos_execute_final_edit():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": "video.mp4"}])
    )

    assert decision.status == "execute"
    assert decision.action == "plan_final_edit"
    assert decision.stage_id == "final_cut"
    assert decision.allowed is True
    assert decision.evidence["selected_video_count"] == 1


def test_active_tasks_wait_instead_of_dispatching_more_work():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}],
            tasks=[{"task_id": "task-1", "task_type": "image_gen", "status": "running"}],
        )
    )

    assert decision.status == "wait"
    assert decision.action == "wait_for_tasks"
    assert decision.active_task_count == 1
    assert decision.allowed is False
    assert decision.reason == "Active production tasks are still running."


def test_failed_keyframe_task_routes_to_recovery():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}],
            tasks=[{"task_id": "task-1", "task_type": "image_gen", "status": "failed", "error_message": "provider failed"}],
        )
    )

    assert decision.status == "recover"
    assert decision.action == "generate_keyframes"
    assert decision.failed_task_count == 1
    assert decision.allowed is False
    assert decision.fallback_action == "request_human_confirmation"


def test_final_video_marks_run_complete():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": "video.mp4"}],
            production_run={"status": "completed", "final_video_url": "https://cdn.test/final.mp4"},
        )
    )

    assert decision.status == "complete"
    assert decision.action == "writeback_review"
    assert decision.allowed is True
    assert decision.evidence["final_video_url"] == "https://cdn.test/final.mp4"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/test_run_coordination.py -q
```

Expected:

```text
ERROR tests/unit/test_run_coordination.py
ModuleNotFoundError: No module named 'app.services.run_coordination'
```

- [ ] **Step 3: Commit the failing tests if git is available**

Run:

```bash
git status --short
git add tests/unit/test_run_coordination.py
git commit -m "test: define read-only run coordination decisions"
```

Expected:

```text
[branch ...] test: define read-only run coordination decisions
```

If `git status --short` fails because `.git` points to an unavailable gitdir, record the failure in the implementation notes and continue without committing.

---

### Task 2: Read-Only Coordination Service

**Files:**
- Create: `app/services/run_coordination.py`
- Test: `tests/unit/test_run_coordination.py`

- [ ] **Step 1: Add the service implementation**

Create `app/services/run_coordination.py` with this content:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.services.agent_run_snapshot import get_agent_run_snapshot
from app.services.agent_run_state_machine import (
    ACTIVE_STATUSES,
    TERMINAL_FAILED,
    evaluate_action_gate,
    evaluate_production_stages,
    recommend_next_action,
)


@dataclass(frozen=True)
class UnifiedRunFacts:
    run: dict[str, Any]
    shots: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    production_run: dict[str, Any]
    source: str = "unknown"


@dataclass(frozen=True)
class DecisionTickResult:
    status: str
    action: str
    stage_id: str
    allowed: bool
    reason: str
    missing: list[str]
    fallback_action: str
    active_task_count: int
    failed_task_count: int
    evidence: dict[str, Any]
    candidate_actions: list[dict[str, Any]]
    success_criteria: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_decision_tick(facts: UnifiedRunFacts) -> DecisionTickResult:
    """Return the next read-only coordination decision for a run."""
    active_tasks = [task for task in facts.tasks if str(task.get("status") or "") in ACTIVE_STATUSES]
    failed_tasks = [task for task in facts.tasks if str(task.get("status") or "") in TERMINAL_FAILED]
    evidence = _build_evidence(facts)
    candidates = _candidate_actions(facts)

    if active_tasks:
        return DecisionTickResult(
            status="wait",
            action="wait_for_tasks",
            stage_id="",
            allowed=False,
            reason="Active production tasks are still running.",
            missing=[],
            fallback_action="",
            active_task_count=len(active_tasks),
            failed_task_count=len(failed_tasks),
            evidence=evidence,
            candidate_actions=candidates,
            success_criteria=["Wait until all active tasks reach a terminal status."],
        )

    recommendation = recommend_next_action(
        shots=facts.shots,
        tasks=facts.tasks,
        production_run=facts.production_run,
    )
    action = str(recommendation.get("action") or "")
    gate = evaluate_action_gate(
        action,
        shots=facts.shots,
        tasks=facts.tasks,
        production_run=facts.production_run,
    )
    stage_id = str(gate.get("stage_id") or recommendation.get("stage_id") or "")
    missing = [str(item) for item in gate.get("missing") or []]

    if failed_tasks and not _has_enough_output_to_continue(facts, action):
        recovery_action = str(gate.get("recovery") or recommendation.get("action") or "recover_failed_tasks")
        return DecisionTickResult(
            status="recover",
            action=recovery_action,
            stage_id=stage_id,
            allowed=False,
            reason=str(gate.get("reason") or "A terminal task failure requires recovery before continuing."),
            missing=missing,
            fallback_action="request_human_confirmation",
            active_task_count=0,
            failed_task_count=len(failed_tasks),
            evidence=evidence,
            candidate_actions=candidates,
            success_criteria=_success_criteria(recovery_action),
        )

    if recommendation.get("status") == "completed" and evidence["final_video_url"]:
        return DecisionTickResult(
            status="complete",
            action=action or "writeback_review",
            stage_id=stage_id or "writeback_review",
            allowed=True,
            reason="Final video artifact is available and production policy is complete.",
            missing=[],
            fallback_action="",
            active_task_count=0,
            failed_task_count=len(failed_tasks),
            evidence=evidence,
            candidate_actions=candidates,
            success_criteria=["Final video URL is present.", "Run can be summarized for the user."],
        )

    if not bool(gate.get("allowed", recommendation.get("allowed", False))):
        return DecisionTickResult(
            status="blocked",
            action=action,
            stage_id=stage_id,
            allowed=False,
            reason=str(gate.get("reason") or recommendation.get("reason") or "Runtime gate blocked the action."),
            missing=missing,
            fallback_action=str(gate.get("recovery") or "request_human_confirmation"),
            active_task_count=0,
            failed_task_count=len(failed_tasks),
            evidence=evidence,
            candidate_actions=candidates,
            success_criteria=_success_criteria(action),
        )

    return DecisionTickResult(
        status="execute",
        action=action,
        stage_id=stage_id,
        allowed=True,
        reason=str(recommendation.get("reason") or gate.get("reason") or ""),
        missing=[],
        fallback_action=str(gate.get("recovery") or ""),
        active_task_count=0,
        failed_task_count=len(failed_tasks),
        evidence=evidence,
        candidate_actions=candidates,
        success_criteria=_success_criteria(action),
    )


async def load_run_facts_from_snapshot(db: AsyncSession, *, run_id: str, user_id: int) -> UnifiedRunFacts | None:
    snapshot = await get_agent_run_snapshot(db, run_id=run_id, user_id=user_id)
    if not snapshot:
        return None
    return UnifiedRunFacts(
        run=dict(snapshot.get("run") or {}),
        shots=list(snapshot.get("ledger", {}).get("shots") or snapshot.get("shots") or []),
        tasks=list(snapshot.get("tasks") or []),
        production_run=dict(snapshot.get("outputs", {}).get("production_run") or {}),
        source="agent_run_snapshot",
    )


async def observe_task_terminal_decision_tick(task_id: str) -> dict[str, Any] | None:
    """Log a read-only coordination decision after a task reaches terminal state."""
    async with AsyncSessionLocal() as session:
        context = await _task_run_context(session, task_id)
        if not context:
            return None
        facts = await load_run_facts_from_snapshot(
            session,
            run_id=str(context["run_id"]),
            user_id=int(context["user_id"]),
        )
        if not facts:
            return None
        decision = evaluate_decision_tick(facts)
        await _insert_decision_event(session, context=context, task_id=task_id, decision=decision)
        await session.commit()
        return decision.as_dict()


async def _task_run_context(session: AsyncSession, task_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT task_id, run_id, project_id, user_id
                FROM tasks
                WHERE task_id = CAST(:task_id AS UUID)
                  AND run_id IS NOT NULL
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _insert_decision_event(
    session: AsyncSession,
    *,
    context: dict[str, Any],
    task_id: str,
    decision: DecisionTickResult,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO agent_events (
                run_id, project_id, task_id, user_id, source,
                event_type, phase, title, detail, status, progress, meta
            )
            VALUES (
                CAST(:run_id AS UUID), :project_id, CAST(:task_id AS UUID), :user_id, 'coordinator',
                'decision', 'decision_tick', 'Run coordination decision tick',
                :detail, :status, NULL, CAST(:meta AS JSONB)
            )
            """
        ),
        {
            "run_id": str(context["run_id"]),
            "project_id": str(context["project_id"]),
            "task_id": task_id,
            "user_id": int(context["user_id"]),
            "detail": f"{decision.status}: {decision.action}",
            "status": decision.status,
            "meta": json.dumps({"decision_tick": decision.as_dict()}, ensure_ascii=False, default=str),
        },
    )


def _candidate_actions(facts: UnifiedRunFacts) -> list[dict[str, Any]]:
    rows = evaluate_production_stages(
        shots=facts.shots,
        tasks=facts.tasks,
        production_run=facts.production_run,
    )
    return [
        {
            "action": row["action"],
            "stage_id": row["id"],
            "status": row["status"],
            "allowed": bool(row.get("gate", {}).get("allowed")),
            "reason": str(row.get("gate", {}).get("reason") or ""),
        }
        for row in rows
        if row["status"] in {"pending", "blocked", "running"}
    ][:3]


def _build_evidence(facts: UnifiedRunFacts) -> dict[str, Any]:
    return {
        "run_id": str(facts.run.get("run_id") or facts.run.get("id") or ""),
        "project_id": str(facts.run.get("project_id") or ""),
        "goal": str(facts.run.get("goal") or ""),
        "shot_count": len(facts.shots),
        "selected_image_count": sum(1 for shot in facts.shots if shot.get("selected_image")),
        "selected_video_count": sum(1 for shot in facts.shots if shot.get("selected_video")),
        "final_video_url": str(facts.production_run.get("final_video_url") or ""),
        "source": facts.source,
    }


def _has_enough_output_to_continue(facts: UnifiedRunFacts, action: str) -> bool:
    if action == "plan_final_edit":
        return any(shot.get("selected_video") for shot in facts.shots)
    if action == "generate_videos":
        return any(shot.get("selected_image") for shot in facts.shots)
    return False


def _success_criteria(action: str) -> list[str]:
    return {
        "generate_story_plan": ["Generate script/storyboard rows.", "Persist shot_rows for downstream media generation."],
        "generate_keyframes": ["Generate selected_image for target shot rows.", "Write image candidates and review evidence."],
        "generate_videos": ["Generate selected_video for ready shot rows.", "Write video variants and provider evidence."],
        "plan_final_edit": ["Create final edit plan from selected videos.", "Produce or prepare final video export."],
        "writeback_review": ["Summarize final artifacts and update run completion evidence."],
    }.get(action, ["Record the decision outcome and expose the next observable state."])
```

- [ ] **Step 2: Run pure coordination tests**

Run:

```bash
python -m pytest tests/unit/test_run_coordination.py -q
```

Expected:

```text
7 passed
```

- [ ] **Step 3: If tests expose an existing snapshot shape mismatch, adjust only the adapter**

If `load_run_facts_from_snapshot` fails in later integration because `snapshot["ledger"]["shots"]` is absent, change only this line:

```python
shots=list(snapshot.get("ledger", {}).get("shots") or snapshot.get("shots") or []),
```

to:

```python
shots=list(snapshot.get("evidence_layers", {}).get("state_machine_flow", {}).get("shots") or snapshot.get("ledger", {}).get("shots") or []),
```

Then rerun:

```bash
python -m pytest tests/unit/test_run_coordination.py -q
```

Expected:

```text
7 passed
```

- [ ] **Step 4: Commit the service if git is available**

Run:

```bash
git status --short
git add app/services/run_coordination.py tests/unit/test_run_coordination.py
git commit -m "feat: add read-only run coordination decision tick"
```

Expected:

```text
[branch ...] feat: add read-only run coordination decision tick
```

If `git status --short` fails because `.git` points to an unavailable gitdir, record the failure in the implementation notes and continue without committing.

---

### Task 3: Terminal Task Observer Hook

**Files:**
- Modify: `app/tasks/_shared.py`
- Create: `tests/unit/test_task_shared_run_coordination_hook.py`

- [ ] **Step 1: Write the failing hook-order test**

Create `tests/unit/test_task_shared_run_coordination_hook.py` with this content:

```python
import pytest

from app.tasks import _shared


@pytest.mark.asyncio
async def test_terminal_publish_observes_coordination_before_finalization(monkeypatch):
    calls = []

    async def fake_persist():
        calls.append("persist")

    async def fake_publish(task_id, payload):
        calls.append(("publish", task_id, payload["type"]))

    async def fake_publish_agent(task_id, payload):
        calls.append(("agent_event", task_id, payload["type"]))

    async def fake_drain(task_id):
        calls.append(("drain", task_id))

    async def fake_observe(task_id):
        calls.append(("coordination", task_id))

    async def fake_finalize(task_id):
        calls.append(("finalize", task_id))

    monkeypatch.setattr(_shared, "_publish_async", fake_publish)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", fake_publish_agent)
    monkeypatch.setattr(_shared, "_drain_pending_instruction", fake_drain)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", fake_observe)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)

    await _shared._persist_and_publish(fake_persist(), "task-1", {"type": "task_complete"})

    assert calls == [
        "persist",
        ("publish", "task-1", "task_complete"),
        ("agent_event", "task-1", "task_complete"),
        ("drain", "task-1"),
        ("coordination", "task-1"),
        ("finalize", "task-1"),
    ]
```

- [ ] **Step 2: Run the hook test to verify it fails**

Run:

```bash
python -m pytest tests/unit/test_task_shared_run_coordination_hook.py -q
```

Expected:

```text
AttributeError: module 'app.tasks._shared' has no attribute '_observe_run_coordination_after_task'
```

- [ ] **Step 3: Add the hook function in `app/tasks/_shared.py`**

In `app/tasks/_shared.py`, add this function immediately after `_drain_pending_instruction`:

```python
async def _observe_run_coordination_after_task(task_id: str) -> None:
    try:
        from app.services.run_coordination import observe_task_terminal_decision_tick

        await observe_task_terminal_decision_tick(task_id)
    except Exception as exc:
        LOGGER.warning("Run coordination decision tick failed for %s: %s", task_id, exc)
```

- [ ] **Step 4: Call the hook before finalization**

In `app/tasks/_shared.py`, change this block inside `_persist_and_publish`:

```python
    if payload.get("type") in ("task_complete", "task_failed"):
        await _drain_pending_instruction(task_id)
        await _maybe_finalize_run(task_id)
```

to:

```python
    if payload.get("type") in ("task_complete", "task_failed"):
        await _drain_pending_instruction(task_id)
        await _observe_run_coordination_after_task(task_id)
        await _maybe_finalize_run(task_id)
```

- [ ] **Step 5: Run the hook test**

Run:

```bash
python -m pytest tests/unit/test_task_shared_run_coordination_hook.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Run the coordination tests again**

Run:

```bash
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_task_shared_run_coordination_hook.py -q
```

Expected:

```text
8 passed
```

- [ ] **Step 7: Commit the hook if git is available**

Run:

```bash
git status --short
git add app/tasks/_shared.py tests/unit/test_task_shared_run_coordination_hook.py
git commit -m "feat: observe coordination tick after terminal tasks"
```

Expected:

```text
[branch ...] feat: observe coordination tick after terminal tasks
```

If `git status --short` fails because `.git` points to an unavailable gitdir, record the failure in the implementation notes and continue without committing.

---

### Task 4: Focused Regression Verification

**Files:**
- Read: `tests/unit/test_agent_run_state_machine.py`
- Read: `tests/unit/test_agent_run_snapshot_contract.py`
- Read: `tests/unit/test_project_continue.py`

- [ ] **Step 1: Run policy regression tests**

Run:

```bash
python -m pytest tests/unit/test_agent_run_state_machine.py tests/unit/test_run_coordination.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 2: Run snapshot contract tests**

Run:

```bash
python -m pytest tests/unit/test_agent_run_snapshot_contract.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 3: Run project continue regression tests**

Run:

```bash
python -m pytest tests/unit/test_project_continue.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 4: Run all targeted tests together**

Run:

```bash
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_agent_run_state_machine.py tests/unit/test_agent_run_snapshot_contract.py tests/unit/test_project_continue.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: Record implementation result**

Append a short result section to this plan after execution:

```markdown
## Example Result

- Added read-only run coordination decision tick.
- Added terminal task observer hook before legacy finalization.
- Verification:
  - `python -m pytest tests/unit/test_run_coordination.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_agent_run_state_machine.py tests/unit/test_agent_run_snapshot_contract.py tests/unit/test_project_continue.py -q`
  - Result: [paste exact pass/fail summary from pytest]
- Git:
  - [paste commit hashes or record that this workspace gitdir is unavailable]
```

Use the exact pytest output summary in the result line.

---

## Acceptance Criteria

- `app/services/run_coordination.py` exists and exposes a pure `evaluate_decision_tick(facts)` function.
- The decision tick returns `execute` for story plan, keyframes, videos, and final edit when those are the next legal stage.
- The decision tick returns `wait` when active tasks exist.
- The decision tick returns `recover` when failed tasks block useful forward progress.
- The decision tick returns `complete` only when a final video artifact exists and the state machine is complete.
- Terminal task completion/failure calls the read-only observer before legacy finalization.
- No automatic dispatch is introduced in this slice.
- DeepSeek, workbench, and production runner behavior remain unchanged except for the new read-only decision event.

## Self-Review

- Spec coverage: This plan implements the first slice from `docs/codex-style-video-agent-process.md`: read-only coordination analysis, decision tick result, tests, and terminal task observation.
- Placeholder scan: No implementation step relies on an undefined function or vague instruction; code snippets define all new public names used by tests.
- Type consistency: `UnifiedRunFacts`, `DecisionTickResult`, `evaluate_decision_tick`, and `observe_task_terminal_decision_tick` use the same names across tests, service, and hook.
- Scope check: Automatic mission dispatch, strategy-level recovery execution, and UI changes are explicitly outside this first slice.

## Implementation Result

- Added read-only run coordination decision tick in `app/services/run_coordination.py`.
- Added final-artifact completion semantics to `app/services/agent_run_state_machine.py` so completion is policy-driven, not coordinator-bypassed.
- Added terminal task observer hook before legacy finalization in `app/tasks/_shared.py` for both complete and failed task paths.
- Added focused unit coverage:
  - `tests/unit/test_run_coordination.py`
  - `tests/unit/test_task_shared_run_coordination_hook.py`
  - final-artifact policy tests in `tests/unit/test_agent_run_state_machine.py`
- Verification:
  - `python -m pytest tests/unit/test_run_coordination.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_agent_run_state_machine.py tests/unit/test_agent_run_snapshot_contract.py tests/unit/test_project_continue.py -q`
  - Result: `67 passed in 2.57s`
- Git:
  - Git is unavailable in this workspace because `.git` points to missing `C:/tmp/saas-git`; no commits were created.
