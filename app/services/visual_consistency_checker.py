"""Visual Consistency Checker (自动化视觉一致性检查器)

Checks a project's shot rows for cross-shot consistency issues *without*
inspecting actual pixels. All checks operate on structured metadata:

  1. **Prompt conflict detection**: Do the same character's descriptions
     contradict each other across shots?
  2. **Reference binding drift**: Do adjacent shots of the same scene share
     consistent reference-image bindings?
  3. **Anchor-lock drift**: Are character/scene locks consistently applied
     across all shots that reference that entity?
  4. **Style jump warning**: Do adjacent shots use different style_refs
     without an intermediate transition?

Each check produces ``ObservationSignal``-compatible dicts that can be
published through the existing ``main_chain_observer`` pipeline or attached
to the snapshot as ``evidence.evidence_layers``.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.services.agent_runtime_contracts import ObservationSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

CHECKS_REGISTERED = [
    "prompt_conflicts",
    "ref_binding_drift",
    "lock_drift",
    "style_jumps",
]
"""Names of all registered consistency checks."""


def check_all(shots: list[dict[str, Any]]) -> list[ObservationSignal]:
    """Run every registered consistency check against a list of shot rows.

    Args:
        shots: List of shot-row dicts, ordered by ``shot_index``.

    Returns:
        A list of ``ObservationSignal`` objects. Each signal's ``type``
        starts with ``"VISUAL_*"`` and its ``severity`` is one of
        ``"info"``, ``"warning"``, or ``"error"``.
    """
    if not shots:
        return []

    signals: list[ObservationSignal] = []

    signals.extend(_check_prompt_conflicts(shots))
    signals.extend(_check_ref_binding_drift(shots))
    signals.extend(_check_lock_drift(shots))
    signals.extend(_check_style_jumps(shots))

    return signals


# ---------------------------------------------------------------------------
# 1. Prompt conflict detection
# ---------------------------------------------------------------------------

# Extended CJK range: covers Unified Ideographs Extensions A through G
# (replaces the old [一-鿿] which missed rare characters)
_CJK = "[一-鿟㐀-䶿豈-﫿\U00020000-\U0002a6df\U0002a700-\U0002b73f\U0002b740-\U0002b81f\U0002b820-\U0002ceaf\U0002ceb0-\U0002ebe0\U00030000-\U0003134f]"

_CHARACTER_ENTITY_PATTERN = re.compile(
    r"[（\(]?\s*(角色|character|人物)[：:]\s*([^）\)，,。.]+)"
    rf"|({_CJK}{{2,6}}(?:先生|女士|小姐|医生|警察|老师|同学|老板|顾客))"
    rf"|({_CJK}{{2,4}}(?:是{_CJK}{{1,6}}(?:的)?{_CJK}{{0,4}}))",
)
"""Rough Chinese entity extractor — finds ``(角色: 名字)`` patterns and
common role titles.  This is intentionally simple; a production version
should use the project's character registry from the script/plan."""


@dataclass
class _CharacterDescriptor:
    """A character's description extracted from a shot prompt."""

    character: str
    shot_index: int
    age_hints: list[str] = field(default_factory=list)
    clothing_hints: list[str] = field(default_factory=list)
    appearance_hints: list[str] = field(default_factory=list)
    action_hints: list[str] = field(default_factory=list)

    def conflicts_with(self, other: _CharacterDescriptor) -> list[str]:
        """Return a list of textual conflict descriptions, or empty list."""
        conflicts: list[str] = []
        # Age contradictions
        age_conflict = _pick_conflict(self.age_hints, other.age_hints)
        if age_conflict:
            conflicts.append(
                f"角色「{self.character}」镜头{self.shot_index}({age_conflict[0]}) "
                f"vs 镜头{other.shot_index}({age_conflict[1]})"
            )
        # Clothing contradictions
        cloth_conflict = _pick_conflict(self.clothing_hints, other.clothing_hints)
        if cloth_conflict:
            conflicts.append(
                f"角色「{self.character}」服装冲突: "
                f"镜头{self.shot_index}({cloth_conflict[0]}) "
                f"vs 镜头{other.shot_index}({cloth_conflict[1]})"
            )
        return conflicts


