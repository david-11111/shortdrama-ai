"""Shared Pydantic models for all service layers.

Centralizes types that are currently duplicated as raw dicts,
inline tuple constants, or ad-hoc dataclasses across services.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums (shared across all services) ──────────────────────────────────────


class ProductionStatus(StrEnum):
    """Deterministic lifecycle status for runs, stages, and tasks."""

    CREATED = "created"
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    DISPATCHING = "dispatching"
    VERIFYING = "verifying"
    WRITING_BACK = "writing_back"
    GENERATING_IMAGE = "generating_image"
    GENERATING_VIDEO = "generating_video"
    PROVIDER_WAITING = "provider_waiting"
    PROVIDER_REQUESTING = "provider_requesting"
    COMPLETED = "completed"
    DONE = "done"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"

    @classmethod
    def terminal_done(cls) -> set[ProductionStatus]:
        return {cls.DONE, cls.COMPLETED}

    @classmethod
    def terminal_failed(cls) -> set[ProductionStatus]:
        return {cls.FAILED, cls.DEAD_LETTER, cls.CANCELLED}

    @classmethod
    def active(cls) -> set[ProductionStatus]:
        return {
            cls.CREATED,
            cls.QUEUED,
            cls.PENDING,
            cls.RUNNING,
            cls.RETRYING,
            cls.DISPATCHING,
            cls.VERIFYING,
            cls.WRITING_BACK,
            cls.GENERATING_IMAGE,
            cls.GENERATING_VIDEO,
            cls.PROVIDER_WAITING,
            cls.PROVIDER_REQUESTING,
        }

    @classmethod
    def terminal(cls) -> set[ProductionStatus]:
        return cls.terminal_done() | cls.terminal_failed() | {cls.CANCELLED, cls.BLOCKED}


class ReviewStatus(StrEnum):
    """Review result statuses used across image/video reviews."""

    PASS = "pass"
    PASSED = "passed"
    APPROVED = "approved"
    OK = "ok"
    USABLE = "usable"
    NEEDS_REVIEW = "needs_review"
    REGENERATE = "regenerate"
    FAILED = "failed"
    FAIL = "fail"
    REJECTED = "rejected"
    BLOCKED = "blocked"

    @classmethod
    def passing(cls) -> set[ReviewStatus]:
        return {cls.PASS, cls.PASSED, cls.APPROVED, cls.OK, cls.USABLE}

    @classmethod
    def blocking(cls) -> set[ReviewStatus]:
        return {cls.NEEDS_REVIEW, cls.REGENERATE, cls.FAILED, cls.FAIL, cls.REJECTED, cls.BLOCKED}


class TransactionType(StrEnum):
    """Credit transaction ledger types."""

    RESERVE = "reserve"
    CHARGE = "charge"
    REFUND = "refund"


class CreditOperation(StrEnum):
    """Known billable operations."""

    VIDEO_GEN_5S = "video_gen_5s"
    VIDEO_GEN_8S = "video_gen_8s"
    VIDEO_GEN_10S = "video_gen_10s"
    VIDEO_GEN_15S = "video_gen_15s"
    IMAGE_GEN = "image_gen"
    LLM_REFINE = "llm_refine"
    LLM_DIRECTOR_CHAT = "llm_director_chat"
    LLM_PLANNER_CALL = "llm_planner_call"
    FINAL_CUT_AI_PLAN = "final_cut_ai_plan"
    PIPELINE_ANALYSIS = "pipeline_analysis"
    TTS_SYNTHESIS = "tts_synthesis"


class Operator(StrEnum):
    """Comparison operators for condition matching in gate rules."""

    EQ = "=="
    NE = "!="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    TRUTHY = "truthy"
    FALSY = "falsy"
    ALL_ZERO = "all_zero"


class RiskLevel(StrEnum):
    OK = "ok"
    WATCH = "watch"
    HIGH = "high"
    BLOCKED = "blocked"


# ── Pydantic models ─────────────────────────────────────────────────────────


class ShotRow(BaseModel):
    """A single shot row — the core unit of production work.

    Kept intentionally flat; all optional fields default to empty so that
    callers can pass partial dicts.
    """

    shot_index: int = 0
    prompt: str = ""
    raw_text: str = ""
    scene_description: str = ""
    status: str = ""

    # Reference bindings
    character_refs: list[str] = Field(default_factory=list)
    scene_refs: list[str] = Field(default_factory=list)
    prop_refs: list[str] = Field(default_factory=list)
    costume_refs: list[str] = Field(default_factory=list)
    style_refs: list[str] = Field(default_factory=list)
    character_refs_json: list[str] = Field(default_factory=list)
    scene_refs_json: list[str] = Field(default_factory=list)
    prop_refs_json: list[str] = Field(default_factory=list)
    costume_refs_json: list[str] = Field(default_factory=list)
    style_refs_json: list[str] = Field(default_factory=list)

    # Selected media
    selected_image: str = ""
    selected_video: str = ""

    # Review state
    image_candidate: dict[str, Any] = Field(default_factory=dict)
    video_variants: list[dict[str, Any]] = Field(default_factory=list)
    image_candidates: list[dict[str, Any]] = Field(default_factory=list)
    selected_image_candidate: dict[str, Any] = Field(default_factory=dict)
    selected_video_candidate: dict[str, Any] = Field(default_factory=dict)
    image_review: dict[str, Any] = Field(default_factory=dict)
    image_review_result: dict[str, Any] = Field(default_factory=dict)
    video_review: dict[str, Any] = Field(default_factory=dict)
    video_review_result: dict[str, Any] = Field(default_factory=dict)

    # Quality & technique
    matched_libraries: list[str] = Field(default_factory=list)
    prompt_revision: dict[str, Any] = Field(default_factory=dict)
    director_preflight: dict[str, Any] = Field(default_factory=dict)
    visual_quality_rules: dict[str, Any] = Field(default_factory=dict)
    motion_controls: dict[str, Any] = Field(default_factory=dict)
    voice_delivery_rules: dict[str, Any] = Field(default_factory=dict)

    # Anchor locks
    lock_character: bool = False
    lock_scene: bool = False
    lock_costume: bool = False
    lock_prop: bool = False

    # Execution context
    execution_plan: dict[str, Any] = Field(default_factory=dict)
    continuity: dict[str, Any] = Field(default_factory=dict)
    revision_source: str = ""
    source: str = ""

    # Episode / scene
    episode: int = 1
    scene: int = 1
    episode_index: int | None = None
    scene_index: int | None = None
    episode_scene: str = ""
    duration: float = 5.0
    duration_seconds: float | None = None

    # Project / run
    project_id: str = ""
    run_id: str = ""

    model_config = {"extra": "ignore", "frozen": True}


class GateResult(BaseModel):
    """Result of evaluating a single production-stage gate."""

    allowed: bool = True
    action: str = ""
    stage_id: str = ""
    reason: str = ""
    missing: list[str] = Field(default_factory=list)
    recovery: str = ""
    status: str = "pending"
    stats: dict[str, Any] = Field(default_factory=dict)


class ActionIntent(BaseModel):
    """Parsed user/intent — action + confidence + matched keywords."""

    action: str = ""
    confidence: float = 0.0
    matched: tuple[str, ...] = ()
    source: str = "natural_language_rule"

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


# ── Conversion helpers ──────────────────────────────────────────────────────


def as_shot_rows(raw: list[dict[str, Any]]) -> list[ShotRow]:
    """Convert a list of raw dicts to validated ``ShotRow`` instances.

    Invalid rows are silently dropped — this is intentional: a corrupt shot
    should not crash the entire ledger computation.
    """
    out: list[ShotRow] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out.append(ShotRow(**item))
        except Exception:
            continue
    return out


def dict_get_str(d: dict[str, Any], *keys: str, default: str = "") -> str:
    """First non-empty string value among *keys*, or *default*."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def dict_get_int(d: dict[str, Any], *keys: str, default: int = 0) -> int:
    """First integer value among *keys*, or *default*."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return default


def dict_get_float(d: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    """First float value among *keys*, or *default*."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def safe_list(value: Any) -> list[Any]:
    """Wrap non-list values into a list; pass through lists; empty otherwise."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    return [value]


def safe_dict(value: Any) -> dict[str, Any]:
    """Wrap non-dict values into an empty dict."""
    return value if isinstance(value, dict) else {}
