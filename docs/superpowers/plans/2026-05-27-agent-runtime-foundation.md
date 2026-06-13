# Agent Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the enforceable foundation for Claude/Opus-style coordination: decision mailbox records, reasoning/execution separation, lane and versioned capability enforcement, normalized observation signals, multi-artifact writeback verification, safety circuit breaker, and user/expert/debug feedback.

**Architecture:** Keep the current main chain intact and add focused services around it. The coordinator remains the only authority; B-lane and LLM workers can submit recommendations, C-lane/provider workers execute assigned missions, and the gateway rejects unauthorized actions before any write or provider call.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, PostgreSQL JSONB via `agent_events.meta`, pytest/pytest-asyncio, existing `DecisionTickResult`, `publish_agent_event`, `dispatch_authoritative_packet`.

---

## Scope

This plan implements the foundation only. It does not implement DAG scheduling, L8 cross-run learning, provider performance ranking, or frontend UI changes. Those are separate plans after this foundation is verified.

## Execution Layers And Batches

This plan is executed as 4 layers and 8 batches. Each batch maps to one concrete section in this plan; no batch should be skipped or merged unless its tests already exist and pass.

| Layer | Batch | Plan task | Main purpose | Primary files | Required proof |
| --- | --- | --- | --- | --- | --- |
| Layer 1: Hard Contracts | Batch 1 | Task 1 + Task 1A | Define runtime contracts, reasoning/execution separation, capability requirements, artifact contracts, and safety constants. | `app/services/agent_runtime_contracts.py`, `tests/unit/test_agent_runtime_contracts.py` | Contract tests prove B/C lane limits, `decision_rationale`, `thinking_artifacts`, `CAPABILITY_REQUIREMENTS`, `ArtifactRef`, `ExpectedArtifact`, and safety gates. |
| Layer 1: Hard Contracts | Batch 2 | Task 2 | Persist the decision mailbox as durable audit events. | `app/services/decision_mailbox.py`, `tests/unit/test_decision_mailbox.py` | Mailbox tests prove pending/completed/rejected records include packet, idempotency key, rationale, and thinking artifacts. |
| Layer 2: Forced Boundaries | Batch 3 | Task 3 | Enforce lane authority at the gateway. | `app/services/run_dispatch_gateway.py`, `tests/unit/test_run_dispatch_gateway.py` | Gateway tests prove B-lane provider execution is rejected and C-lane assigned execution can proceed. |
| Layer 2: Forced Boundaries | Batch 4 | Task 3A | Enforce runtime/tool/provider capability compatibility before dispatch. | `app/services/run_dispatch_gateway.py`, `tests/unit/test_run_dispatch_gateway.py` | Gateway tests prove missing Seedance/Kling-style video capability blocks `generate_videos` before handler execution. |
| Layer 3: Observation And Safety | Batch 5 | Task 4 | Add active task/writeback observation foundation. | `app/services/main_chain_observer.py`, `tests/unit/test_main_chain_observer.py` | Observer tests prove task success with missing `selected_image` or `selected_video` emits `WRITEBACK_FAILED`. |
| Layer 3: Observation And Safety | Batch 6 | Task 4A | Verify multi-artifact output completeness. | `app/services/main_chain_observer.py`, `tests/unit/test_main_chain_observer.py` | Observer tests prove missing required artifacts emit `MISSING_ARTIFACT`; optional artifacts do not block completion. |
| Layer 3: Observation And Safety | Batch 7 | Task 6A | Add controller safety circuit breaker. | `app/services/main_chain_controller.py`, `tests/unit/test_main_chain_controller.py` | Controller tests prove dangerous/high-risk packets block before gateway dispatch and publish review feedback. |
| Layer 4: Feedback And Closure | Batch 8 | Task 5 + Task 6 + Task 7 + Task 8 | Publish user/expert/debug feedback, integrate controller states, run full-loop verification, and update main-chain docs. | `app/services/main_chain_feedback.py`, `app/services/main_chain_controller.py`, `tests/integration/test_main_chain_loop.py`, `docs/main-chain-implementation-contract.md`, `docs/main-chain-function-tree-diagnosis.md` | Unit and integration tests prove feedback/mailbox events exist and the main chain still passes entry-to-terminal-to-gateway verification. |

Execution order:

```text
Batch 1 -> Batch 2 -> Batch 3 -> Batch 4 -> Batch 5 -> Batch 6 -> Batch 7 -> Batch 8
```

The dependency rule is strict:

```text
Contracts first
-> mailbox persistence
-> gateway enforcement
-> capability compatibility
-> observation correctness
-> artifact completeness
-> safety blocking
-> feedback and full-loop verification
```

Each batch must end with its local tests passing before the next batch starts. Batch 8 is the only batch that should run the full selected unit matrix plus DB-backed integration suite.

## File Structure

- Create `app/services/agent_runtime_contracts.py`
  - Pure dataclasses/constants for mailbox records, observation signals, feedback payloads, lane capabilities, versioned capability requirements, artifact expectations, safety thresholds, and validation helpers.
- Create `app/services/decision_mailbox.py`
  - Event-backed decision mailbox using `agent_events` with `source='decision_mailbox'`, including `decision_rationale` and `thinking_artifacts`.
- Create `app/services/main_chain_observer.py`
  - Multi-source observer foundation with task status, DB writeback verification, and required artifact verification.
- Create `app/services/main_chain_feedback.py`
  - Normalized user/expert/debug feedback builder and publisher.
- Modify `app/services/run_dispatch_gateway.py`
  - Enforce lane capability whitelist before handler dispatch.
  - Enforce `CAPABILITY_REQUIREMENTS` against runtime/provider/tool context before handler dispatch.
  - Mark claimed/completed mailbox state.
  - Publish user-visible dispatch feedback.
- Modify `app/services/main_chain_controller.py`
  - Use feedback helper for wait/recover/blocked/complete.
  - Block dangerous or high-risk packets through a safety circuit breaker before dispatch.
  - Preserve existing `apply_decision_packet` public API.
- Modify `app/services/main_chain_terminal.py`
  - Run active observer before applying terminal decision.
- Test `tests/unit/test_agent_runtime_contracts.py`
- Test `tests/unit/test_decision_mailbox.py`
- Test `tests/unit/test_main_chain_observer.py`
- Test updates in `tests/unit/test_run_dispatch_gateway.py`
- Test updates in `tests/unit/test_main_chain_controller.py`
- Integration update in `tests/integration/test_main_chain_loop.py`

## Task 1: Runtime Contracts

**Files:**
- Create: `app/services/agent_runtime_contracts.py`
- Test: `tests/unit/test_agent_runtime_contracts.py`

- [ ] **Step 1: Write failing tests for lane capabilities and signal normalization**

Create `tests/unit/test_agent_runtime_contracts.py`:

