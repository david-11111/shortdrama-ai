import shutil
import uuid
from pathlib import Path

from app.services import project_brain, project_workspace


def _storage(monkeypatch):
    storage = Path("storage") / "test-project-brain-ledgers" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    return storage


def _persist_plan(project_id, shot_rows, *, continuity=None, reply="Director Plan"):
    project_workspace.persist_director_result_to_workspace(
        project_id,
        {
            "reply": reply,
            "continuity": continuity or {
                "character_continuity": "Hero keeps the same face, navy suit, and restrained expression.",
                "scene_continuity": "Modern jewelry store counter with warm practical lights.",
                "prop_continuity": "Gold bracelet and printed quote sheet remain visible when relevant.",
            },
            "shot_rows": shot_rows,
        },
        source="unit",
        reason="brain ledger contract",
    )


def test_creative_technique_ledger_counts_applied_candidate_and_per_shot(monkeypatch):
    storage = _storage(monkeypatch)
    try:
        _persist_plan(
            "brain-creative-ledger",
            [
                {
                    "shot_index": 1,
                    "prompt": "Shot 1: push in from the counter to the gold bracelet.",
                    "duration": 5,
                    "matched_libraries": ["dolly_push_in", "product_insert"],
                },
                {
                    "shot_index": 2,
                    "prompt": "Shot 2: reaction close-up with shallow focus.",
                    "duration": 5,
                    "matched_libraries": ["reaction_closeup"],
                },
            ],
        )

        brain = project_brain.build_project_brain(
            "brain-creative-ledger",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "Shot 1: push in from the counter to the gold bracelet.",
                    "status": "image_done",
                    "selected_image": "img-1",
                    "matched_libraries": ["dolly_push_in", "product_insert"],
                    "image_candidate": {"review_status": "usable", "review_score": 84},
                },
                {
                    "shot_index": 2,
                    "prompt": "Shot 2: reaction close-up with shallow focus.",
                    "status": "pending",
                    "matched_libraries": ["reaction_closeup"],
                    "image_candidate": {"review_status": "needs_review", "review_score": 61},
                },
            ],
        )

        ledger = brain["context"]["creative_technique_ledger"]

        assert ledger["applied_count"] == 2
        assert ledger["candidate_count"] == 1
        assert ledger["technique_total"] == 3
        assert ledger["per_shot"][1]["shot_index"] == 1
        assert ledger["per_shot"][1]["applied"] == ["dolly_push_in", "product_insert"]
        assert ledger["per_shot"][2]["candidate"] == ["reaction_closeup"]
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_creative_lowering_audit_separates_prompt_markers_from_execution_boundaries(monkeypatch):
    storage = _storage(monkeypatch)
    try:
        _persist_plan(
            "brain-creative-lowering",
            [
                {
                    "shot_index": 1,
                    "prompt": "中景缓慢推进，女主眼底泛红，手指轻轻攥住报价单。",
                    "duration": 5,
                    "matched_libraries": ["slow_push_in", "micro_expression"],
                    "dialogue": "等一下，我想先确认一件事",
                },
                {
                    "shot_index": 2,
                    "prompt": "全景展示金店柜台和围观人群，暖色顶光。",
                    "duration": 5,
                },
            ],
        )

        brain = project_brain.build_project_brain(
            "brain-creative-lowering",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "中景缓慢推进，女主眼底泛红，手指轻轻攥住报价单。",
                    "status": "video_done",
                    "selected_image": "img-1",
                    "selected_video": "vid-1",
                    "matched_libraries": ["slow_push_in", "micro_expression"],
                    "dialogue": "等一下，我想先确认一件事",
                    "tts_payload": {"text": "等一下，我想先确认一件事", "speed": 0.9},
                },
                {
                    "shot_index": 2,
                    "prompt": "全景展示金店柜台和围观人群，暖色顶光。",
                    "status": "image_done",
                    "selected_image": "img-2",
                },
            ],
            final_edit_plan={
                "clips": [{"shot_index": 1, "src": "vid-1"}],
                "settings": {"recipe_id": "cinematic_rhythm"},
            },
        )

        audit = {item["component"]: item for item in brain["context"]["creative_lowering_audit"]}

        assert audit["matched_libraries"]["coverage"] == "partial"
        assert audit["matched_libraries"]["applied_count"] == 1
        assert "shot.matched_libraries" in audit["matched_libraries"]["lowered_to"]
        assert audit["visual_quality_rules"]["coverage"] == "covered"
        assert audit["visual_quality_rules"]["code_boundary"] is True
        assert "apply_visual_quality_controls" in audit["visual_quality_rules"]["execution_boundary"]
        assert audit["video_motion_controls"]["coverage"] == "partial"
        assert audit["video_motion_controls"]["applied_count"] == 1
        assert "Seedance video prompt" in audit["video_motion_controls"]["lowered_to"]
        assert audit["voice_delivery_rules"]["coverage"] == "covered"
        assert "TTS payload.speed" in audit["voice_delivery_rules"]["lowered_to"]
        assert audit["final_cut_recipes"]["coverage"] == "covered"
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_story_continuity_ledger_reports_current_segment_and_gaps_for_multi_scene_long_plan(monkeypatch):
    storage = _storage(monkeypatch)
    try:
        _persist_plan(
            "brain-story-continuity-ledger",
            [
                {"shot_index": 1, "prompt": "Episode 1 Scene 1: hero enters the jewelry store.", "duration": 120},
                {"shot_index": 2, "prompt": "Episode 1 Scene 1: clerk reveals the bracelet price.", "duration": 120},
                {"shot_index": 3, "prompt": "Episode 1 Scene 2: hero suddenly argues in a parking garage.", "duration": 150},
                {"shot_index": 4, "prompt": "Episode 1 Scene 2: assistant appears without setup.", "duration": 150},
            ],
            continuity={
                "character_continuity": "Hero keeps same face and navy suit.",
                "scene_continuity": "Scene 1 is a jewelry store. Scene 2 must explain the move before the garage.",
            },
            reply="Director Plan: target 12 minutes with two connected scenes.",
        )

        brain = project_brain.build_project_brain(
            "brain-story-continuity-ledger",
            operational_shots=[
                {"shot_index": 1, "status": "video_done", "selected_video": "vid-1", "duration": 120},
                {"shot_index": 2, "status": "video_done", "selected_video": "vid-2", "duration": 120},
                {"shot_index": 3, "status": "image_done", "selected_image": "img-3", "duration": 150},
                {"shot_index": 4, "status": "pending", "duration": 150},
            ],
        )

        ledger = brain["context"]["story_continuity_ledger"]
        audit = {item["component"]: item for item in brain["context"]["continuity_handoff_audit"]}

        assert ledger["current_segment"]["scene_key"] in {"E01S02", "episode-01-scene-02"}
        assert ledger["current_segment"]["first_shot_index"] == 3
        assert ledger["previous_segment"]["last_shot_index"] == 2
        assert ledger["continuity_gaps"]
        assert any("Scene 1" in item.get("reason", "") or "handoff" in item.get("reason", "").lower() for item in ledger["continuity_gaps"])
        assert audit["scene_position"]["coverage"] == "covered"
        assert audit["scene_position"]["evidence"].startswith("current=E01S02")
        assert audit["minute_position"]["coverage"] == "covered"
        assert audit["previous_scene"]["coverage"] == "covered"
        assert audit["previous_scene"]["evidence"].startswith("previous=E01S01")
        assert audit["handoff_gaps"]["coverage"] == "covered"
        assert "scene_handoff_check" in audit["handoff_gaps"]["evidence"]
        assert audit["decision_influence"]["coverage"] == "covered"
        assert any(item["code"] == "story_handoff_gap" for item in brain["risks"])
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_cost_risk_ledger_flags_non_low_risk_and_guardrails_for_large_pending_batch(monkeypatch):
    storage = _storage(monkeypatch)
    try:
        _persist_plan(
            "brain-cost-risk-ledger",
            [
                {"shot_index": idx, "prompt": f"Shot {idx}: dense crowd scene with new assets.", "duration": 5}
                for idx in range(1, 19)
            ],
        )

        operational_shots = [
            {"shot_index": idx, "prompt": f"Shot {idx}: dense crowd scene with new assets.", "status": "pending"}
            for idx in range(1, 19)
        ]
        brain = project_brain.build_project_brain(
            "brain-cost-risk-ledger",
            operational_shots=operational_shots,
            visual_plan={
                "seedream_budget": {
                    "action_count": 12,
                    "bind_existing_count": 0,
                    "generate_reference_action_count": 12,
                    "unique_reference_generation_count": 12,
                    "pending_keyframe_count": 18,
                    "estimated_without_reuse": 30,
                    "estimated_seedream_images": 30,
                    "avoided_seedream_images": 0,
                    "reuse_ratio_percent": 0,
                    "budget_level": "over_budget",
                }
            },
        )

        ledger = brain["context"]["cost_risk_ledger"]
        audit = {item["component"]: item for item in brain["context"]["cost_control_audit"]}

        assert ledger["risk_level"] != "low"
        assert ledger["estimated_image_count"] >= 30
        assert ledger["pending_video_count"] >= 18
        assert ledger["limits"]["image_batch_max"] == 4
        assert ledger["limits"]["video_batch_max"] == 1
        assert ledger["guardrail_actions"]
        assert any("batch" in action.lower() or "reuse" in action.lower() for action in ledger["guardrail_actions"])
        assert audit["small_step_keyframes"]["coverage"] == "covered"
        assert "BRAIN_KEYFRAME_BATCH_MAX" in audit["small_step_keyframes"]["enforced_by"]
        assert "batch_max=4" in audit["small_step_keyframes"]["evidence"]
        assert audit["small_step_videos"]["coverage"] == "covered"
        assert "BRAIN_VIDEO_BATCH_MAX" in audit["small_step_videos"]["enforced_by"]
        assert audit["budget_gate"]["coverage"] == "covered"
        assert audit["budget_gate"]["evidence"].startswith("budget_level=over_budget")
        assert audit["credit_guard"]["coverage"] == "covered"
        assert audit["rate_concurrency_guard"]["coverage"] == "covered"
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_final_quality_ledger_blocks_when_video_bgm_or_reviews_are_missing(monkeypatch):
    storage = _storage(monkeypatch)
    try:
        _persist_plan(
            "brain-final-quality-ledger",
            [
                {"shot_index": 1, "prompt": "Shot 1: usable opening shot.", "duration": 5},
                {"shot_index": 2, "prompt": "Shot 2: missing video close-up.", "duration": 5},
                {"shot_index": 3, "prompt": "Shot 3: failed review reaction.", "duration": 5},
            ],
        )

        brain = project_brain.build_project_brain(
            "brain-final-quality-ledger",
            operational_shots=[
                {
                    "shot_index": 1,
                    "status": "video_done",
                    "selected_image": "img-1",
                    "selected_video": "vid-1",
                    "video_candidate": {"review_status": "cuttable", "review_score": 82},
                },
                {
                    "shot_index": 2,
                    "status": "image_done",
                    "selected_image": "img-2",
                    "video_candidate": {"review_status": "needs_review", "review_score": 58},
                },
                {
                    "shot_index": 3,
                    "status": "video_done",
                    "selected_image": "img-3",
                    "selected_video": "vid-3",
                    "video_candidate": {"review_status": "regenerate", "review_score": 39},
                },
            ],
            final_edit_plan={
                "clips": [
                    {"shot_index": 1, "video_url": "vid-1"},
                    {"shot_index": 3, "video_url": "vid-3"},
                ],
                "settings": {"bgm_path": ""},
            },
        )

        ledger = brain["context"]["final_quality_ledger"]
        audit = {item["component"]: item for item in brain["context"]["final_delivery_audit"]}

        assert ledger["ready_score"] < 70
        assert ledger["blocking_items"]
        assert any(item.get("code") == "missing_video" for item in ledger["blocking_items"])
        assert any(item.get("code") == "missing_bgm" for item in ledger["blocking_items"])
        assert any(item.get("code") == "review_not_passed" for item in ledger["blocking_items"])
        assert audit["video_complete"]["coverage"] == "missing"
        assert "missing_video" in audit["video_complete"]["decision_effect"]
        assert audit["bgm_ready"]["coverage"] == "missing"
        assert audit["edit_plan_complete"]["coverage"] == "covered"
        assert audit["subtitles_ready"]["coverage"] == "missing"
        assert audit["reviews_passed"]["coverage"] == "missing"
        assert audit["preview_export_ready"]["coverage"] == "missing"
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_final_delivery_audit_marks_complete_exportable_plan_ready(monkeypatch):
    storage = _storage(monkeypatch)
    try:
        _persist_plan(
            "brain-final-delivery-ready",
            [
                {"shot_index": 1, "prompt": "Shot 1: opening.", "duration": 5},
                {"shot_index": 2, "prompt": "Shot 2: close-up.", "duration": 5},
            ],
        )

        brain = project_brain.build_project_brain(
            "brain-final-delivery-ready",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "Shot 1: opening.",
                    "status": "video_done",
                    "selected_video": "vid-1",
                    "duration": 5,
                    "video_candidate": {"review_status": "passed"},
                },
                {
                    "shot_index": 2,
                    "prompt": "Shot 2: close-up.",
                    "status": "video_done",
                    "selected_video": "vid-2",
                    "duration": 5,
                    "video_candidate": {"review_status": "passed"},
                },
            ],
            final_edit_plan={
                "settings": {
                    "bgm_path": "http://audio/bgm.mp3",
                    "burn_subtitles": True,
                    "cover_title": "Ready",
                },
                "clips": [
                    {"shot_index": 1, "video_url": "vid-1", "enabled": True, "subtitle": "opening", "duration": 5},
                    {"shot_index": 2, "video_url": "vid-2", "enabled": True, "subtitle": "close-up", "duration": 5},
                ],
            },
        )

        ledger = brain["context"]["final_quality_ledger"]
        audit = {item["component"]: item for item in brain["context"]["final_delivery_audit"]}

        assert ledger["acceptance_status"] == "ready"
        assert audit["video_complete"]["coverage"] == "covered"
        assert audit["bgm_ready"]["coverage"] == "covered"
        assert audit["edit_plan_complete"]["coverage"] == "covered"
        assert audit["subtitles_ready"]["coverage"] == "covered"
        assert audit["reviews_passed"]["coverage"] == "covered"
        assert audit["preview_export_ready"]["coverage"] == "covered"
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_feedback_loop_audit_tracks_writeback_sources_for_next_brain_run(monkeypatch):
    storage = _storage(monkeypatch)
    try:
        _persist_plan(
            "brain-feedback-loop",
            [
                {"shot_index": 1, "prompt": "Shot 1: opening.", "duration": 5},
                {"shot_index": 2, "prompt": "Shot 2: failed video.", "duration": 5},
            ],
        )
        project_workspace.write_project_workspace_file(
            "brain-feedback-loop",
            relative_path="memory/decisions.md",
            content="- source: project_brain_continue\n- reason: queued bounded media tasks",
            source="unit",
            reason="feedback audit",
        )
        project_workspace.write_project_workspace_file(
            "brain-feedback-loop",
            relative_path="memory/failures.md",
            content="- source: media_task_writeback\n- error: provider timeout",
            source="unit",
            reason="feedback audit",
        )

        brain = project_brain.build_project_brain(
            "brain-feedback-loop",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "Shot 1: opening.",
                    "status": "video_done",
                    "selected_image": "img-1",
                    "selected_video": "vid-1",
                    "duration": 5,
                },
                {
                    "shot_index": 2,
                    "prompt": "Shot 2: failed video.",
                    "status": "image_done",
                    "selected_image": "img-2",
                    "last_error": "provider timeout",
                    "duration": 5,
                },
            ],
            final_edit_plan={
                "settings": {"bgm_path": "http://audio/bgm.mp3", "burn_subtitles": False, "cover_title": "Feedback"},
                "clips": [{"shot_index": 1, "video_url": "vid-1", "enabled": True, "duration": 5}],
            },
        )

        audit = {item["component"]: item for item in brain["context"]["feedback_loop_audit"]}

        assert audit["workspace_decision_memory"]["coverage"] == "covered"
        assert "has_project_brain_continue=True" in audit["workspace_decision_memory"]["evidence"]
        assert audit["shot_row_status_writeback"]["coverage"] == "covered"
        assert "failed=1" in audit["shot_row_status_writeback"]["evidence"]
        assert audit["media_success_writeback"]["coverage"] == "covered"
        assert audit["failure_writeback"]["coverage"] == "covered"
        assert "has_media_task_writeback=True" in audit["failure_writeback"]["evidence"]
        assert audit["final_edit_writeback"]["coverage"] == "covered"
        assert audit["after_brain_refresh"]["coverage"] == "covered"
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)
