"""Policy definitions — the formal production stage DAG.

Every stage has:
- ``id``: unique key (``generate_keyframes``, etc.)
- ``title``: human-readable English
- ``action``: the action string used in routing
- ``deps``: stage IDs that must be completed before this one runs
- ``gates``: conditions that block the stage; each has a
  ``missing_item`` code and a ``reason`` shown to the user.
- ``status_rules``: conditions that determine whether the stage is
  ``pending`` / ``running`` / ``completed``.
- ``progress_metric``: the ``stats`` key used to render a progress bar.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.types import Operator as Op


# ── Operator dispatch (module-level, never rebuilt) ─────────────────────────
import operator as _builtin_op

_OPERATORS = {
    Op.EQ: _builtin_op.eq,
    Op.NE: _builtin_op.ne,
    Op.GT: _builtin_op.gt,
    Op.GE: _builtin_op.ge,
    Op.LT: _builtin_op.lt,
    Op.LE: _builtin_op.le,
}


# ── Model types ─────────────────────────────────────────────────────────────


class Condition(BaseModel):
    """A single condition: stats[metric] ``op`` expected."""

    metric: str
    op: Op
    expected: Any = None

    def evaluate(self, stats: dict[str, Any]) -> bool:
        value = stats.get(self.metric)
        if self.op == Op.TRUTHY:
            return bool(value)
        if self.op == Op.FALSY:
            return not bool(value)
        if self.op == Op.ALL_ZERO:
            return all(int(stats.get(name) or 0) == 0 for name in self.expected or ())
        op_fn = _OPERATORS.get(self.op)
        if op_fn is None:
            return False
        return op_fn(value, self.expected)


class GateRule(BaseModel):
    """A gate that blocks the stage if its condition is truthy."""

    condition: Condition
    missing_item: str
    reason: str


class StatusRule(BaseModel):
    """When *all* conditions are met, the stage enters *status*."""

    status: str
    conditions: list[Condition] = Field(default_factory=list)

    def evaluate(self, stats: dict[str, Any]) -> bool:
        return all(c.evaluate(stats) for c in self.conditions)


class ReworkTrigger(BaseModel):
    """A condition that, when met, triggers a rework to ``back_to`` stage.

    ``scope`` determines how much work is re-done:
    - ``"affected"`` — only the shots/items that triggered the rework
    - ``"all"`` — restart the entire stage

    ``max_retries`` limits how many times the system will auto-rework
    before escalating to ``retry_exhausted_action``.

    ``retry_exhausted_action`` — what to do when retries are exhausted:
    - ``"skip_shot"`` — auto-skip the failing shots and continue
    - ``"change_provider"`` — switch to a different video provider and retry
    - ``"human_review"`` — block and wait for human intervention

    ``depth`` — how deep the rework goes:
    - ``"shallow"`` — restart only the ``back_to`` stage; keep upstream
      outputs (e.g. keep selected_image when redoing generate_videos)
    - ``"deep"`` — cascade to upstream stages too (future use)

    ``reason`` is surfaced to front-end so the user sees *why* they're
    being sent back.
    """

    condition: Condition
    back_to: str
    scope: str = "affected"  # "affected" | "all"
    max_retries: int = 3
    retry_exhausted_action: str = "skip_shot"  # "skip_shot" | "human_review"
    depth: str = "shallow"  # "shallow" | "deep"
    reason: str = ""


class ProductionPolicy(BaseModel):
    """Complete specification for one production stage."""

    id: str
    title: str
    action: str
    depends_on: tuple[str, ...] = ()
    gates: tuple[GateRule, ...] = ()
    status_rules: tuple[StatusRule, ...] = ()
    progress_metric: str = ""
    rework_triggers: tuple[ReworkTrigger, ...] = ()


# ── Helper constructors ─────────────────────────────────────────────────────


def _c(metric: str, op: str, expected: Any = None) -> Condition:
    return Condition(metric=metric, op=Op(op), expected=expected)


def _g(metric: str, op: str, expected: Any, missing_item: str, reason: str) -> GateRule:
    return GateRule(condition=_c(metric, op, expected), missing_item=missing_item, reason=reason)


def _r(status: str, *conditions: Condition) -> StatusRule:
    return StatusRule(status=status, conditions=list(conditions))


def _rework(back_to: str, metric: str, op: str, expected: Any = None, *,
            scope: str = "affected", max_retries: int = 3,
            retry_exhausted_action: str = "skip_shot", depth: str = "shallow",
            reason: str = "") -> ReworkTrigger:
    """Shortcut to build a rework trigger."""
    return ReworkTrigger(
        condition=Condition(metric=metric, op=Op(op), expected=expected),
        back_to=back_to,
        scope=scope,
        max_retries=max_retries,
        retry_exhausted_action=retry_exhausted_action,
        depth=depth,
        reason=reason,
    )


# ── Reusable gates ──────────────────────────────────────────────────────────

NEED_SHOTS = _g("shot_count", "<=", 0, "shot_rows", "Script/storyboard rows must exist before visual assets or keyframes.")
NEED_VIDEO = _g("selected_video_count", "<=", 0, "selected_video", "At least one selected video is required before audio/final cut.")


# ── Master policy list (order is the execution DAG) ─────────────────────────

PRODUCTION_POLICIES: tuple[ProductionPolicy, ...] = (
    ProductionPolicy(id="read_context", title="Read project context", action="analyze_project", status_rules=(_r("completed"),)),
    ProductionPolicy(
        id="generate_story_plan",
        title="Generate script and storyboard plan",
        action="generate_story_plan",
        status_rules=(_r("completed", _c("shot_count", ">", 0)),),
    ),
    ProductionPolicy(
        id="plan_visual_assets",
        title="Plan visual assets",
        action="plan_visual_assets",
        depends_on=("generate_story_plan",),
        gates=(NEED_SHOTS,),
        status_rules=(_r("completed", _c("shot_count", ">", 0)),),
    ),
    ProductionPolicy(
        id="lock_assets",
        title="Lock reusable assets",
        action="lock_assets",
        depends_on=("generate_story_plan",),
        gates=(NEED_SHOTS,),
        status_rules=(_r("completed", _c("shot_count", ">", 0)),),
    ),
    ProductionPolicy(
        id="generate_keyframes",
        title="Generate keyframes",
        action="generate_keyframes",
        depends_on=("generate_story_plan",),
        gates=(NEED_SHOTS,),
        status_rules=(
            _r("running", _c("image_task_active_count", ">", 0)),
            _r("completed", _c("image_generation_complete", "truthy")),
        ),
        progress_metric="selected_image_count",
    ),
    ProductionPolicy(
        id="review_keyframes",
        title="Review keyframes",
        action="review_keyframes",
        depends_on=("generate_keyframes",),
        gates=(
            _g("image_task_failed_count", ">", 0, "image_task_failures", "Failed keyframe tasks must be resolved before keyframe review."),
            _g("image_tasks_or_selected_images", "all_zero", ("image_task_count", "selected_image_count"), "image_tasks_or_selected_images", "Keyframe generation must run before keyframe review."),
            _g("image_review_blocking_count", ">", 0, "image_review_blockers", "关键帧审查发现不合格镜头，需要先重做关键帧，再进入视频生成。"),
        ),
        status_rules=(_r("completed", _c("image_generation_complete", "truthy")),),
        progress_metric="selected_image_count",
        rework_triggers=(
            _rework(
                back_to="generate_keyframes",
                metric="image_review_blocking_count",
                op=">",
                expected=0,
                scope="affected",
                reason="关键帧审查发现不合格镜头，返回生成关键帧阶段重做。",
            ),
        ),
    ),
    ProductionPolicy(
        id="generate_videos",
        title="Generate videos",
        action="generate_videos",
        depends_on=("review_keyframes",),
        gates=(
            _g("selected_image_count", "<=", 0, "selected_image", "At least one selected keyframe is required before video generation."),
            _g("image_review_blocking_count", ">", 0, "image_review_blockers", "关键帧审查发现不合格镜头，需要先重做关键帧，再进入视频生成。"),
        ),
        status_rules=(
            _r("running", _c("video_task_active_count", ">", 0)),
            _r("completed", _c("video_generation_complete", "truthy")),
        ),
        progress_metric="selected_video_count",
    ),
    ProductionPolicy(
        id="review_videos",
        title="Review videos",
        action="review_videos",
        depends_on=("generate_videos",),
        gates=(
            _g("video_task_failed_count", ">", 0, "video_task_failures", "Failed video tasks must be resolved before video review."),
            _g("video_tasks_or_selected_videos", "all_zero", ("video_task_count", "selected_video_count"), "video_tasks_or_selected_videos", "Video generation must run before video review."),
            _g("video_review_blocking_count", ">", 0, "video_review_blockers", "视频审查发现不合格镜头，需要先重做视频片段，再进入最终剪辑。"),
        ),
        status_rules=(_r("completed", _c("video_generation_complete", "truthy")),),
        progress_metric="selected_video_count",
        rework_triggers=(
            _rework(
                back_to="generate_videos",
                metric="video_review_blocking_count",
                op=">",
                expected=0,
                scope="affected",
                reason="视频审查发现不合格镜头，返回生成视频阶段重做。",
            ),
        ),
    ),
    ProductionPolicy(
        id="audio_subtitles",
        title="Produce audio, subtitles and BGM",
        action="audio_subtitles",
        gates=(NEED_VIDEO,),
        status_rules=(_r("completed", _c("final_video_url", "truthy")),),
    ),
    ProductionPolicy(
        id="final_cut",
        title="Build final cut",
        action="plan_final_edit",
        gates=(
            NEED_VIDEO,
            _g("video_review_blocking_count", ">", 0, "video_review_blockers", "视频审查发现不合格镜头，需要先重做视频片段，再进入剪辑成片。"),
        ),
        status_rules=(_r("completed", _c("final_video_url", "truthy")),),
    ),
    ProductionPolicy(
        id="quality_check",
        title="Quality check",
        action="quality_check",
        depends_on=("final_cut",),
        gates=(_g("final_video_url", "falsy", None, "final_video_url", "A final exported video is required before quality check."),),
        status_rules=(_r("completed", _c("final_video_url", "truthy")),),
    ),
    ProductionPolicy(
        id="writeback_review",
        title="Write back and review",
        action="writeback_review",
        status_rules=(_r("completed"),),
    ),
)

# ── Index maps ──────────────────────────────────────────────────────────────

POLICY_VERSION = "commercial_production_policy_v2"
POLICY_BY_STAGE_ID: dict[str, ProductionPolicy] = {p.id: p for p in PRODUCTION_POLICIES}
STAGE_BY_ID: dict[str, ProductionPolicy] = POLICY_BY_STAGE_ID
STAGE_BY_ACTION: dict[str, ProductionPolicy] = {p.action: p for p in PRODUCTION_POLICIES}


def validate_policy_graph() -> dict[str, Any]:
    """Validate the DAG: no duplicate IDs, no missing deps, no cycles.

    Returns a report dict with ``valid`` boolean — call during app startup.
    """
    ids = [p.id for p in PRODUCTION_POLICIES]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    missing: dict[str, list[str]] = {}
    for p in PRODUCTION_POLICIES:
        bad = [dep for dep in p.depends_on if dep not in ids]
        if bad:
            missing[p.id] = bad
    cycles = _detect_cycles({p.id: p.depends_on for p in PRODUCTION_POLICIES})
    return {
        "version": POLICY_VERSION,
        "stage_count": len(PRODUCTION_POLICIES),
        "duplicate_ids": duplicates,
        "missing_dependencies": missing,
        "cycles": cycles,
        "valid": not duplicates and not missing and not cycles,
    }


def _detect_cycles(graph: dict[str, tuple[str, ...]]) -> list[list[str]]:
    """DFS cycle detection — returns all cycles found."""
    cycles: list[list[str]] = []
    stack: list[str] = []
    seen: set[str] = set()

    def _visit(node: str) -> None:
        if node in stack:
            cycles.append(stack[stack.index(node):] + [node])
            return
        if node in seen:
            return
        stack.append(node)
        for dep in graph.get(node, ()):
            _visit(dep)
        stack.pop()
        seen.add(node)

    for node in graph:
        _visit(node)
    return cycles


# ── Legacy alias resolver (injectable) ──────────────────────────────────────

def resolve_node_id(action: str, registry_lookup=None) -> str:
    """Resolve an action string to a policy node ID.

    Accepts an optional ``registry_lookup`` callable to break the circular
    dependency on ``app.services.action_registry.node_id_for_action``.
    """
    if registry_lookup is not None:
        nid = registry_lookup(action)
        if nid:
            return nid
    _FALLBACK: dict[str, str] = {
        "analyze_project": "read_context",
        "plan_scene": "plan_shots",
        "generate_storyboard": "plan_shots",
        "review_keyframes": "generate_keyframes",
        "review_videos": "generate_videos",
        "audio_subtitles": "audio_subtitles",
        "final_cut": "ffmpeg_export",
        "quality_check": "quality_check",
    }
    return _FALLBACK.get(action, "writeback")


# ── Legacy ProductionStage tuple (backward-compatible for callers that
#     imported PRODUCTION_STAGES from agent_run_state_machine) ─────────────────

PRODUCTION_STAGES: tuple = tuple(
    stage for stage in PRODUCTION_POLICIES
)