```python
import pytest

from app.services.agent_runtime_contracts import (
    CapabilityViolation,
    ObservationSignal,
    RuntimeFeedback,
    ensure_lane_can,
    normalize_signal_severity,
)


def test_b_lane_cannot_execute_provider_work():
    with pytest.raises(CapabilityViolation, match="b_lane_agent_runs cannot execute"):
        ensure_lane_can("b_lane_agent_runs", "execute")


def test_c_lane_cannot_choose_global_next_action():
    with pytest.raises(CapabilityViolation, match="c_lane_production cannot choose_next_global_action"):
        ensure_lane_can("c_lane_production", "choose_next_global_action")


def test_c_lane_can_execute_assigned_mission():
    ensure_lane_can("c_lane_production", "execute_assigned_mission")


def test_observation_signal_as_dict_has_stable_shape():
    signal = ObservationSignal(
        type="WRITEBACK_FAILED",
        severity="error",
        source="writeback_status",
        run_id="run-1",
        task_id="task-1",
        stage_id="generate_keyframes",
        summary="Task completed but selected_image was not written back.",
        evidence_refs=[{"kind": "shot_row", "shot_index": 1}],
        suggested_recovery="repair_writeback",
    )

    payload = signal.as_dict()

    assert payload["type"] == "WRITEBACK_FAILED"
    assert payload["severity"] == "error"
    assert payload["suggested_recovery"] == "repair_writeback"


def test_runtime_feedback_as_dict_defaults():
    feedback = RuntimeFeedback(
        status="executing",
        summary="Generating video for shot 1.",
        next_step="Wait for task completion.",
    )

    payload = feedback.as_dict()

    assert payload["status"] == "executing"
    assert payload["requires_user"] is False
    assert payload["audience"] == "user"


def test_signal_severity_normalization():
    assert normalize_signal_severity("ERROR") == "error"
    assert normalize_signal_severity("unknown") == "info"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_agent_runtime_contracts.py -q`

Expected: FAIL because `app.services.agent_runtime_contracts` does not exist.

- [ ] **Step 3: Implement runtime contracts**

Create `app/services/agent_runtime_contracts.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


LANE_CAPABILITIES: dict[str, set[str]] = {
    "a_lane_project_brain": {"plan", "recommend", "read_state", "draft_feedback"},
    "b_lane_agent_runs": {"analyze", "recommend", "diagnose", "suggest", "draft_feedback"},
    "c_lane_production": {"execute_assigned_mission", "write_expected_outputs", "call_provider", "report_progress"},
    "main_chain": {"decide", "route", "pause", "escalate", "ask_human", "complete"},
}

LANE_FORBIDDEN: dict[str, set[str]] = {
    "a_lane_project_brain": {"call_provider", "spend_credits", "mark_complete"},
    "b_lane_agent_runs": {"execute", "write_db", "call_provider", "spend_credits", "mark_complete"},
    "c_lane_production": {"change_goal", "change_plan", "skip_stage", "override_budget", "choose_next_global_action"},
    "main_chain": {"direct_provider_call", "bypass_gateway"},
}

SEVERITIES = {"info", "warning", "error", "critical"}
FEEDBACK_AUDIENCES = {"user", "expert", "debug"}


class CapabilityViolation(ValueError):
    pass


@dataclass(frozen=True)
class ObservationSignal:
    type: str
    severity: str
    source: str
    run_id: str
    task_id: str | None = None
    stage_id: str = ""
    summary: str = ""
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    suggested_recovery: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = normalize_signal_severity(payload["severity"])
        return payload


@dataclass(frozen=True)
class RuntimeFeedback:
    status: str
    summary: str
    next_step: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    risk: dict[str, Any] | None = None
    requires_user: bool = False
    audience: str = "user"
    progress: dict[str, Any] = field(default_factory=dict)
    call_to_action: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["audience"] = normalize_feedback_audience(payload["audience"])
        return payload


@dataclass(frozen=True)
class DecisionMailboxRecord:
    decision_id: str
    run_id: str
    status: str
    packet: dict[str, Any]
    parent_decision_id: str = ""
    claimed_by: str = ""
    result_ref: dict[str, Any] = field(default_factory=dict)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    recovery_strategy: str = ""
    idempotency_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_signal_severity(value: str | None) -> str:
    severity = str(value or "info").strip().lower()
    return severity if severity in SEVERITIES else "info"


def normalize_feedback_audience(value: str | None) -> str:
    audience = str(value or "user").strip().lower()
    return audience if audience in FEEDBACK_AUDIENCES else "user"


def ensure_lane_can(lane: str, capability: str) -> None:
    lane_value = str(lane or "").strip()
    capability_value = str(capability or "").strip()
    forbidden = LANE_FORBIDDEN.get(lane_value, set())
    allowed = LANE_CAPABILITIES.get(lane_value, set())
    if capability_value in forbidden or capability_value not in allowed:
        raise CapabilityViolation(
            f"{lane_value or 'unknown'} cannot {capability_value or 'unknown'}. "
            f"Allowed: {sorted(allowed)}"
        )
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `python -m pytest tests/unit/test_agent_runtime_contracts.py -q`

Expected: `5 passed`.

## Task 1A: Reasoning, Capability, Artifact, And Safety Contracts

**Files:**
- Modify: `app/services/agent_runtime_contracts.py`
- Test: `tests/unit/test_agent_runtime_contracts.py`

- [ ] **Step 1: Add failing tests for Claude/Opus production-hardening contracts**

Append to `tests/unit/test_agent_runtime_contracts.py`:

```python
from app.services.agent_runtime_contracts import (
    ARTIFACT_REQUIREMENTS,
    CAPABILITY_REQUIREMENTS,
    DANGEROUS_ACTIONS,
    RISK_THRESHOLDS,
    ArtifactRef,
    DecisionMailboxRecord,
    ExpectedArtifact,
    SafetyReviewRequired,
    ensure_runtime_requirements,
    ensure_safety_gate,
    expected_artifacts_for_action,
)


def test_decision_mailbox_record_stores_rationale_without_hidden_cot():
    record = DecisionMailboxRecord(
        decision_id="decision-1",
        run_id="run-1",
        status="pending",
        packet={"action": "generate_videos"},
        decision_rationale="Shot 1 has selected_image and is missing selected_video.",
        thinking_artifacts=[
            {"type": "planner_summary", "model": "deepseek-reasoner", "confidence": 0.82}
        ],
    )

    payload = record.as_dict()

    assert payload["decision_rationale"] == "Shot 1 has selected_image and is missing selected_video."
    assert payload["thinking_artifacts"][0]["type"] == "planner_summary"
    assert "chain_of_thought" not in payload
    assert "reasoning_trace" not in payload


