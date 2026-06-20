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

CAPABILITY_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "generate_videos": {
        "capability_version": "2026-05-27.v1",
        "required_features": {
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        },
        "provider_capabilities_any": {
            "ltx23_image_to_video",
            "ltx_image_to_video",
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

SEVERITIES = {"info", "warning", "error", "critical"}
FEEDBACK_AUDIENCES = {"user", "expert", "debug"}


class CapabilityViolation(ValueError):
    pass


class SafetyReviewRequired(ValueError):
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
    decision_rationale: str = ""
    thinking_artifacts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def expected_artifacts_for_action(action: str) -> list[ExpectedArtifact]:
    return list(ARTIFACT_REQUIREMENTS.get(str(action or ""), []))


def ensure_runtime_requirements(action: str, context: dict[str, Any] | None) -> None:
    action_value = str(action or "")
    requirement = CAPABILITY_REQUIREMENTS.get(action_value)
    if not requirement:
        return

    runtime_context = context or {}
    runtime_features = set(runtime_context.get("runtime_features") or [])
    provider_capabilities = set(runtime_context.get("provider_capabilities") or [])
    required_features = set(requirement.get("required_features") or [])
    provider_any = set(requirement.get("provider_capabilities_any") or [])

    missing_features = sorted(required_features - runtime_features)
    if missing_features:
        raise CapabilityViolation(f"{action_value} missing runtime features: {missing_features}")

    if provider_any and not provider_any.intersection(provider_capabilities):
        raise CapabilityViolation(
            f"{action_value} missing provider capability; expected one of {sorted(provider_any)}"
        )

    expected_version = str(requirement.get("capability_version") or "")
    current_version = str((runtime_context.get("capability_versions") or {}).get(action_value) or "")
    if expected_version and current_version and _version_key(current_version) < _version_key(expected_version):
        raise CapabilityViolation(f"{action_value} requires capability {expected_version}; current {current_version}")


def ensure_safety_gate(packet: dict[str, Any]) -> None:
    action = str(packet.get("action") or "")
    risk = packet.get("risk") if isinstance(packet.get("risk"), dict) else {}
    score = float(risk.get("score") or 0.0)

    if action in DANGEROUS_ACTIONS:
        raise SafetyReviewRequired(f"dangerous action requires review: {action}")
    if score >= RISK_THRESHOLDS["high"]:
        raise SafetyReviewRequired(f"high risk packet requires review: {action}")


def _version_key(value: str) -> tuple[int, ...]:
    tail = str(value or "0").rsplit(".v", 1)[-1]
    parts: list[int] = []
    for item in tail.split("."):
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])
