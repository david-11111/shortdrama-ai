import shutil
import uuid
from pathlib import Path

from app.services import project_brain, project_workspace


def test_project_brain_starts_with_story_plan_gap(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        brain = project_brain.build_project_brain("brain-one", name="brain one")

        assert brain["phase"] == "script_understanding"
        assert brain["next_action"] == "generate_story_plan"
        assert any(item["code"] == "story_plan" for item in brain["missing"])
        assert brain["signals"]["workspace_ready"] is True
        assert brain["signals"]["workspace_shot_count"] == 0
        coverage = {item["path"]: item for item in brain["context"]["context_coverage"]}
        assert coverage["PROJECT.md"]["role"] == "project_brief"
        assert coverage["PROJECT.md"]["exists"] is True
        assert coverage["PROJECT.md"]["parsed"] is True
        assert "production_ledger" in coverage["PROJECT.md"]["used_by"]
        assert coverage["shots/episode-01-scene-01.json"]["coverage"] in {"covered", "partial"}
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_summary_does_not_call_warnings_blocking_risks():
    summary = project_brain._build_summary(
        "asset_locking",
        {
            "seedream_budget_level": "normal",
            "operational_pending_video_count": 0,
            "operational_video_done_count": 0,
            "operational_shot_count": 8,
            "ledger_generated_video_seconds": 0,
            "ledger_target_total_seconds": 60,
            "ledger_remaining_seconds": 60,
        },
        [{"code": "cost_risk_ledger", "severity": "warning"}],
        [],
    )

    assert "阻塞风险" not in summary


def test_project_brain_moves_to_keyframes_after_workspace_plan(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-two",
            {
                "reply": "第一场：女主走进金店。",
                "continuity": {
                    "character_continuity": "女主，职业装，神情克制。",
                    "scene_continuity": "现代金店柜台。",
                },
                "shot_rows": [
                    {"shot_index": 1, "prompt": "女主走进金店，柜台灯光明亮。", "duration": 5},
                    {"shot_index": 2, "prompt": "特写黄金手镯放到柜台。", "duration": 4},
                ],
            },
            source="unit",
            reason="brain plan",
        )

        brain = project_brain.build_project_brain("brain-two")

        assert brain["phase"] == "keyframe_generation"
        assert brain["next_action"] == "generate_keyframes"
        assert brain["signals"]["has_director_plan"] is True
        assert brain["signals"]["has_character_lock"] is True
        assert brain["signals"]["workspace_shot_count"] == 2
        assert not brain["risks"]
        read_file = next(item for item in brain["read_files"] if item["path"] == "shots/episode-01-scene-01.json")
        assert read_file["parsed"] is True
        assert read_file["item_count"] == 2
        assert read_file["consumed"] is True
        assert read_file["impact_if_missing"]
        audit = {item["component"]: item for item in brain["context"]["ledger_merge_audit"]}
        assert audit["production_ledger"]["coverage"] == "covered"
        assert "ledger_generated_video_seconds" in audit["production_ledger"]["signals_used"]
        assert audit["character_lock"]["coverage"] == "covered"
        assert "phase" in audit["character_lock"]["consumed_by"]
        assert audit["scene_lock"]["coverage"] == "covered"
        assert "next_action" in audit["scene_lock"]["consumed_by"]
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_does_not_treat_placeholder_locks_as_complete(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-placeholder-lock",
            {
                "reply": "第一场：女主走进金店。",
                "continuity": {
                    "character_continuity": "主角需要先锁定清晰身份、年龄段、服装、发型和正脸参考。",
                    "scene_continuity": "现代金店柜台。",
                },
                "shot_rows": [{"shot_index": 1, "prompt": "女主走进金店。", "duration": 5}],
            },
            source="unit",
            reason="placeholder lock",
        )

        brain = project_brain.build_project_brain("brain-placeholder-lock")

        assert brain["phase"] == "asset_locking"
        assert brain["next_action"] == "lock_assets"
        assert brain["signals"]["has_character_lock"] is False
        assert any(item["code"] == "asset_locks" for item in brain["missing"])
        gates = {item["id"]: item for item in brain["safety_gates"]}
        assert gates["asset_locks_ready"]["passed"] is False
        assert gates["asset_locks_ready"]["blocks_current_action"] is False
        assert "downstream generation" in gates["asset_locks_ready"]["reason"]
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_ignores_marker_only_and_empty_field_content(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.write_project_workspace_file(
            "brain-empty-fields",
            relative_path="story/characters.md",
            content="## Director Lock\n\n### Character Continuity\n- 姓名：\n- 年龄：\n- 身份：\n????",
            mode="replace",
            force=True,
        )
        project_workspace.write_project_workspace_file(
            "brain-empty-fields",
            relative_path="story/episodes.md",
            content="## Director Plan\n\n### Story / Production Draft\n待填写。",
            mode="replace",
            force=True,
        )
        project_workspace.write_project_workspace_file(
            "brain-empty-fields",
            relative_path="scenes/episode-01-scene-01.md",
            content="## Director Scene Plan\n\n### Shot Summary\n- 场景地点：\n- 出场角色：",
            mode="replace",
            force=True,
        )

        brain = project_brain.build_project_brain("brain-empty-fields")

        assert brain["phase"] == "script_understanding"
        assert brain["signals"]["has_director_plan"] is False
        assert brain["signals"]["has_character_lock"] is False
        assert brain["signals"]["has_scene_plan"] is False
        gates = {item["id"]: item for item in brain["context"]["safety_gates"]}
        assert gates["story_plan_ready"]["blocks_current_action"] is False
        assert gates["scene_plan_ready"]["passed"] is False
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_plans_visual_assets_before_keyframes(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-visual-assets",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "店员在金店柜台前报价", "duration": 5}],
            },
            source="unit",
            reason="brain visual assets",
        )

        brain = project_brain.build_project_brain(
            "brain-visual-assets",
            operational_shots=[{"shot_index": 1, "prompt": "店员在金店柜台前报价", "status": "pending"}],
            visual_plan={
                "asset_actions": [
                    {"id": "shot-1-character", "action_type": "generate_reference"},
                    {"id": "shot-1-scene", "action_type": "bind_existing"},
                ],
            },
        )

        assert brain["phase"] == "asset_locking"
        assert brain["next_action"] == "plan_visual_assets"
        assert brain["can_continue"] is True
        assert brain["signals"]["visual_plan_action_count"] == 2
        assert brain["signals"]["visual_reference_generation_count"] == 1
        assert brain["signals"]["visual_bind_existing_count"] == 1
        assert brain["signals"]["seedream_estimated_image_count"] == 2
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_holds_keyframes_when_seedream_budget_is_high(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-seedream-budget",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [
                    {"shot_index": idx, "prompt": f"金店柜台镜头 {idx}", "duration": 5}
                    for idx in range(1, 11)
                ],
            },
            source="unit",
            reason="brain seedream budget",
        )

        operational_shots = [
            {"shot_index": idx, "prompt": f"金店柜台镜头 {idx}", "status": "pending"}
            for idx in range(1, 11)
        ]
        brain = project_brain.build_project_brain(
            "brain-seedream-budget",
            operational_shots=operational_shots,
            visual_plan={
                "asset_actions": [
                    {"id": f"shot-{idx}-character", "action_type": "generate_reference", "kind": "character", "title": "店员角色参考"}
                    for idx in range(1, 6)
                ],
                "seedream_budget": {
                    "action_count": 5,
                    "bind_existing_count": 0,
                    "generate_reference_action_count": 5,
                    "unique_reference_generation_count": 1,
                    "pending_keyframe_count": 10,
                    "estimated_without_reuse": 15,
                    "estimated_seedream_images": 14,
                    "avoided_seedream_images": 1,
                    "reuse_ratio_percent": 20,
                    "budget_level": "over_budget",
                },
            },
        )

        assert brain["phase"] == "asset_locking"
        assert brain["next_action"] == "plan_visual_assets"
        assert brain["signals"]["seedream_budget_level"] == "over_budget"
        assert brain["signals"]["seedream_estimated_image_count"] == 14
        assert any(item["code"] == "visual_budget_review" for item in brain["missing"])
        assert any(item["code"] == "seedream_budget_overrun" for item in brain["risks"])
        gates = {item["id"]: item for item in brain["safety_gates"]}
        assert gates["visual_budget_guard"]["passed"] is False
        assert gates["visual_budget_guard"]["status"] == "warning"
        audit = {item["component"]: item for item in brain["context"]["ledger_merge_audit"]}
        assert audit["asset_reuse"]["coverage"] == "covered"
        assert "next_action" in audit["asset_reuse"]["consumed_by"]
        assert audit["cost_ledger"]["coverage"] == "covered"
        assert "risks" in audit["cost_ledger"]["consumed_by"]
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_blocks_on_preflight_risk(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-three",
            {
                "reply": "第一场：人群争抢。",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [
                    {
                        "shot_index": 1,
                        "prompt": "十几个人围在柜台前争抢黄金。",
                        "duration": 5,
                        "director_preflight": {
                            "risk_level": "blocked",
                            "risks": [{"reason": "人数过多，主体不清。"}],
                        },
                    }
                ],
            },
            source="unit",
            reason="brain blocked",
        )

        brain = project_brain.build_project_brain("brain-three")

        assert brain["phase"] == "preflight_review"
        assert brain["next_action"] == "fix_preflight_risks"
        assert brain["can_continue"] is False
        assert brain["risks"][0]["code"] == "workspace_preflight_blocked"
        gates = {item["id"]: item for item in brain["safety_gates"]}
        assert gates["preflight_clear"]["passed"] is False
        assert gates["preflight_clear"]["status"] == "blocked"
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_waits_while_keyframes_are_generating(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-four",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [
                    {"shot_index": 1, "prompt": "shot one", "duration": 5},
                    {"shot_index": 2, "prompt": "shot two", "duration": 5},
                ],
            },
            source="unit",
            reason="brain generating",
        )

        brain = project_brain.build_project_brain(
            "brain-four",
            operational_shots=[
                {"shot_index": 1, "prompt": "shot one", "status": "image_done", "selected_image": "http://image/1.jpg"},
                {"shot_index": 2, "prompt": "shot two", "status": "generating_image"},
            ],
        )

        assert brain["phase"] == "keyframe_generation"
        assert brain["next_action"] == "wait_for_keyframes"
        assert brain["next_action_label"] == "等待关键帧回写"
        assert brain["can_continue"] is False
        assert brain["signals"]["operational_generating_count"] == 1
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_moves_to_video_after_keyframes(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-five",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "shot one", "duration": 5}],
            },
            source="unit",
            reason="brain image done",
        )

        brain = project_brain.build_project_brain(
            "brain-five",
            operational_shots=[
                {"shot_index": 1, "prompt": "shot one", "status": "image_done", "selected_image": "http://image/1.jpg"},
            ],
        )

        assert brain["phase"] == "video_generation"
        assert brain["next_action"] == "generate_videos"
        assert brain["can_continue"] is True
        assert brain["signals"]["operational_pending_video_count"] == 1
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_builds_production_ledger_for_long_episode(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-ledger",
            {
                "reply": "Director Plan：目标 40 分钟。第一场进入核心场景，第二场承接危机。",
                "continuity": {
                    "character_continuity": "主角西装，助理灰衬衫。",
                    "scene_continuity": "核心控制室。",
                },
                "shot_rows": [
                    {"shot_index": 1, "prompt": "第1集第1场，建立镜头：主角进入核心场景。", "duration": 5},
                    {"shot_index": 2, "prompt": "第1集第1场，关系镜头：助理递交文件。", "duration": 5},
                    {"shot_index": 3, "prompt": "第1集第2场，反应镜头：主角听到危机。", "duration": 5},
                ],
            },
            source="unit",
            reason="brain ledger",
        )

        brain = project_brain.build_project_brain(
            "brain-ledger",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "第1集第1场，建立镜头：主角进入核心场景。",
                    "duration": 5,
                    "status": "video_done",
                    "selected_image": "img-1",
                    "selected_video": "vid-1",
                    "character_refs": ["char-main"],
                    "scene_refs": ["scene-core"],
                    "costume_refs": ["suit-main"],
                },
                {
                    "shot_index": 2,
                    "prompt": "第1集第1场，关系镜头：助理递交文件。",
                    "duration": 5,
                    "status": "video_done",
                    "selected_image": "img-2",
                    "selected_video": "vid-2",
                    "character_refs": ["char-main", "char-assistant"],
                    "scene_refs": ["scene-core"],
                },
                {
                    "shot_index": 3,
                    "prompt": "第1集第2场，反应镜头：主角听到危机。",
                    "duration": 5,
                    "status": "image_done",
                    "selected_image": "img-3",
                    "character_refs": ["char-main"],
                    "scene_refs": ["scene-core"],
                },
            ],
        )

        ledger = brain["context"]["production_ledger"]

        assert ledger["target_total_seconds"] == 2400
        assert ledger["planned_shot_count"] == 3
        assert ledger["generated_video_count"] == 2
        assert ledger["generated_video_seconds"] == 10
        assert ledger["remaining_seconds"] == 2390
        assert ledger["current_scene"]["scene_key"] == "E01S02"
        assert ledger["previous_scene"]["scene_key"] == "E01S01"
        assert ledger["asset_locks"]["reusable_total"] >= 4
        assert brain["signals"]["ledger_current_scene_key"] == "E01S02"
        assert brain["signals"]["ledger_generated_video_seconds"] == 10
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_waits_while_videos_are_generating(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-six",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "shot one", "duration": 5}],
            },
            source="unit",
            reason="brain video generating",
        )

        brain = project_brain.build_project_brain(
            "brain-six",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "shot one",
                    "status": "generating_video",
                    "selected_image": "http://image/1.jpg",
                },
            ],
        )

        assert brain["phase"] == "video_generation"
        assert brain["next_action"] == "wait_for_videos"
        assert brain["next_action_label"] == "等待视频回写"
        assert brain["can_continue"] is False
        assert brain["signals"]["operational_generating_video_count"] == 1
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_allows_retry_for_video_provider_failure(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-seven",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "shot one", "duration": 5}],
            },
            source="unit",
            reason="brain video retry",
        )

        brain = project_brain.build_project_brain(
            "brain-seven",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "shot one",
                    "status": "image_done",
                    "selected_image": "http://image/1.jpg",
                    "last_error": "Service seedance saturated across all configured keys",
                },
            ],
        )

        assert brain["phase"] == "video_generation"
        assert brain["next_action"] == "generate_videos"
        assert brain["can_continue"] is True
        assert brain["risks"][0]["severity"] == "warning"
        assert not any(item["code"] == "risk_resolution" for item in brain["missing"])
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_moves_to_final_edit_after_videos(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-eight",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "shot one", "duration": 5}],
            },
            source="unit",
            reason="brain final edit",
        )

        brain = project_brain.build_project_brain(
            "brain-eight",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "shot one",
                    "status": "video_done",
                    "selected_image": "http://image/1.jpg",
                    "selected_video": "http://video/1.mp4",
                },
            ],
        )

        assert brain["phase"] == "final_edit"
        assert brain["next_action"] == "plan_final_edit"
        assert brain["can_continue"] is True
        assert brain["signals"]["operational_video_done_count"] == 1
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_stops_after_final_edit_plan_exists(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-nine",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "shot one", "duration": 5}],
            },
            source="unit",
            reason="brain final edit saved",
        )

        brain = project_brain.build_project_brain(
            "brain-nine",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "shot one",
                    "status": "video_done",
                    "selected_image": "http://image/1.jpg",
                    "selected_video": "http://video/1.mp4",
                },
            ],
            final_edit_plan={"clips": [{"shot_index": 1, "video_url": "http://video/1.mp4"}]},
        )

        assert brain["phase"] == "final_edit"
        assert brain["next_action"] == "open_final_cut"
        assert brain["can_continue"] is False
        assert brain["signals"]["final_edit_plan_ready"] is True
        assert brain["signals"]["final_edit_clip_count"] == 1
    finally:
        shutil.rmtree(storage, ignore_errors=True)