def test_runtime_requirement_blocks_missing_provider_capability():
    context = {
        "runtime_features": [
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        "provider_capabilities": ["seedream_text_to_image"],
        "capability_versions": {"generate_videos": "2026-05-27.v1"},
    }

    with pytest.raises(CapabilityViolation, match="provider capability"):
        ensure_runtime_requirements("generate_videos", context)


def test_runtime_requirement_allows_seedance_video_capability():
    context = {
        "runtime_features": [
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        "provider_capabilities": ["seedance_image_to_video"],
        "capability_versions": {"generate_videos": "2026-05-27.v1"},
    }

    ensure_runtime_requirements("generate_videos", context)


def test_expected_artifacts_for_video_generation_include_required_outputs():
    artifacts = expected_artifacts_for_action("generate_videos")

    assert ExpectedArtifact(
        artifact_type="selected_video",
        write_target={"table": "shot_rows", "field": "selected_video"},
        required=True,
        source="db_writeback",
    ) in artifacts
    assert any(item.artifact_type == "thumbnail" and item.required is False for item in artifacts)


def test_safety_gate_blocks_dangerous_action():
    with pytest.raises(SafetyReviewRequired, match="delete_project"):
        ensure_safety_gate({"action": "delete_project", "risk": {"score": 0.2}})


def test_safety_gate_blocks_high_risk_packet():
    with pytest.raises(SafetyReviewRequired, match="high risk"):
        ensure_safety_gate({"action": "generate_videos", "risk": {"score": 0.86}})


def test_safety_constants_are_explicit():
    assert "delete_project" in DANGEROUS_ACTIONS
    assert RISK_THRESHOLDS["high"] == 0.8
    assert "generate_videos" in CAPABILITY_REQUIREMENTS
    assert "generate_videos" in ARTIFACT_REQUIREMENTS
    assert ArtifactRef(artifact_type="video", ref="asset-1").required is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_agent_runtime_contracts.py -q`

Expected: FAIL because the new contracts and helpers do not exist.

- [ ] **Step 3: Extend runtime contracts**

Modify `app/services/agent_runtime_contracts.py`:

```python
from packaging.version import Version
```

Extend `DecisionMailboxRecord`:

```python
@dataclass(frozen=True)
class DecisionMailboxRecord:
    decision_id: str
    run_id: str
    status: str
    packet: dict[str, Any]
    parent_decision_id: str = ""
    claimed_by: str = ""
    result_ref: dict[str, Any] = field(default_factory=dict)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    recovery_strategy: str = ""
    idempotency_key: str = ""
    decision_rationale: str = ""
    thinking_artifacts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Add artifact contracts:

```python
@dataclass(frozen=True)
class ArtifactRef:
    artifact_type: str
    ref: str
    required: bool = True
    checksum: str = ""
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExpectedArtifact:
    artifact_type: str
    write_target: dict[str, Any]
    required: bool = True
    source: str = "provider_result"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Add versioned capability and artifact requirements:

```python
CAPABILITY_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "generate_videos": {
        "capability_version": "2026-05-27.v1",
        "required_features": {
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        },
        "provider_capabilities_any": {
            "seedance_image_to_video",
            "kling_image_to_video",
        },
        "max_concurrent": 2,
        "rate_limit_per_hour": 10,
    },
    "plan_final_edit": {
        "capability_version": "2026-05-27.v1",
        "required_features": {
            "scene_analysis",
            "selected_video_read",
            "final_edit_plan_writeback",
        },
        "provider_capabilities_any": set(),
    },
}

ARTIFACT_REQUIREMENTS: dict[str, list[ExpectedArtifact]] = {
    "generate_keyframes": [
        ExpectedArtifact("selected_image", {"table": "shot_rows", "field": "selected_image"}, True, "db_writeback"),
        ExpectedArtifact("image_candidate_metadata", {"table": "agent_artifacts", "kind": "image_metadata"}, True),
        ExpectedArtifact("provider_writeback_event", {"table": "agent_events", "event_type": "writeback"}, True),
    ],
    "generate_videos": [
        ExpectedArtifact("selected_video", {"table": "shot_rows", "field": "selected_video"}, True, "db_writeback"),
        ExpectedArtifact("video_variant_metadata", {"table": "agent_artifacts", "kind": "video_metadata"}, True),
        ExpectedArtifact("provider_writeback_event", {"table": "agent_events", "event_type": "writeback"}, True),
        ExpectedArtifact("thumbnail", {"table": "agent_artifacts", "kind": "thumbnail"}, False),
    ],
    "export_final": [
        ExpectedArtifact("final_video_asset", {"table": "final_video_assets", "field": "url"}, True, "db_writeback"),
        ExpectedArtifact("delivery_metadata", {"table": "agent_artifacts", "kind": "delivery_metadata"}, True),
        ExpectedArtifact("final_task_result_link", {"table": "tasks", "field": "result"}, True),
    ],
}

RISK_THRESHOLDS: dict[str, float] = {
    "low": 0.3,
    "medium": 0.6,
    "high": 0.8,
    "critical": 0.9,
}

DANGEROUS_ACTIONS: set[str] = {
    "delete_project",
    "purge_database",
    "override_production",
    "escalate_privileges",
    "bypass_budget",
}
```

Add safety and runtime validation helpers:

```python
class SafetyReviewRequired(ValueError):
    pass


def expected_artifacts_for_action(action: str) -> list[ExpectedArtifact]:
    return list(ARTIFACT_REQUIREMENTS.get(str(action or ""), []))


def ensure_runtime_requirements(action: str, context: dict[str, Any] | None) -> None:
    requirement = CAPABILITY_REQUIREMENTS.get(str(action or ""))
    if not requirement:
        return

    runtime_context = context or {}
    runtime_features = set(runtime_context.get("runtime_features") or [])
    provider_capabilities = set(runtime_context.get("provider_capabilities") or [])
    required_features = set(requirement.get("required_features") or [])
    provider_any = set(requirement.get("provider_capabilities_any") or [])

    missing_features = sorted(required_features - runtime_features)
    if missing_features:
        raise CapabilityViolation(f"{action} missing runtime features: {missing_features}")

    if provider_any and not provider_any.intersection(provider_capabilities):
        raise CapabilityViolation(
            f"{action} missing provider capability; expected one of {sorted(provider_any)}"
        )

    expected_version = str(requirement.get("capability_version") or "")
    current_version = str((runtime_context.get("capability_versions") or {}).get(action) or "")
    if expected_version and current_version and Version(_version_tail(current_version)) < Version(_version_tail(expected_version)):
        raise CapabilityViolation(f"{action} requires capability {expected_version}; current {current_version}")


def ensure_safety_gate(packet: dict[str, Any]) -> None:
    action = str(packet.get("action") or "")
    risk = packet.get("risk") if isinstance(packet.get("risk"), dict) else {}
    score = float(risk.get("score") or 0.0)

    if action in DANGEROUS_ACTIONS:
        raise SafetyReviewRequired(f"dangerous action requires review: {action}")
    if score >= RISK_THRESHOLDS["high"]:
        raise SafetyReviewRequired(f"high risk packet requires review: {action}")


def _version_tail(value: str) -> str:
    return value.rsplit(".v", 1)[-1] if ".v" in value else "0"
```

- [ ] **Step 4: Install packaging only if the environment lacks it**

Run: `python -c "import packaging; print(packaging.__version__)"`

Expected: prints a version. If it fails, replace `Version(...)` with tuple parsing in `_version_tail` instead of adding a new dependency.

- [ ] **Step 5: Run runtime contract tests**

Run: `python -m pytest tests/unit/test_agent_runtime_contracts.py -q`

Expected: all runtime contract tests pass.

## Task 2: Event-Backed Decision Mailbox

**Files:**
- Create: `app/services/decision_mailbox.py`
- Test: `tests/unit/test_decision_mailbox.py`

- [ ] **Step 1: Write failing mailbox tests with a fake async DB**

Create `tests/unit/test_decision_mailbox.py`:

```python
import json

import pytest

from app.services.decision_mailbox import (
    complete_decision,
    mark_decision_rejected,
    submit_decision,
)


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeDB:
    def __init__(self):
        self.executed = []

    async def execute(self, statement, params):
        self.executed.append((str(statement), params))
        return FakeResult("event-1")


def packet(action="generate_videos"):
    return {
        "status": "execute",
        "action": action,
        "mission": {
            "idempotency_key": f"run-1:{action}",
            "lane": "c_lane_production",
            "action": action,
        },
    }


@pytest.mark.asyncio
async def test_submit_decision_writes_pending_mailbox_event():
    db = FakeDB()

    decision_id = await submit_decision(
        db,
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        packet=packet(),
        parent_decision_id="parent-1",
        decision_rationale="Shot 1 needs video generation.",
        thinking_artifacts=[{"type": "planner_summary", "confidence": 0.8}],
    )

    assert decision_id == "event-1"
    params = db.executed[0][1]
    meta = json.loads(params["meta"])
    assert meta["mailbox"]["status"] == "pending"
    assert meta["mailbox"]["packet"]["action"] == "generate_videos"
    assert meta["mailbox"]["parent_decision_id"] == "parent-1"
    assert meta["mailbox"]["decision_rationale"] == "Shot 1 needs video generation."
    assert meta["mailbox"]["thinking_artifacts"][0]["type"] == "planner_summary"


@pytest.mark.asyncio
async def test_complete_decision_writes_completed_mailbox_event():
    db = FakeDB()

    await complete_decision(
        db,
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        decision_id="decision-1",
        result_ref={"queued_count": 1},
    )

    meta = json.loads(db.executed[0][1]["meta"])
    assert meta["mailbox"]["status"] == "completed"
    assert meta["mailbox"]["decision_id"] == "decision-1"
    assert meta["mailbox"]["result_ref"]["queued_count"] == 1


@pytest.mark.asyncio
async def test_mark_decision_rejected_records_reason():
    db = FakeDB()

    await mark_decision_rejected(
        db,
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        decision_id="decision-1",
        reason="lane cannot execute",
    )

    meta = json.loads(db.executed[0][1]["meta"])
    assert meta["mailbox"]["status"] == "rejected"
    assert meta["mailbox"]["reason"] == "lane cannot execute"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_decision_mailbox.py -q`

Expected: FAIL because `app.services.decision_mailbox` does not exist.

- [ ] **Step 3: Implement event-backed mailbox**

Create `app/services/decision_mailbox.py`:

```python
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SOURCE = "decision_mailbox"


async def submit_decision(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    packet: dict[str, Any],
    parent_decision_id: str = "",
    decision_rationale: str = "",
    thinking_artifacts: list[dict[str, Any]] | None = None,
) -> str:
    mission = packet.get("mission") if isinstance(packet.get("mission"), dict) else {}
    mailbox = {
        "status": "pending",
        "packet": packet,
        "parent_decision_id": parent_decision_id,
        "idempotency_key": str(mission.get("idempotency_key") or ""),
        "decision_rationale": decision_rationale,
        "thinking_artifacts": list(thinking_artifacts or []),
    }
    return await _insert_mailbox_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        status="pending",
        title="Decision queued",
        detail=str(packet.get("action") or "decision"),
        mailbox=mailbox,
    )


