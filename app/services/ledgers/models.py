"""Pydantic models for all four director ledgers."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Named constants (replaces magic numbers) ────────────────────────────────

CONTINUITY_GAP_PENALTY = 15       # score -= len(gaps) * 15
STYLE_BASE_SCORE = 45             # base for style consistency
STYLE_LOCK_WEIGHT = 35            # weight for locked refs
STYLE_REVIEW_WEIGHT = 20          # weight for reviewed shots

COST_RISK_HIGH_THRESHOLD = 20     # total_weight >= 20 → high risk
COST_RISK_WATCH_THRESHOLD = 10    # total_weight >= 10 → watch risk

IMAGE_BATCH_MAX = 4
VIDEO_BATCH_MAX = 1

HIGH_RISK_VIDEO_SHOT_THRESHOLD = 8
MEDIUM_RISK_VIDEO_SHOT_THRESHOLD = 3


# ── Shot analysis (intermediate structure, single-pass) ─────────────────────


class ShotAnalysisItem(BaseModel):
    """Pre-computed metrics for one shot (used internally by ledgers)."""

    shot_index: int
    has_prompt: bool
    has_prompt_revision: bool
    has_preflight: bool
    has_image: bool
    has_video: bool
    has_visual_quality_rules: bool
    has_voice_rules: bool
    has_humanizer_marker: bool
    needs_image: bool
    needs_video: bool
    needs_tts: bool
    image_review_status: str
    video_review_status: str
    matched_libraries: list[str]
    director_preflight_status: str
    image_review_passed: bool
    video_review_passed: bool
    has_character_lock: bool
    has_scene_lock: bool
    has_style_refs: bool
    duration: float
    prompt_text: str
    voiceover: str
    dialogue: str
    subtitle: str
    episode: int
    scene: int


class ShotAnalysis(BaseModel):
    """Aggregated shot analysis — single pass computed data."""

    total: int
    with_prompt: int
    with_selected_image: int
    with_selected_video: int
    with_prompt_revision: int
    with_preflight: int
    with_image_review: int
    with_video_review: int
    image_review_blocking: int
    video_review_blocking: int
    needs_image: int
    needs_video: int
    needs_tts: int
    has_character_lock_count: int
    has_style_refs_count: int
    has_voice_rules_count: int
    image_review_passed_count: int
    video_review_passed_count: int
    library_counts: dict[str, dict[str, int]]  # {name: {shot_count, reviewed_count}}
    per_shot: list[ShotAnalysisItem]
    shots_with_text: list[str]


# ── Ledger models ───────────────────────────────────────────────────────────


class CreativeLedger(BaseModel):
    """Creative technique coverage ledger."""

    applied: dict[str, list[str]] = Field(default_factory=dict)
    candidate: dict[str, list[str]] = Field(default_factory=dict)
    missing_by_stage: dict[str, list[str]] = Field(default_factory=dict)
    per_shot: list[dict] = Field(default_factory=list)
    applied_count: int = 0
    candidate_count: int = 0
    technique_total: int = 0
    technique_coverage: int = 0
    technique_coverage_label: str = "暂无技巧命中"
    style_consistency_score: int = 0
    style_consistency_label: str = "0分"
    shot_strategy_label: str = "待细化"
    reusable_anchor_count: int = 0
    reusable_anchor_label: str = "0 个"
    next_action_label: str = "继续复用已验证技巧"
    risk_label: str = "低"
    summary: dict = Field(default_factory=dict)


class ContinuityLedger(BaseModel):
    """Story continuity ledger."""

    episode: int = 1
    scene: int = 1
    minute_range: str = ""
    previous_scene: dict = Field(default_factory=dict)
    current_scene: dict = Field(default_factory=dict)
    next_scene: dict = Field(default_factory=dict)
    previous_segment: dict = Field(default_factory=dict)
    current_segment: dict = Field(default_factory=dict)
    next_segment: dict = Field(default_factory=dict)
    scene_goals: list[dict] = Field(default_factory=list)
    continuity_gaps: list = Field(default_factory=list)
    handoff_questions: list[str] = Field(default_factory=list)
    continuity_score: int = 100
    continuity_score_label: str = "100分"
    character_consistency_label: str = "待锁定"
    scene_bridge_label: str = "承接稳定"
    open_question_count: int = 0
    next_action_label: str = "继续下一场规划"
    risk_label: str = "低"
    scenes: list[dict] = Field(default_factory=list)


class CostRiskLedger(BaseModel):
    """Cost and risk estimation ledger."""

    risk_level: str = "ok"
    estimated_operations: dict = Field(default_factory=dict)
    estimated_image_count: int = 0
    pending_image_count: int = 0
    pending_video_count: int = 0
    pending_operation_count: int = 0
    budget_status_label: str = "正常"
    estimated_cost_label: str = ""
    retry_risk_label: str = "低"
    high_risk_shot_count: int = 0
    high_risk_shot_label: str = "0 个"
    guardrail_actions: list[str] = Field(default_factory=list)
    next_action_label: str = "保持当前计划"
    risk_label: str = "低"
    reuse_first: bool = True
    limits: dict = Field(default_factory=lambda: {
        "image_batch_max": IMAGE_BATCH_MAX,
        "video_batch_max": VIDEO_BATCH_MAX,
        "retry_only_failed_reviews": True,
    })


class QualityLedger(BaseModel):
    """Final quality readiness ledger."""

    checklist: list[dict] = Field(default_factory=list)
    ready_score: int = 0
    quality_score: int = 0
    quality_score_label: str = "0分"
    acceptance_status: str = "blocked"
    acceptance_status_label: str = "未通过"
    pass_rate: int = 0
    pass_rate_label: str = "0%"
    pending_review_count: int = 0
    pending_review_label: str = "0 项"
    next_action_label: str = "生成预览小样"
    risk_label: str = "低"
    blocking_items: list[dict] = Field(default_factory=list)
    missing_video_shots: list[int] = Field(default_factory=list)
    review_blockers: list[dict] = Field(default_factory=list)
    has_final_edit_plan: bool = False
    produced_video_count: int = 0