def _check_prompt_conflicts(shots: list[dict[str, Any]]) -> list[ObservationSignal]:
    """Detect contradictory character descriptions across shots."""
    descriptors = _extract_character_descriptors(shots)
    signals: list[ObservationSignal] = []

    # Group by character name
    by_character: dict[str, list[_CharacterDescriptor]] = defaultdict(list)
    for d in descriptors:
        by_character[d.character].append(d)

    for character, descs in by_character.items():
        if len(descs) < 2:
            continue
        # Compare first vs rest. In a full implementation you'd compare
        # every pair with a configurable distance threshold.
        first = descs[0]
        for later in descs[1:]:
            conflicts = first.conflicts_with(later)
            for conflict_desc in conflicts:
                signals.append(
                    ObservationSignal(
                        type="VISUAL_PROMPT_CONFLICT",
                        severity="warning",
                        source="consistency_checker.prompt_conflicts",
                        run_id="",
                        stage_id="review_keyframes",
                        summary=f"Prompt conflict: {conflict_desc}",
                        evidence_refs=[
                            {"kind": "shot", "shot_index": first.shot_index},
                            {"kind": "shot", "shot_index": later.shot_index},
                            {"kind": "character", "name": character},
                        ],
                        suggested_recovery="align_character_description",
                        raw={
                            "character": character,
                            "descriptor_a": first.__dict__,
                            "descriptor_b": later.__dict__,
                        },
                    )
                )

    return signals


def _extract_character_descriptors(shots: list[dict[str, Any]]) -> list[_CharacterDescriptor]:
    """Parse character descriptors from each shot's prompt and refs."""
    results: list[_CharacterDescriptor] = []
    for shot in shots:
        prompt = str(shot.get("prompt") or "")
        shot_index = int(shot.get("shot_index") or 0)
        character_refs = _as_string_list(
            shot.get("character_refs") or shot.get("character_refs_json") or []
        )

        # If no explicit character refs are bound, try to extract from prompt
        found_names = _CHARACTER_ENTITY_PATTERN.findall(prompt)
        names = set(character_refs) | {g for group in found_names for g in group if g.strip()}

        for name in names:
            if not name.strip():
                continue
            d = _CharacterDescriptor(character=name.strip(), shot_index=shot_index)
            _parse_age_hints(prompt, d)
            _parse_clothing_hints(prompt, d)
            _parse_appearance_hints(prompt, d)
            results.append(d)

    return results


# ---------------------------------------------------------------------------
# 2. Reference-binding drift
# ---------------------------------------------------------------------------

_REF_FIELDS = ("character_refs", "scene_refs", "prop_refs", "costume_refs", "style_refs")


def _check_ref_binding_drift(shots: list[dict[str, Any]]) -> list[ObservationSignal]:
    """Detect adjacent shots in the same scene that use different references.

    This catches cases where a character's face changes because different
    reference images were bound to adjacent shots.
    """
    signals: list[ObservationSignal] = []
    grouped = _group_shots_by_scene(shots)

    for scene_key, scene_shots in grouped.items():
        for field in _REF_FIELDS:
            _detect_drift_in_field(scene_key, scene_shots, field, signals)

    return signals