async def complete_decision(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    decision_id: str,
    result_ref: dict[str, Any],
) -> str:
    return await _insert_mailbox_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        status="completed",
        title="Decision completed",
        detail=decision_id,
        mailbox={"status": "completed", "decision_id": decision_id, "result_ref": result_ref},
    )


async def mark_decision_rejected(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    decision_id: str,
    reason: str,
) -> str:
    return await _insert_mailbox_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        status="rejected",
        title="Decision rejected",
        detail=reason,
        mailbox={"status": "rejected", "decision_id": decision_id, "reason": reason},
    )


async def _insert_mailbox_event(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    status: str,
    title: str,
    detail: str,
    mailbox: dict[str, Any],
) -> str:
    result = await db.execute(
        text(
            """
            INSERT INTO agent_events (
                run_id, project_id, user_id, source, event_type, phase,
                title, detail, status, progress, meta
            )
            VALUES (
                CAST(:run_id AS UUID), :project_id, :user_id, :source,
                'decision_mailbox', :phase, :title, :detail, :status, NULL,
                CAST(:meta AS JSONB)
            )
            RETURNING id
            """
        ),
        {
            "run_id": run_id,
            "project_id": project_id,
            "user_id": user_id,
            "source": SOURCE,
            "phase": status,
            "title": title,
            "detail": detail,
            "status": status,
            "meta": json.dumps({"mailbox": mailbox}, ensure_ascii=False, default=str),
        },
    )
    return str(result.scalar_one())
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `python -m pytest tests/unit/test_decision_mailbox.py -q`

Expected: `3 passed`.

## Task 3: Gateway Capability Enforcement

**Files:**
- Modify: `app/services/run_dispatch_gateway.py`
- Test: `tests/unit/test_run_dispatch_gateway.py`

- [ ] **Step 1: Add failing gateway tests**

Append to `tests/unit/test_run_dispatch_gateway.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_gateway_rejects_b_lane_provider_execution(monkeypatch):
    async def fail_handler():
        raise AssertionError("handler should not run")

    async def fake_reject(*args, **kwargs):
        return "rejected-event"

    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "mark_decision_rejected", fake_reject)

    with pytest.raises(ValueError, match="b_lane_agent_runs cannot execute"):
        await run_dispatch_gateway.dispatch_authoritative_packet(
            object(),
            packet=packet(action="generate_videos", lane="b_lane_agent_runs"),
            context=DispatchGatewayContext(
                project_id="project-1",
                user_id=7,
                user_tier="pro",
                run_id="run-1",
                run_mode="step",
            ),
            handlers={"generate_videos": fail_handler},
        )


@pytest.mark.asyncio
async def test_dispatch_gateway_completes_mailbox_after_handler(monkeypatch):
    observed = {"completed": None}

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_complete(_db, **kwargs):
        observed["completed"] = kwargs
        return "completed-event"

    async def handler():
        return {"queued_count": 1}

    monkeypatch.setattr(run_dispatch_gateway, "update_agent_run", fake_update)
    monkeypatch.setattr(run_dispatch_gateway, "publish_agent_event", fake_publish)
    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "complete_decision", fake_complete)

    await run_dispatch_gateway.dispatch_authoritative_packet(
        object(),
        packet=packet(),
        context=DispatchGatewayContext("project-1", 7, "pro", "run-1", "step"),
        handlers={"generate_keyframes": handler},
    )

    assert observed["completed"]["result_ref"]["queued_count"] == 1
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_run_dispatch_gateway.py -q`

Expected: FAIL because `run_dispatch_gateway` does not import `decision_mailbox` and does not enforce lane capabilities.

- [ ] **Step 3: Update gateway implementation**

Modify `app/services/run_dispatch_gateway.py`:

```python
from app.services import decision_mailbox
from app.services.agent_runtime_contracts import CapabilityViolation, ensure_lane_can
```

Inside `dispatch_authoritative_packet`, after `mission = _validate_packet(packet)`:

```python
    action = str(mission["action"])
    lane = str(mission["lane"])
    decision_id = str(mission.get("mission_id") or f"{context.run_id}:{action}")
    try:
        ensure_lane_can(lane, _capability_for_action(action))
    except CapabilityViolation as exc:
        await decision_mailbox.mark_decision_rejected(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            decision_id=decision_id,
            reason=str(exc),
        )
        raise ValueError(str(exc)) from exc
```