def test_project_brain_surfaces_preview_and_final_export_status(monkeypatch):
    storage = Path("storage") / "test-project-brain" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "brain-export-status",
            {
                "reply": "Director Plan",
                "continuity": {"character_continuity": "Character Continuity"},
                "shot_rows": [{"shot_index": 1, "prompt": "shot one", "duration": 5}],
            },
            source="unit",
            reason="brain export status",
        )

        brain = project_brain.build_project_brain(
            "brain-export-status",
            operational_shots=[
                {
                    "shot_index": 1,
                    "prompt": "shot one",
                    "status": "video_done",
                    "selected_image": "http://image/1.jpg",
                    "selected_video": "http://video/1.mp4",
                },
            ],
            final_edit_plan={
                "settings": {
                    "preview_export": {"task_id": "preview-task", "url": "http://video/preview.mp4"},
                    "final_export": {"task_id": "final-task", "url": "http://video/final.mp4"},
                    "final_delivery_report": {"passed": True},
                },
                "clips": [{"shot_index": 1, "video_url": "http://video/1.mp4", "subtitle": "shot one"}],
            },
        )

        assert brain["signals"]["preview_export_ready"] is True
        assert brain["signals"]["preview_export_task_id"] == "preview-task"
        assert brain["signals"]["final_export_ready"] is True
        assert brain["signals"]["final_export_task_id"] == "final-task"
        assert brain["signals"]["final_delivery_passed"] is True
        audit = {item["component"]: item for item in brain["context"]["final_delivery_audit"]}
        assert audit["preview_export_done"]["coverage"] == "covered"
        assert audit["final_export_done"]["coverage"] == "covered"
    finally:
        shutil.rmtree(storage, ignore_errors=True)