def _detect_drift_in_field(
    scene_key: str,
    scene_shots: list[dict[str, Any]],
    field: str,
    signals: list[ObservationSignal],
) -> None:
    """Compare reference bindings for *field* across consecutive shots."""
    prev_assets: set[str] | None = None
    prev_shot_index: int | None = None

    for shot in sorted(scene_shots, key=lambda s: int(s.get("shot_index") or 0)):
        assets = set(_as_string_list(shot.get(field) or shot.get(f"{field}_json") or []))
        shot_index = int(shot.get("shot_index") or 0)

        if prev_assets is not None and assets != prev_assets and assets and prev_assets:
            # Assets changed — signal if the overlap is small
            overlap = assets & prev_assets
            if not overlap or len(overlap) < max(len(assets), len(prev_assets)) * 0.5:
                signals.append(
                    ObservationSignal(
                        type="VISUAL_REF_DRIFT",
                        severity="warning",
                        source="consistency_checker.ref_binding_drift",
                        run_id="",
                        stage_id="review_keyframes",
                        summary=(
                            f"场次 {scene_key}: {field} 在镜头 {prev_shot_index} 和 "
                            f"{shot_index} 之间发生了显著变更"
                        ),
                        evidence_refs=[
                            {"kind": "shot", "shot_index": prev_shot_index},
                            {"kind": "shot", "shot_index": shot_index},
                            {"kind": "reference_field", "field": field},
                            {"kind": "prev_assets", "assets": list(prev_assets)},
                            {"kind": "curr_assets", "assets": list(assets)},
                        ],
                        suggested_recovery="review_reference_binding",
                        raw={
                            "scene": scene_key,
                            "field": field,
                            "prev_shot": prev_shot_index,
                            "curr_shot": shot_index,
                            "prev_assets": list(prev_assets),
                            "curr_assets": list(assets),
                        },
                    )
                )
        prev_assets = assets
        prev_shot_index = shot_index


# ---------------------------------------------------------------------------
# 3. Anchor-lock drift
# ---------------------------------------------------------------------------

_LOCK_FIELDS = ("lock_character", "lock_scene", "lock_costume", "lock_prop")


def _check_lock_drift(shots: list[dict[str, Any]]) -> list[ObservationSignal]:
    """Detect inconsistent anchor-lock states across shots.

    If a character's lock is on in some shots but off in others (within the
    same scene), the visual identity may drift.
    """
    signals: list[ObservationSignal] = []
    grouped = _group_shots_by_scene(shots)

    for scene_key, scene_shots in grouped.items():
        lock_states: dict[str, set[bool]] = {f: set() for f in _LOCK_FIELDS}
        for shot in scene_shots:
            for field in _LOCK_FIELDS:
                lock_states[field].add(bool(shot.get(field, False)))

        for field, states in lock_states.items():
            if len(states) > 1:  # both True and False seen in same scene
                signals.append(
                    ObservationSignal(
                        type="VISUAL_LOCK_DRIFT",
                        severity="warning",
                        source="consistency_checker.lock_drift",
                        run_id="",
                        stage_id="review_keyframes",
                        summary=(
                            f"场次 {scene_key}: {field} 状态不一致 "
                            f"(同时存在 {(states)} 状态)"
                        ),
                        evidence_refs=[
                            {"kind": "scene", "scene_key": scene_key},
                            {"kind": "lock_field", "field": field},
                        ],
                        suggested_recovery="unify_lock_settings",
                        raw={
                            "scene": scene_key,
                            "field": field,
                            "inconsistent_states": [str(s) for s in states],
                        },
                    )
                )

    return signals


# ---------------------------------------------------------------------------
# 4. Style jump warning
# ---------------------------------------------------------------------------