After `result["decision_packet"] = packet.as_dict()`:

```python
    await decision_mailbox.complete_decision(
        db,
        run_id=context.run_id,
        project_id=context.project_id,
        user_id=context.user_id,
        decision_id=decision_id,
        result_ref={key: value for key, value in result.items() if key != "decision_packet"},
    )
```

Add helper at end of file:

```python
def _capability_for_action(action: str) -> str:
    if action in {"generate_keyframes", "generate_videos", "plan_final_edit", "export_preview", "export_final"}:
        return "execute_assigned_mission"
    if action in {"generate_story_plan", "plan_visual_assets"}:
        return "plan"
    return "execute_assigned_mission"
```

- [ ] **Step 4: Run gateway tests**

Run: `python -m pytest tests/unit/test_run_dispatch_gateway.py -q`

Expected: all gateway tests pass.

## Task 3A: Versioned Runtime/Provider Capability Enforcement

**Files:**
- Modify: `app/services/run_dispatch_gateway.py`
- Test: `tests/unit/test_run_dispatch_gateway.py`

- [ ] **Step 1: Add failing gateway tests for runtime capability checks**

Append to `tests/unit/test_run_dispatch_gateway.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_gateway_rejects_missing_provider_capability(monkeypatch):
    async def fail_handler():
        raise AssertionError("handler should not run")

    async def fake_reject(*args, **kwargs):
        return "rejected-event"

    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "mark_decision_rejected", fake_reject)

    context = DispatchGatewayContext(
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        run_id="run-1",
        run_mode="step",
        runtime_features=[
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        provider_capabilities=["seedream_text_to_image"],
        capability_versions={"generate_videos": "2026-05-27.v1"},
    )

    with pytest.raises(ValueError, match="provider capability"):
        await run_dispatch_gateway.dispatch_authoritative_packet(
            object(),
            packet=packet(action="generate_videos", lane="c_lane_production"),
            context=context,
            handlers={"generate_videos": fail_handler},
        )


@pytest.mark.asyncio
async def test_dispatch_gateway_allows_seedance_video_capability(monkeypatch):
    observed = {"handler": False}

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_complete(*args, **kwargs):
        return "completed-event"

    async def handler():
        observed["handler"] = True
        return {"queued_count": 1}

    monkeypatch.setattr(run_dispatch_gateway, "update_agent_run", fake_update)
    monkeypatch.setattr(run_dispatch_gateway, "publish_agent_event", fake_publish)
    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "complete_decision", fake_complete)

    context = DispatchGatewayContext(
        "project-1",
        7,
        "pro",
        "run-1",
        "step",
        runtime_features=[
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        provider_capabilities=["seedance_image_to_video"],
        capability_versions={"generate_videos": "2026-05-27.v1"},
    )

    await run_dispatch_gateway.dispatch_authoritative_packet(
        object(),
        packet=packet(action="generate_videos", lane="c_lane_production"),
        context=context,
        handlers={"generate_videos": handler},
    )

    assert observed["handler"] is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_run_dispatch_gateway.py -q`

Expected: FAIL because dispatch does not call `ensure_runtime_requirements`.

- [ ] **Step 3: Enforce runtime requirements in gateway**

Modify imports in `app/services/run_dispatch_gateway.py`:

```python
from app.services.agent_runtime_contracts import (
    CapabilityViolation,
    ensure_lane_can,
    ensure_runtime_requirements,
)
```

Extend `DispatchGatewayContext`:

```python
@dataclass(frozen=True)
class DispatchGatewayContext:
    project_id: str
    user_id: int
    user_tier: str
    run_id: str
    run_mode: str
    runtime_features: list[str] = field(default_factory=list)
    provider_capabilities: list[str] = field(default_factory=list)
    capability_versions: dict[str, str] = field(default_factory=dict)
```

Update the dataclass import:

```python
from dataclasses import dataclass, field
```

Inside `dispatch_authoritative_packet`, immediately after lane capability validation succeeds:

```python
    runtime_context = {
        "runtime_features": context.runtime_features,
        "provider_capabilities": context.provider_capabilities,
        "capability_versions": context.capability_versions,
    }
    try:
        ensure_runtime_requirements(action, runtime_context)
    except CapabilityViolation as exc:
        await decision_mailbox.mark_decision_rejected(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            decision_id=decision_id,
            reason=str(exc),
        )
        raise ValueError(str(exc)) from exc
```

- [ ] **Step 4: Run gateway tests**

Run: `python -m pytest tests/unit/test_run_dispatch_gateway.py -q`

Expected: gateway tests pass, including lane and versioned capability rejections.

## Task 4: Active Observation Signals And Writeback Verification

**Files:**
- Create: `app/services/main_chain_observer.py`
- Test: `tests/unit/test_main_chain_observer.py`

- [ ] **Step 1: Write failing observer tests**

Create `tests/unit/test_main_chain_observer.py`:

```python
import pytest

from app.services.main_chain_observer import expected_write_signals


def test_image_task_done_without_selected_image_emits_writeback_failed():
    signals = expected_write_signals(
        task={
            "task_id": "task-1",
            "run_id": "run-1",
            "task_type": "image_gen",
            "status": "done",
            "result": {"image_url": "https://cdn.example.com/a.jpg"},
        },
        shots=[{"shot_index": 1, "selected_image": "", "selected_video": ""}],
    )

    assert len(signals) == 1
    assert signals[0].type == "WRITEBACK_FAILED"
    assert signals[0].suggested_recovery == "repair_writeback"


def test_image_task_done_with_selected_image_has_no_writeback_signal():
    signals = expected_write_signals(
        task={
            "task_id": "task-1",
            "run_id": "run-1",
            "task_type": "image_gen",
            "status": "done",
            "result": {"image_url": "https://cdn.example.com/a.jpg"},
        },
        shots=[{"shot_index": 1, "selected_image": "https://cdn.example.com/a.jpg", "selected_video": ""}],
    )

    assert signals == []


def test_video_task_done_without_selected_video_emits_writeback_failed():
    signals = expected_write_signals(
        task={
            "task_id": "task-2",
            "run_id": "run-1",
            "task_type": "video_gen",
            "status": "done",
            "result": {"video_url": "https://cdn.example.com/v.mp4"},
        },
        shots=[{"shot_index": 1, "selected_image": "https://cdn.example.com/a.jpg", "selected_video": ""}],
    )

    assert signals[0].type == "WRITEBACK_FAILED"
    assert signals[0].evidence_refs[0]["field"] == "selected_video"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_main_chain_observer.py -q`

Expected: FAIL because `app.services.main_chain_observer` does not exist.

- [ ] **Step 3: Implement writeback signal helper**

Create `app/services/main_chain_observer.py`:

