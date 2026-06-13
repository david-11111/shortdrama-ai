"""Tests for the Visual Consistency Checker.

Covers all four check types:
  1. Prompt conflicts (same character, contradictory descriptions)
  2. Reference-binding drift (adjacent shots, different refs)
  3. Anchor-lock drift (inconsistent lock states within a scene)
  4. Style jumps (disjoint style refs across adjacent shots)
"""

from __future__ import annotations

import pytest

from app.services.visual_consistency_checker import (
    _check_lock_drift,
    _check_prompt_conflicts,
    _check_ref_binding_drift,
    _check_style_jumps,
    _group_shots_by_scene,
    check_all,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def consistent_shots() -> list[dict]:
    """Three shots with consistent character/ref/lock/style bindings."""
    return [
        {
            "shot_index": 1,
            "prompt": "角色：老王，穿着蓝色制服，戴着老花镜，站在柜台后。",
            "character_refs_json": ["char-wang-001"],
            "scene_refs_json": ["scene-store-001"],
            "style_refs_json": ["style-retro-001"],
            "lock_character": True,
            "lock_scene": True,
            "scene": "scene_1",
        },
        {
            "shot_index": 2,
            "prompt": "角色：老王，穿着蓝色制服，正在接待顾客。",
            "character_refs_json": ["char-wang-001"],
            "scene_refs_json": ["scene-store-001"],
            "style_refs_json": ["style-retro-001"],
            "lock_character": True,
            "lock_scene": True,
            "scene": "scene_1",
        },
        {
            "shot_index": 3,
            "prompt": "角色：老王，穿着蓝色制服，目送顾客离开。",
            "character_refs_json": ["char-wang-001"],
            "scene_refs_json": ["scene-store-001"],
            "style_refs_json": ["style-retro-001"],
            "lock_character": True,
            "lock_scene": True,
            "scene": "scene_1",
        },
    ]


@pytest.fixture
def conflicting_shots() -> list[dict]:
    """Shots where the same character has conflicting descriptions."""
    return [
        {
            "shot_index": 1,
            "prompt": "角色：小李，年轻，穿着红色T恤，短发。",
            "character_refs_json": ["char-li-001"],
            "scene": "scene_1",
        },
        {
            "shot_index": 2,
            "prompt": "角色：小李，老年，穿着蓝色西装，长发。",
            "character_refs_json": ["char-li-001"],
            "scene": "scene_1",
        },
    ]


@pytest.fixture
def drifting_ref_shots() -> list[dict]:
    """Adjacent shots where reference bindings change significantly."""
    return [
        {
            "shot_index": 1,
            "prompt": "角色：小王。",
            "character_refs_json": ["char-wang-001", "char-wang-002"],
            "scene": "scene_1",
        },
        {
            "shot_index": 2,
            "prompt": "角色：小王。",
            "character_refs_json": ["char-wang-003", "char-wang-004"],
            "scene": "scene_1",
        },
    ]


@pytest.fixture
def lock_drift_shots() -> list[dict]:
    """Shots in the same scene with inconsistent lock states."""
    return [
        {
            "shot_index": 1,
            "prompt": "角色：张三。",
            "lock_character": True,
            "lock_scene": True,
            "scene": "scene_2",
        },
        {
            "shot_index": 2,
            "prompt": "角色：张三。",
            "lock_character": False,
            "lock_scene": True,
            "scene": "scene_2",
        },
    ]


@pytest.fixture
def style_jump_shots() -> list[dict]:
    """Adjacent shots with completely different style refs."""
    return [
        {
            "shot_index": 1,
            "prompt": "镜头1",
            "style_refs_json": ["style-warm-001"],
            "scene": "scene_1",
        },
        {
            "shot_index": 2,
            "prompt": "镜头2",
            "style_refs_json": ["style-cold-001"],
            "scene": "scene_1",
        },
    ]


@pytest.fixture
def cross_scene_style_shots() -> list[dict]:
    """Adjacent shots with different styles, but across scene boundary."""
    return [
        {
            "shot_index": 1,
            "prompt": "镜头1",
            "style_refs_json": ["style-warm-001"],
            "scene": "scene_1",
        },
        {
            "shot_index": 2,
            "prompt": "镜头2",
            "style_refs_json": ["style-cold-001"],
            "scene": "scene_2",
        },
    ]


# ---------------------------------------------------------------------------
# Scene grouping
# ---------------------------------------------------------------------------

class TestGroupShotsByScene:
    def test_groups_by_scene_field(self):
        shots = [
            {"shot_index": 1, "scene": "scene_1"},
            {"shot_index": 2, "scene": "scene_1"},
            {"shot_index": 3, "scene": "scene_2"},
        ]
        groups = _group_shots_by_scene(shots)
        assert len(groups) == 2
        assert len(groups["scene_1"]) == 2
        assert len(groups["scene_2"]) == 1

    def test_falls_back_to_unknown(self):
        shots = [{"shot_index": 1}]
        groups = _group_shots_by_scene(shots)
        assert "_unknown" in groups

    def test_empty_input(self):
        assert _group_shots_by_scene([]) == {}


# ---------------------------------------------------------------------------
# 1. Prompt conflicts
# ---------------------------------------------------------------------------

class TestPromptConflicts:
    def test_consistent_shots_no_conflicts(self, consistent_shots):
        signals = _check_prompt_conflicts(consistent_shots)
        assert len(signals) == 0

    def test_conflicting_age_triggers_signal(self, conflicting_shots):
        signals = _check_prompt_conflicts(conflicting_shots)
        # "年轻" vs "老年" is a direct conflict
        conflict_signals = [s for s in signals if s.type == "VISUAL_PROMPT_CONFLICT"]
        assert len(conflict_signals) >= 1
        signal = conflict_signals[0]
        assert signal.severity == "warning"
        assert signal.stage_id == "review_keyframes"
        assert signal.suggested_recovery == "align_character_description"
        assert len(signal.evidence_refs) >= 2

    def test_no_character_refs_no_signals(self):
        shots = [
            {"shot_index": 1, "prompt": "一只猫走过来了。", "character_refs_json": []},
            {"shot_index": 2, "prompt": "猫跳上了桌子。", "character_refs_json": []},
        ]
        signals = _check_prompt_conflicts(shots)
        assert len(signals) == 0

    def test_single_shot_no_signal(self):
        shots = [{"shot_index": 1, "prompt": "角色：老王，老年。", "character_refs_json": ["wang"]}]
        signals = _check_prompt_conflicts(shots)
        assert len(signals) == 0

    def test_prompt_conflict_type_and_source(self, conflicting_shots):
        signals = _check_prompt_conflicts(conflicting_shots)
        assert all(s.type == "VISUAL_PROMPT_CONFLICT" for s in signals)
        assert all("consistency_checker.prompt_conflicts" in s.source for s in signals)


# ---------------------------------------------------------------------------
# 2. Reference-binding drift
# ---------------------------------------------------------------------------

class TestRefBindingDrift:
    def test_consistent_refs_no_drift(self, consistent_shots):
        signals = _check_ref_binding_drift(consistent_shots)
        ref_signals = [s for s in signals if s.type == "VISUAL_REF_DRIFT"]
        assert len(ref_signals) == 0

    def test_different_refs_triggers_drift(self, drifting_ref_shots):
        signals = _check_ref_binding_drift(drifting_ref_shots)
        drift_signals = [s for s in signals if s.type == "VISUAL_REF_DRIFT"]
        assert len(drift_signals) >= 1
        assert drift_signals[0].severity == "warning"
        assert drift_signals[0].suggested_recovery == "review_reference_binding"

    def test_no_refs_no_signals(self):
        shots = [
            {"shot_index": 1, "prompt": "镜头", "character_refs_json": [], "scene": "s1"},
            {"shot_index": 2, "prompt": "镜头", "character_refs_json": [], "scene": "s1"},
        ]
        signals = _check_ref_binding_drift(shots)
        assert len([s for s in signals if s.type == "VISUAL_REF_DRIFT"]) == 0

    def test_single_shot_no_drift(self):
        shots = [{"shot_index": 1, "prompt": "镜头", "character_refs_json": ["a"], "scene": "s1"}]
        signals = _check_ref_binding_drift(shots)
        assert len([s for s in signals if s.type == "VISUAL_REF_DRIFT"]) == 0


# ---------------------------------------------------------------------------
# 3. Anchor-lock drift
# ---------------------------------------------------------------------------

class TestLockDrift:
    def test_consistent_locks_no_signal(self, consistent_shots):
        signals = _check_lock_drift(consistent_shots)
        lock_signals = [s for s in signals if s.type == "VISUAL_LOCK_DRIFT"]
        assert len(lock_signals) == 0

    def test_inconsistent_locks_triggers_signal(self, lock_drift_shots):
        signals = _check_lock_drift(lock_drift_shots)
        lock_signals = [s for s in signals if s.type == "VISUAL_LOCK_DRIFT"]
        assert len(lock_signals) >= 1
        signal = lock_signals[0]
        assert signal.severity == "warning"
        assert signal.suggested_recovery == "unify_lock_settings"
        # Should flag lock_character specifically
        assert "lock_character" in signal.summary

    def test_all_locks_off_no_signal(self):
        shots = [
            {"shot_index": 1, "lock_character": False, "lock_scene": False, "scene": "s1"},
            {"shot_index": 2, "lock_character": False, "lock_scene": False, "scene": "s1"},
        ]
        signals = _check_lock_drift(shots)
        assert len([s for s in signals if s.type == "VISUAL_LOCK_DRIFT"]) == 0

    def test_different_scenes_not_grouped_together(self):
        shots = [
            {"shot_index": 1, "lock_character": True, "scene": "s1"},
            {"shot_index": 2, "lock_character": False, "scene": "s2"},
        ]
        signals = _check_lock_drift(shots)
        assert len([s for s in signals if s.type == "VISUAL_LOCK_DRIFT"]) == 0


# ---------------------------------------------------------------------------
# 4. Style jumps
# ---------------------------------------------------------------------------

class TestStyleJumps:
    def test_consistent_styles_no_signal(self, consistent_shots):
        signals = _check_style_jumps(consistent_shots)
        assert len([s for s in signals if s.type == "VISUAL_STYLE_JUMP"]) == 0

    def test_same_scene_style_jump_is_warning(self, style_jump_shots):
        signals = _check_style_jumps(style_jump_shots)
        style_signals = [s for s in signals if s.type == "VISUAL_STYLE_JUMP"]
        assert len(style_signals) >= 1
        assert style_signals[0].severity == "warning"  # same scene
        assert style_signals[0].suggested_recovery == "review_style_transition"

    def test_cross_scene_style_change_is_info(self, cross_scene_style_shots):
        signals = _check_style_jumps(cross_scene_style_shots)
        style_signals = [s for s in signals if s.type == "VISUAL_STYLE_JUMP"]
        assert len(style_signals) >= 1
        assert style_signals[0].severity == "info"  # different scene

    def test_no_style_refs_no_signal(self):
        shots = [
            {"shot_index": 1, "prompt": "a", "style_refs_json": [], "scene": "s1"},
            {"shot_index": 2, "prompt": "b", "style_refs_json": [], "scene": "s1"},
        ]
        signals = _check_style_jumps(shots)
        assert len([s for s in signals if s.type == "VISUAL_STYLE_JUMP"]) == 0

    def test_partial_style_overlap_no_signal(self):
        shots = [
            {"shot_index": 1, "prompt": "a", "style_refs_json": ["style-a", "style-b"], "scene": "s1"},
            {"shot_index": 2, "prompt": "b", "style_refs_json": ["style-b", "style-c"], "scene": "s1"},
        ]
        signals = _check_style_jumps(shots)
        assert len([s for s in signals if s.type == "VISUAL_STYLE_JUMP"]) == 0


# ---------------------------------------------------------------------------
# Integrated check_all
# ---------------------------------------------------------------------------

class TestCheckAll:
    def test_consistent_shots_no_signals(self, consistent_shots):
        signals = check_all(consistent_shots)
        assert len(signals) == 0

    def test_empty_shots_no_signals(self):
        assert check_all([]) == []

    def test_all_issues_detected(
        self, conflicting_shots, drifting_ref_shots,
        lock_drift_shots, style_jump_shots,
    ):
        """Verify each check type independently produces signals."""
        assert len([s for s in check_all(conflicting_shots) if s.type == "VISUAL_PROMPT_CONFLICT"]) >= 1
        assert len([s for s in check_all(drifting_ref_shots) if s.type == "VISUAL_REF_DRIFT"]) >= 1
        assert len([s for s in check_all(lock_drift_shots) if s.type == "VISUAL_LOCK_DRIFT"]) >= 1
        assert len([s for s in check_all(style_jump_shots) if s.type == "VISUAL_STYLE_JUMP"]) >= 1

    def test_all_signals_have_required_fields(
        self, conflicting_shots, drifting_ref_shots,
        lock_drift_shots, style_jump_shots,
    ):
        """Every signal must have type, severity, source, stage_id, summary."""
        all_shots = conflicting_shots + drifting_ref_shots + lock_drift_shots + style_jump_shots
        signals = check_all(all_shots)
        for s in signals:
            assert s.type, "type is required"
            assert s.severity in {"info", "warning", "error"}, f"invalid severity: {s.severity}"
            assert s.source, "source is required"
            assert s.stage_id == "review_keyframes"
            assert s.summary, "summary is required"

    def test_check_names_match_registered(self):
        from app.services.visual_consistency_checker import CHECKS_REGISTERED
        # check_all should call all registered checks
        assert "prompt_conflicts" in CHECKS_REGISTERED
        assert "ref_binding_drift" in CHECKS_REGISTERED
        assert "lock_drift" in CHECKS_REGISTERED
        assert "style_jumps" in CHECKS_REGISTERED