def _check_style_jumps(shots: list[dict[str, Any]]) -> list[ObservationSignal]:
    """Warn when adjacent shots use entirely different style references.

    A style change across a scene boundary is expected; a change *within*
    the same scene may indicate a visual discontinuity.
    """
    signals: list[ObservationSignal] = []
    sorted_shots = sorted(shots, key=lambda s: int(s.get("shot_index") or 0))

    for i in range(1, len(sorted_shots)):
        prev = sorted_shots[i - 1]
        curr = sorted_shots[i]
        prev_style = set(_as_string_list(prev.get("style_refs") or prev.get("style_refs_json") or []))
        curr_style = set(_as_string_list(curr.get("style_refs") or curr.get("style_refs_json") or []))
        prev_idx = int(prev.get("shot_index") or 0)
        curr_idx = int(curr.get("shot_index") or 0)

        # Only flag if both have explicit style refs AND they're disjoint
        if prev_style and curr_style and not (prev_style & curr_style):
            # Check if there's a scene boundary between them
            prev_scene = prev.get("scene") or prev.get("episode_scene") or ""
            curr_scene = curr.get("scene") or curr.get("episode_scene") or ""
            same_scene = prev_scene == curr_scene

            severity = "warning" if same_scene else "info"
            signals.append(
                ObservationSignal(
                    type="VISUAL_STYLE_JUMP",
                    severity=severity,
                    source="consistency_checker.style_jumps",
                    run_id="",
                    stage_id="review_keyframes",
                    summary=(
                        f"镜头 {prev_idx} → {curr_idx} 风格参考图完全变更"
                        f"{' (同一场次内!)' if same_scene else ' (跨场次, 可接受)'}"
                    ),
                    evidence_refs=[
                        {"kind": "shot", "shot_index": prev_idx},
                        {"kind": "shot", "shot_index": curr_idx},
                        {"kind": "prev_style_refs", "assets": list(prev_style)},
                        {"kind": "curr_style_refs", "assets": list(curr_style)},
                    ],
                    suggested_recovery="review_style_transition",
                    raw={
                        "prev_shot": prev_idx,
                        "curr_shot": curr_idx,
                        "prev_style_refs": list(prev_style),
                        "curr_style_refs": list(curr_style),
                        "same_scene": same_scene,
                    },
                )
            )

    return signals


# ---------------------------------------------------------------------------
# Scene grouping helper
# ---------------------------------------------------------------------------


def _group_shots_by_scene(shots: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group shot rows by their ``scene`` or ``episode_scene`` field.

    Falls back to placing all shots under a single ``"_unknown"`` key.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for shot in shots:
        scene_key = str(shot.get("scene") or shot.get("episode_scene") or "_unknown")
        groups[scene_key].append(shot)
    return dict(groups)


# ---------------------------------------------------------------------------
# Text-parsing helpers
# ---------------------------------------------------------------------------

_AGE_KEYWORDS = {
    "老年", "年迈", "老",  # elderly
    "中年",  # middle-aged
    "青年", "年轻", "少年", "少女", "小男孩", "小女孩",  # young
    "儿童", "小孩", "孩子",  # child
}
_CLOTHING_KEYWORDS_RE = re.compile(
    rf"(穿着|身穿|身着|穿着|戴|戴着|系着|披着)"
    rf"{_CJK}{{2,20}}(?:的)?"
)
_APPEARANCE_KEYWORDS = {
    "长发", "短发", "卷发", "直发", "马尾", "盘发", "光头",
    "戴眼镜", "戴墨镜", "胡子", "胡须", "胡子拉碴",
    "浓眉", "细眉", "大眼睛", "小眼睛",
    "高鼻梁", "鹰钩鼻",
    "厚嘴唇", "薄嘴唇",
    "圆脸", "方脸", "瓜子脸", "长脸",
    "白皮肤", "黑皮肤", "小麦色皮肤",
    "强壮", "瘦弱", "高大", "矮小", "丰满", "苗条",
}


def _parse_age_hints(prompt: str, d: _CharacterDescriptor) -> None:
    """Extract age-related keywords from prompt."""
    for kw in _AGE_KEYWORDS:
        if kw in prompt:
            d.age_hints.append(kw)


def _parse_clothing_hints(prompt: str, d: _CharacterDescriptor) -> None:
    """Extract clothing descriptions from prompt."""
    for match in _CLOTHING_KEYWORDS_RE.finditer(prompt):
        d.clothing_hints.append(match.group(0)[:30])


def _parse_appearance_hints(prompt: str, d: _CharacterDescriptor) -> None:
    """Extract appearance keywords from prompt."""
    for kw in _APPEARANCE_KEYWORDS:
        if kw in prompt:
            d.appearance_hints.append(kw)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _as_string_list(value: Any) -> list[str]:
    """Normalise a value to a list of strings (handles JSON arrays too)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    return []


def _pick_conflict(a: list[str], b: list[str]) -> tuple[str, str] | None:
    """If *a* and *b* each have hints and none overlap, return one pair."""
    if not a or not b:
        return None
    set_a, set_b = set(a), set(b)
    if not (set_a & set_b):
        return (a[0], b[0])
    return None