```python
from __future__ import annotations

from typing import Any

from app.services.agent_runtime_contracts import ObservationSignal


def expected_write_signals(*, task: dict[str, Any], shots: list[dict[str, Any]]) -> list[ObservationSignal]:
    if str(task.get("status") or "") not in {"done", "completed"}:
        return []
    task_type = str(task.get("task_type") or "")
    if task_type == "image_gen":
        return _missing_media_write_signal(task=task, shots=shots, field="selected_image", stage_id="generate_keyframes")
    if task_type == "video_gen":
        return _missing_media_write_signal(task=task, shots=shots, field="selected_video", stage_id="generate_videos")
    return []


def _missing_media_write_signal(
    *,
    task: dict[str, Any],
    shots: list[dict[str, Any]],
    field: str,
    stage_id: str,
) -> list[ObservationSignal]:
    if any(str(shot.get(field) or "").strip() for shot in shots):
        return []
    task_id = str(task.get("task_id") or "")
    return [
        ObservationSignal(
            type="WRITEBACK_FAILED",
            severity="error",
            source="writeback_status",
            run_id=str(task.get("run_id") or ""),
            task_id=task_id,
            stage_id=stage_id,
            summary=f"Task completed but {field} was not written back.",
            evidence_refs=[
                {"kind": "shot_row", "field": field},
                {"kind": "task", "id": task_id},
            ],
            suggested_recovery="repair_writeback",
            raw={"task_type": task.get("task_type"), "result": task.get("result")},
        )
    ]
```

- [ ] **Step 4: Run observer tests**

Run: `python -m pytest tests/unit/test_main_chain_observer.py -q`

Expected: `3 passed`.

## Task 4A: Multi-Artifact Output Verification

**Files:**
- Modify: `app/services/main_chain_observer.py`
- Test: `tests/unit/test_main_chain_observer.py`

- [ ] **Step 1: Add failing tests for required and optional artifacts**

Append to `tests/unit/test_main_chain_observer.py`:

```python
from app.services.agent_runtime_contracts import ExpectedArtifact
from app.services.main_chain_observer import verify_expected_artifacts


def test_video_task_missing_required_thumbnail_metadata_emits_missing_artifact():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-2",
        action="generate_videos",
        provider_artifacts=[
            {"artifact_type": "selected_video", "ref": "https://cdn.example.com/v.mp4"},
        ],
        db_artifacts=[
            {"artifact_type": "selected_video", "ref": "shot_rows:1:selected_video"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
    )

    assert [signal.type for signal in signals] == ["MISSING_ARTIFACT"]
    assert signals[0].evidence_refs[0]["artifact_type"] == "video_variant_metadata"


def test_video_task_missing_optional_thumbnail_does_not_block_completion():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-2",
        action="generate_videos",
        provider_artifacts=[
            {"artifact_type": "selected_video", "ref": "https://cdn.example.com/v.mp4"},
            {"artifact_type": "video_variant_metadata", "ref": "agent_artifacts:video-meta-1"},
        ],
        db_artifacts=[
            {"artifact_type": "selected_video", "ref": "shot_rows:1:selected_video"},
            {"artifact_type": "video_variant_metadata", "ref": "agent_artifacts:video-meta-1"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
    )

    assert signals == []


def test_provider_artifact_present_but_db_write_missing_emits_writeback_failed():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-1",
        action="generate_keyframes",
        provider_artifacts=[
            {"artifact_type": "selected_image", "ref": "https://cdn.example.com/a.jpg"},
            {"artifact_type": "image_candidate_metadata", "ref": "agent_artifacts:image-meta-1"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
        db_artifacts=[
            {"artifact_type": "image_candidate_metadata", "ref": "agent_artifacts:image-meta-1"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
    )

    assert signals[0].type == "WRITEBACK_FAILED"
    assert signals[0].suggested_recovery == "repair_writeback"


def test_explicit_artifact_expectations_can_override_defaults():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-custom",
        action="custom_action",
        provider_artifacts=[],
        db_artifacts=[],
        expected=[
            ExpectedArtifact(
                artifact_type="custom_json",
                write_target={"table": "agent_artifacts", "kind": "custom_json"},
                required=True,
            )
        ],
    )

    assert signals[0].type == "MISSING_ARTIFACT"
    assert signals[0].evidence_refs[0]["artifact_type"] == "custom_json"
```

- [ ] **Step 2: Run observer tests and verify they fail**

Run: `python -m pytest tests/unit/test_main_chain_observer.py -q`

Expected: FAIL because `verify_expected_artifacts` is not implemented.

- [ ] **Step 3: Implement artifact verification**

Modify imports in `app/services/main_chain_observer.py`:

```python
from app.services.agent_runtime_contracts import (
    ExpectedArtifact,
    ObservationSignal,
    expected_artifacts_for_action,
)
```

Add:

```python
def verify_expected_artifacts(
    *,
    run_id: str,
    task_id: str,
    action: str,
    provider_artifacts: list[dict[str, Any]],
    db_artifacts: list[dict[str, Any]],
    expected: list[ExpectedArtifact] | None = None,
) -> list[ObservationSignal]:
    expected_items = list(expected if expected is not None else expected_artifacts_for_action(action))
    provider_types = {str(item.get("artifact_type") or "") for item in provider_artifacts}
    db_types = {str(item.get("artifact_type") or "") for item in db_artifacts}
    signals: list[ObservationSignal] = []

    for item in expected_items:
        if not item.required:
            continue

        provider_has = item.artifact_type in provider_types
        db_has = item.artifact_type in db_types
        evidence = [
            {
                "kind": "artifact",
                "artifact_type": item.artifact_type,
                "write_target": item.write_target,
            }
        ]

        if provider_has and not db_has:
            signals.append(
                ObservationSignal(
                    type="WRITEBACK_FAILED",
                    severity="error",
                    source="artifact_verification",
                    run_id=run_id,
                    task_id=task_id,
                    stage_id=action,
                    summary=f"Provider returned {item.artifact_type} but DB writeback is missing.",
                    evidence_refs=evidence,
                    suggested_recovery="repair_writeback",
                )
            )
        elif not provider_has and not db_has:
            signals.append(
                ObservationSignal(
                    type="MISSING_ARTIFACT",
                    severity="error",
                    source="artifact_verification",
                    run_id=run_id,
                    task_id=task_id,
                    stage_id=action,
                    summary=f"Required artifact {item.artifact_type} is missing.",
                    evidence_refs=evidence,
                    suggested_recovery="retry_with_artifact_check",
                )
            )

    return signals
```

- [ ] **Step 4: Run observer tests**

Run: `python -m pytest tests/unit/test_main_chain_observer.py -q`

Expected: observer tests pass and required artifact gaps produce `MISSING_ARTIFACT` or `WRITEBACK_FAILED`.

## Task 5: User/Expert/Debug Feedback Publisher

**Files:**
- Create: `app/services/main_chain_feedback.py`
- Test: `tests/unit/test_main_chain_feedback.py`

- [ ] **Step 1: Write failing feedback tests**

Create `tests/unit/test_main_chain_feedback.py`:

```python
import pytest

from app.services.agent_runtime_contracts import RuntimeFeedback
from app.services.main_chain_feedback import feedback_event_payload


def test_feedback_event_payload_user_visibility():
    payload = feedback_event_payload(
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        feedback=RuntimeFeedback(
            status="executing",
            summary="Generating video for shot 1.",
            next_step="Wait for writeback verification.",
            progress={"current": 2, "total": 5, "percentage": 40},
        ),
    )

    assert payload["source"] == "main_chain"
    assert payload["event_type"] == "feedback"
    assert payload["visibility"] == "user"
    assert payload["meta"]["feedback"]["progress"]["percentage"] == 40


def test_feedback_event_payload_debug_visibility():
    payload = feedback_event_payload(
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        feedback=RuntimeFeedback(
            status="observing",
            summary="Raw packet observed.",
            audience="debug",
        ),
    )

    assert payload["visibility"] == "debug"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_main_chain_feedback.py -q`

Expected: FAIL because `main_chain_feedback` does not exist.

- [ ] **Step 3: Implement feedback payload helper**

Create `app/services/main_chain_feedback.py`:

```python
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runtime import publish_agent_event
from app.services.agent_runtime_contracts import RuntimeFeedback


def feedback_event_payload(
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    feedback: RuntimeFeedback,
) -> dict[str, Any]:
    feedback_payload = feedback.as_dict()
    return {
        "run_id": run_id,
        "project_id": project_id,
        "user_id": user_id,
        "source": "main_chain",
        "event_type": "feedback",
        "phase": str(feedback.status),
        "title": feedback.summary[:120],
        "detail": feedback.next_step or feedback.summary,
        "status": feedback.status,
        "progress": feedback.progress.get("percentage") if isinstance(feedback.progress, dict) else None,
        "meta": {"feedback": feedback_payload},
        "event_kind": "narration",
        "visibility": feedback_payload["audience"],
        "summary": feedback.summary,
        "reason": feedback.next_step,
    }


async def publish_runtime_feedback(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    feedback: RuntimeFeedback,
) -> dict[str, Any]:
    return await publish_agent_event(db, **feedback_event_payload(run_id=run_id, project_id=project_id, user_id=user_id, feedback=feedback))
```

- [ ] **Step 4: Run feedback tests**

Run: `python -m pytest tests/unit/test_main_chain_feedback.py -q`

Expected: `2 passed`.

## Task 6: Controller Feedback Integration

**Files:**
- Modify: `app/services/main_chain_controller.py`
- Test: `tests/unit/test_main_chain_controller.py`

- [ ] **Step 1: Add failing controller feedback test**

Append to `tests/unit/test_main_chain_controller.py`:

```python
@pytest.mark.asyncio
async def test_wait_decision_publishes_runtime_feedback(monkeypatch):
    from app.services import main_chain_controller

    observed = {"feedback": None}

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(_db, **kwargs):
        observed["feedback"] = kwargs["feedback"].as_dict()
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(status="wait", action="wait_for_tasks", dispatchable=False, allowed=False),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={},
    )

    assert observed["feedback"]["status"] == "waiting"
    assert "wait_for_tasks" in observed["feedback"]["summary"]
```

- [ ] **Step 2: Run test and verify it fails**

Run: `python -m pytest tests/unit/test_main_chain_controller.py::test_wait_decision_publishes_runtime_feedback -q`

Expected: FAIL because controller does not publish runtime feedback.

- [ ] **Step 3: Integrate feedback helper**

Modify imports in `app/services/main_chain_controller.py`:

```python
from app.services import main_chain_feedback
from app.services.agent_runtime_contracts import RuntimeFeedback
```

At end of `_publish_state`, after `publish_agent_event(...)`:

```python
    await _maybe_await(
        main_chain_feedback.publish_runtime_feedback(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            feedback=RuntimeFeedback(
                status=_feedback_status(status, packet.status),
                summary=f"{packet.status}: {packet.action}",
                next_step=packet.reason,
                evidence=packet.evidence_refs,
                risk=packet.risk,
                requires_user=packet.status in {"blocked", "recover", "ask_human"},
            ),
        )
    )
```

Add helper:

```python
def _feedback_status(run_status: str, packet_status: str) -> str:
    if packet_status == "wait":
        return "waiting"
    if packet_status == "recover":
        return "recovering"
    if packet_status == "complete":
        return "completed"
    if run_status == "blocked":
        return "blocked"
    return run_status
```

- [ ] **Step 4: Run controller tests**

Run: `python -m pytest tests/unit/test_main_chain_controller.py -q`

Expected: all controller tests pass.

## Task 6A: Safety Circuit Breaker Before Dispatch

**Files:**
- Modify: `app/services/main_chain_controller.py`
- Test: `tests/unit/test_main_chain_controller.py`

- [ ] **Step 1: Add failing safety circuit breaker tests**

Append to `tests/unit/test_main_chain_controller.py`:

```python
@pytest.mark.asyncio
async def test_dangerous_action_is_blocked_before_dispatch(monkeypatch):
    from app.services import main_chain_controller

    observed = {"dispatch": False, "feedback": None}

    async def fake_dispatch(*args, **kwargs):
        observed["dispatch"] = True
        return {"queued_count": 1}

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(_db, **kwargs):
        observed["feedback"] = kwargs["feedback"].as_dict()
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fake_dispatch)
    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(action="delete_project"),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={"delete_project": fake_dispatch},
    )

    assert observed["dispatch"] is False
    assert result.status == "blocked"
    assert observed["feedback"]["status"] == "blocked"
    assert observed["feedback"]["requires_user"] is True
    assert observed["feedback"]["call_to_action"]["type"] == "dangerous_action_review"


@pytest.mark.asyncio
async def test_high_risk_packet_is_blocked_before_dispatch(monkeypatch):
    from dataclasses import replace
    from app.services import main_chain_controller

    observed = {"dispatch": False, "feedback": None}

    async def fake_dispatch(*args, **kwargs):
        observed["dispatch"] = True
        return {"queued_count": 1}

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(_db, **kwargs):
        observed["feedback"] = kwargs["feedback"].as_dict()
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fake_dispatch)
    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    risky_packet = replace(packet(action="generate_videos"), risk={"score": 0.86, "level": "high"})

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=risky_packet,
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={"generate_videos": fake_dispatch},
    )

    assert observed["dispatch"] is False
    assert result.status == "blocked"
    assert "review" in observed["feedback"]["next_step"].lower()
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/unit/test_main_chain_controller.py -q`

Expected: FAIL because the controller does not call `ensure_safety_gate` before dispatch.

- [ ] **Step 3: Add safety circuit breaker to controller**

Modify imports in `app/services/main_chain_controller.py`:

```python
from app.services.agent_runtime_contracts import (
    RuntimeFeedback,
    SafetyReviewRequired,
    ensure_safety_gate,
)
```

At the start of `apply_decision_packet`, before dispatch:

```python
    try:
        ensure_safety_gate(packet.as_dict())
    except SafetyReviewRequired as exc:
        await _publish_safety_block(db, packet=packet, context=context, reason=str(exc))
        return MainChainResult("blocked", False, packet.as_dict(), {"safety_block": str(exc)})
```

Add helper:

```python
async def _publish_safety_block(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: MainChainContext,
    reason: str,
) -> None:
    await _publish_state(db, packet=packet, context=context, status="blocked", phase="safety_review")
    await _maybe_await(
        main_chain_feedback.publish_runtime_feedback(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            feedback=RuntimeFeedback(
                status="blocked",
                summary=f"Safety block: {packet.action}",
                next_step="Manual review is required before this action can run.",
                evidence=packet.evidence_refs,
                risk=packet.risk,
                requires_user=True,
                call_to_action={
                    "type": "dangerous_action_review",
                    "action": packet.action,
                    "approvers": ["admin", "product_owner"],
                    "timeout_minutes": 60,
                    "reason": reason,
                },
            ),
        )
    )
```

- [ ] **Step 4: Run controller tests**

Run: `python -m pytest tests/unit/test_main_chain_controller.py -q`

Expected: controller tests pass and dangerous/high-risk packets do not reach the gateway.

## Task 7: Integration Verification

**Files:**
- Modify: `tests/integration/test_main_chain_loop.py`

- [ ] **Step 1: Add assertions for feedback and mailbox events**

In `test_entry_to_terminal_hook_dispatches_next_stage`, after `await assert_dispatch_gateway_event(...)`, add:

```python
        await assert_agent_event_exists(
            run_id=run_id,
            user_id=user_id,
            source="main_chain",
            event_type="feedback",
        )
        await assert_agent_event_exists(
            run_id=run_id,
            user_id=user_id,
            source="decision_mailbox",
            event_type="decision_mailbox",
        )
```

Add helper:

```python
async def assert_agent_event_exists(*, run_id: str, user_id: int, source: str, event_type: str) -> None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT 1
                    FROM agent_events
                    WHERE run_id = CAST(:run_id AS UUID)
                      AND user_id = :user_id
                      AND source = :source
                      AND event_type = :event_type
                    LIMIT 1
                    """
                ),
                {"run_id": run_id, "user_id": user_id, "source": source, "event_type": event_type},
            )
        ).first()
    assert row is not None
```

- [ ] **Step 2: Run integration test and verify it initially fails if mailbox/feedback is not wired**

Run:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/saas_test'
$env:DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/saas_test'
python -m pytest tests/integration/test_main_chain_loop.py -q -rs
```

Expected before all wiring: FAIL on missing feedback or mailbox event. Expected after Tasks 1-6: PASS.

- [ ] **Step 3: Run foundation unit suite**

Run:

```powershell
python -m pytest tests/unit/test_agent_runtime_contracts.py tests/unit/test_decision_mailbox.py tests/unit/test_main_chain_observer.py tests/unit/test_main_chain_feedback.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_main_chain_controller.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3A: Verify Claude/Opus hardening test matrix**

Run:

```powershell
python -m pytest tests/unit/test_agent_runtime_contracts.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_main_chain_observer.py tests/unit/test_main_chain_controller.py -q -k "rationale or runtime_requirement or provider_capability or expected_artifacts or safety or dangerous or high_risk or artifact"
```

Expected:

- B-lane rationale is stored as `decision_rationale` and `thinking_artifacts`.
- C-lane dispatch never receives hidden chain-of-thought fields.
- Missing provider/runtime capability blocks dispatch before handler execution.
- Missing required artifact emits `MISSING_ARTIFACT`.
- Provider result without DB writeback emits `WRITEBACK_FAILED`.
- Dangerous/high-risk action publishes review feedback and does not dispatch.

- [ ] **Step 4: Run existing main-chain suite**

Run:

```powershell
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_main_chain_controller.py tests/unit/test_main_chain_terminal.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_project_continue.py tests/unit/test_agent_action_executor.py tests/unit/test_agent_runs_route_contract.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Run DB-backed integration suite**

Run:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/saas_test'
$env:DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/saas_test'
python -m pytest tests/integration/test_main_chain_loop.py tests/integration/test_agent_events.py -q -rs
```

Expected: all selected integration tests pass.

## Task 8: Documentation Update

**Files:**
- Modify: `docs/main-chain-implementation-contract.md`
- Modify: `docs/main-chain-function-tree-diagnosis.md`

- [ ] **Step 1: Update implementation contract with foundation invariants**

Add to `docs/main-chain-implementation-contract.md`:

```markdown
## Agent Runtime Foundation Invariants

1. B lane can recommend, diagnose, explain, and request actions; it cannot execute provider work.
2. C lane can execute assigned missions; it cannot choose the global next action.
3. Every autonomous production dispatch must pass the gateway capability whitelist.
4. Decision mailbox events provide the durable audit trail for pending, completed, rejected, recovered, and cancelled decisions.
5. L7 observation must verify task state and expected DB writeback separately.
6. DeepSeek and Doubao mailbox outputs are recommendations/artifacts, not authority.
7. Seedream and Seedance jobs require active observation: progress, heartbeat, timeout, user control, provider result, and DB writeback verification.
8. Decision mailbox records store `decision_rationale` and `thinking_artifacts`, not hidden chain-of-thought.
9. Gateway checks `CAPABILITY_REQUIREMENTS` before executing any provider/tool handler.
10. Required artifacts are verified as a set; missing outputs produce `MISSING_ARTIFACT` or `WRITEBACK_FAILED`.
11. Dangerous actions and high-risk packets are blocked by the controller safety circuit breaker before gateway dispatch.
```

- [ ] **Step 2: Update diagnosis document implementation status**

Add to `docs/main-chain-function-tree-diagnosis.md` under implementation alignment:

```markdown
The next implementation phase introduces enforced lane boundaries:

```text
B lane -> recommendation/request only
C lane -> assigned execution only
Gateway -> capability whitelist + decision mailbox audit
L7 -> active observation + writeback verification + feedback
```
```

- [ ] **Step 3: Run documentation grep**

Run:

```powershell
rg -n "Decision Mailbox|capability whitelist|writeback verification|Seedream|Seedance|DeepSeek|Doubao" docs
```

Expected: each new concept appears in the design spec and main-chain docs.

## Final Verification

### Verification Matrix

| Enhancement | Test file | Required proof |
| --- | --- | --- |
| Reasoning/execution separation | `tests/unit/test_agent_runtime_contracts.py`, `tests/unit/test_decision_mailbox.py` | `decision_rationale` and `thinking_artifacts` persist in mailbox evidence; execution packet path does not depend on hidden reasoning fields. |
| Versioned capability checks | `tests/unit/test_run_dispatch_gateway.py` | Missing runtime/provider capability rejects before handler execution; Seedance/Kling-capable context proceeds. |
| Multi-artifact verification | `tests/unit/test_main_chain_observer.py` | Missing required artifact emits `MISSING_ARTIFACT`; provider result without DB writeback emits `WRITEBACK_FAILED`; optional thumbnail absence does not block. |
| Safety circuit breaker | `tests/unit/test_main_chain_controller.py` | `delete_project` and high-risk packets are blocked before dispatch and publish human/admin review feedback. |

Run all required commands:

```powershell
python -m pytest tests/unit/test_agent_runtime_contracts.py tests/unit/test_decision_mailbox.py tests/unit/test_main_chain_observer.py tests/unit/test_main_chain_feedback.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_main_chain_controller.py -q
```

```powershell
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_main_chain_controller.py tests/unit/test_main_chain_terminal.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_project_continue.py tests/unit/test_agent_action_executor.py tests/unit/test_agent_runs_route_contract.py -q
```

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/saas_test'
$env:DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/saas_test'
python -m pytest tests/integration/test_main_chain_loop.py tests/integration/test_agent_events.py -q -rs
```

Expected:

- Foundation unit tests pass.
- Existing main-chain unit matrix remains green.
- DB-backed integration proves entry -> terminal -> gateway plus feedback/mailbox events.

## Commit Note

This workspace currently reports `fatal: not a git repository: C:/tmp/saas-git` when `git status --short` is run. If git is repaired before execution, commit after each task with a focused message. If git remains unavailable, record the command failure in the final implementation report and do not attempt destructive git repair.
