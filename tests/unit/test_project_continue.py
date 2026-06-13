import shutil
import uuid
from pathlib import Path

import pytest

from app.routes import workbench
from app.services.director_preflight import analyze_shot_risk
from app.services import project_continue, project_workspace
from app.routes.workbench import _dispatch_action_after_planning, _estimate_continue_credits, _keyframe_generation_targets, _split_final_edit_rows


def test_continue_project_from_brain_generates_planning_files(monkeypatch):
    storage = Path("storage") / "test-project-continue" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        result = project_continue.continue_project_from_brain(
            "continue-one",
            instruction="精品短剧：女主到金店回购黄金，引发信任冲突。",
            name="黄金回购",
        )

        assert result["applied"] is True
        assert result["action"] == "generate_story_plan"
        assert len(result["writes"]) == 4
        assert len(result["shot_rows"]) == 8
        assert result["before"]["next_action"] == "generate_story_plan"
        assert result["after"]["next_action"] in {"lock_assets", "generate_keyframes"}
        assert result["after"]["signals"]["workspace_shot_count"] == 8

        decisions = (storage / "continue-one" / "memory" / "decisions.md").read_text(encoding="utf-8")
        shots = (storage / "continue-one" / "shots" / "episode-01-scene-01.json").read_text(encoding="utf-8")
        assert "continue action: generate_story_plan" in decisions
        assert "黄金回购" in shots
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_continue_project_from_brain_scales_to_requested_duration(monkeypatch):
    storage = Path("storage") / "test-project-continue" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        result = project_continue.continue_project_from_brain(
            "continue-long",
            instruction="精品短剧：主角逆袭，目标成片 40 分钟，电视剧质感。",
            name="主角",
        )

        assert result["applied"] is True
        assert result["shot_rows"][0]["production_batch"]["target_total_shots"] == 480
        assert result["shot_rows"][0]["production_batch"]["target_scene_count"] == 40
        assert len(result["shot_rows"]) == 20
        assert result["shot_rows"][-1]["shot_index"] == 20
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_continue_project_from_brain_preserves_actor_drama_lead_requirement(monkeypatch):
    storage = Path("storage") / "test-project-continue" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        instruction = "我想复拍最近很火的张嘉益演的电视剧主角的前一分钟戏，请先生成剧本和分镜。"
        result = project_continue.continue_project_from_brain(
            "continue-actor-drama",
            instruction=instruction,
            name="电视剧主角前一分钟",
        )

        assert result["applied"] is True
        understanding = result["story_understanding"]["understanding_card"]
        assert understanding["work"] == "主角"
        assert understanding["role"] == "胡三元"
        assert "鼓槌" in understanding["prop_anchors"]
        character_lock = result["continuity"]["character_continuity"]
        assert "张嘉益" in character_lock
        assert "胡三元" in character_lock
        assert "县剧团司鼓" in character_lock
        assert "前一分钟" in result["reply"]
        assert all("张嘉益" in row["prompt"] for row in result["shot_rows"])
        assert all("胡三元" in row["prompt"] for row in result["shot_rows"])
        assert any("秦腔" in row["prompt"] for row in result["shot_rows"])
        assert any("鼓槌" in row["prompt"] for row in result["shot_rows"])

        shots = (storage / "continue-actor-drama" / "shots" / "episode-01-scene-01.json").read_text(encoding="utf-8")
        characters = (storage / "continue-actor-drama" / "story" / "characters.md").read_text(encoding="utf-8")
        assert "张嘉益" in shots
        assert "胡三元" in shots
        assert "秦腔" in shots
        assert "张嘉益" in characters
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_continue_project_from_brain_generates_concrete_project_process_shots(monkeypatch):
    storage = Path("storage") / "test-project-continue" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        instruction = "AI时代下，一个普通人坚持做短剧工具一个月，从崩溃到重新把链路跑通，做一个不超过10秒、有创意、有质感的视频测试。"
        result = project_continue.continue_project_from_brain(
            "continue-real-process",
            instruction=instruction,
            name="短剧工具链路测试",
        )

        assert result["applied"] is True
        assert result["shot_rows"]
        blocked = [
            (row["shot_index"], analyze_shot_risk(row, project_goal=instruction))
            for row in result["shot_rows"]
            if analyze_shot_risk(row, project_goal=instruction)["risk_level"] == "blocked"
        ]
        assert blocked == []
        assert all("开发者" in row["prompt"] or "测试日志" in row["prompt"] or "电脑屏幕" in row["prompt"] for row in result["shot_rows"])
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_continue_project_from_brain_refuses_unsupported_action(monkeypatch):
    storage = Path("storage") / "test-project-continue" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        project_workspace.persist_director_result_to_workspace(
            "continue-two",
            {
                "reply": "已有规划。",
                "continuity": {"character_continuity": "女主，职业装。"},
                "shot_rows": [{"shot_index": 1, "prompt": "女主走进金店。", "duration": 5}],
            },
        )
        result = project_continue.continue_project_from_brain("continue-two")

        assert result["applied"] is False
        assert result["action"] == "generate_keyframes"
        assert not result["writes"]
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)


def test_planning_lock_assets_hands_off_to_keyframe_dispatch():
    after_brain = {
        "can_continue": False,
        "signals": {"operational_pending_keyframe_count": 8},
    }

    assert _dispatch_action_after_planning(after_brain, "lock_assets") == "generate_keyframes"


def test_production_action_does_not_continue_planning_loop():
    after_brain = {
        "can_continue": True,
        "next_action": "generate_keyframes",
    }

    assert workbench._should_continue_planning_chain(
        run_mode="step",
        result={"after": after_brain},
        chain_step=1,
        max_chain_steps=3,
    ) is False


def test_autopilot_continues_internal_preflight_repair_before_media_dispatch():
    after_brain = {
        "can_continue": False,
        "next_action": "fix_preflight_risks",
    }

    assert workbench._should_continue_planning_chain(
        run_mode="autopilot",
        result={"after": after_brain},
        chain_step=1,
        max_chain_steps=3,
    ) is True


def test_compatibility_packet_for_generate_videos_uses_c_lane_and_cost_hint():
    packet = workbench._build_compatibility_decision_packet(
        project_id="project-1",
        run_id="11111111-1111-1111-1111-111111111111",
        action="generate_videos",
        before={"signals": {"operational_pending_video_count": 7, "workspace_shot_count": 8}},
        image_unit_price=10,
        video_unit_price=80,
        provider="seedance",
    )

    assert packet.selected_lane == "c_lane_production"
    assert packet.budget["estimated_max_credits"] == 320
    assert packet.mission["provider"] == "seedance"
    assert packet.mission["write_scope"] == ["tasks", "shot_rows", "agent_events", "agent_runs"]


@pytest.mark.asyncio
async def test_dispatch_production_action_routes_through_gateway(monkeypatch):
    observed = {}

    async def fake_load(_db, *, run_id, user_id):
        return None

    async def fake_dispatch(_db, *, packet, context, handlers):
        observed["packet"] = packet
        observed["context"] = context
        observed["handler_names"] = sorted(handlers.keys())
        return {"ok": True}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="generate_keyframes",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_keyframe_count": 2, "workspace_shot_count": 2}},
        name="project-1",
        run_id="11111111-1111-1111-1111-111111111111",
        run_mode="step",
        result={"before": {}},
        image_unit_price=12,
        video_unit_price=80,
    )

    assert observed["packet"].action == "generate_keyframes"
    assert observed["packet"].selected_lane == "c_lane_production"
    assert observed["context"].run_id == "11111111-1111-1111-1111-111111111111"
    assert "generate_keyframes" in observed["handler_names"]
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_dispatch_production_action_passes_video_runtime_capabilities(monkeypatch):
    observed = {}

    async def fake_load(_db, *, run_id, user_id):
        return None

    async def fake_dispatch(_db, *, packet, context, handlers):
        observed["packet"] = packet
        observed["context"] = context
        observed["handler_names"] = sorted(handlers.keys())
        return {"ok": True}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="generate_videos",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_video_count": 2, "workspace_shot_count": 2}},
        name="project-1",
        run_id="11111111-1111-1111-1111-111111111111",
        run_mode="step",
        result={"before": {}},
        image_unit_price=12,
        video_unit_price=80,
        provider="seedance",
    )

    assert observed["packet"].action == "generate_videos"
    assert "generate_videos" in observed["handler_names"]
    assert "video_generation" in observed["context"].runtime_features
    assert "provider_status_observation" in observed["context"].runtime_features
    assert "selected_video_writeback" in observed["context"].runtime_features
    assert "seedance_image_to_video" in observed["context"].provider_capabilities
    assert observed["context"].capability_versions["generate_videos"] == "2026-05-27.v1"
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_dispatch_production_action_uses_canonical_decision_tick(monkeypatch):
    observed = {}

    async def fake_load(db, *, run_id, user_id):
        observed["loaded_run_id"] = run_id
        return object()

    def fake_evaluate(facts):
        return workbench.DecisionTickResult(
            packet_version="main_run_chain_phase1",
            status="execute",
            action="generate_keyframes",
            stage_id="generate_keyframes",
            selected_lane="c_lane_production",
            dispatchable=True,
            allowed=True,
            reason="canonical",
            missing=[],
            fallback_action="",
            active_task_count=0,
            failed_task_count=0,
            allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
            evidence={},
            evidence_refs=[],
            candidate_actions=[],
            success_criteria=[],
            budget={},
            risk={},
            failure_policy={},
            mission={
                "mission_id": "run-1:generate_keyframes",
                "lane": "c_lane_production",
                "action": "generate_keyframes",
                "write_scope": ["tasks"],
                "idempotency_key": "run-1:generate_keyframes",
            },
        )

    async def fake_dispatch(db, *, packet, context, handlers):
        observed["packet_reason"] = packet.reason
        return {"run_id": context.run_id, "decision_packet": packet.as_dict()}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "evaluate_decision_tick", fake_evaluate)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="generate_keyframes",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_keyframe_count": 1}},
        name="project-1",
        run_id="run-1",
        run_mode="autopilot",
        result={},
        image_unit_price=1,
        video_unit_price=1,
    )

    assert observed["loaded_run_id"] == "run-1"
    assert observed["packet_reason"] == "canonical"
    assert result["decision_packet"]["reason"] == "canonical"


def test_final_edit_rows_allow_partial_cut_from_existing_videos():
    rows = [
        {"shot_index": 1, "selected_video": "video-1.mp4"},
        {"shot_index": 2, "selected_video": "video-2.mp4"},
        {"shot_index": 3, "selected_video": "video-3.mp4"},
        {"shot_index": 4, "selected_video": ""},
        {"shot_index": 5, "selected_video": None},
        {"shot_index": 6},
        {"shot_index": 7, "selected_video": ""},
        {"shot_index": 8, "selected_video": ""},
    ]

    usable, missing = _split_final_edit_rows(rows)

    assert [row["shot_index"] for row in usable] == [1, 2, 3]
    assert missing == [4, 5, 6, 7, 8]


def test_generate_videos_credit_estimate_batches_multiple_ready_shots():
    rows = [
        {
            "shot_index": idx,
            "prompt": f"shot {idx}",
            "selected_image": f"https://cdn.test/{idx}.png",
            "selected_video": "",
            "status": "image_done",
        }
        for idx in range(1, 8)
    ]

    assert _estimate_continue_credits("generate_videos", rows, image_unit=10, video_unit=80) == 320


def test_keyframe_repair_targets_review_failed_selected_images():
    rows = [
        {
            "shot_index": 1,
            "prompt": "shot 1",
            "selected_image": "https://cdn.test/old-1.png",
            "status": "image_done",
            "image_candidates": [
                {
                    "url": "https://cdn.test/old-1.png",
                    "review": {"status": "needs_review"},
                }
            ],
        },
        {
            "shot_index": 2,
            "prompt": "shot 2",
            "selected_image": "https://cdn.test/old-2.png",
            "status": "image_done",
            "image_candidates": [
                {
                    "url": "https://cdn.test/old-2.png",
                    "review": {"status": "passed"},
                }
            ],
        },
    ]
    semantic_control = {
        "human_routing": {
            "pending_action": {
                "recommendation": "regenerate_review_failed_keyframes",
                "shot_indices": [1, 2],
            }
        }
    }

    targets = _keyframe_generation_targets(rows, semantic_control=semantic_control)

    assert [row["shot_index"] for row in targets] == [1]
    assert targets[0]["selected_image"] == "https://cdn.test/old-1.png"
    assert targets[0]["regeneration"]["previous_selected_image"] == "https://cdn.test/old-1.png"


def test_keyframe_generation_targets_expired_selected_images():
    rows = [
        {
            "shot_index": 1,
            "prompt": "shot 1",
            "selected_image": (
                "https://cdn.test/shot-1.png?"
                "X-Tos-Date=20260521T010203Z&X-Tos-Expires=86400&X-Tos-Signature=x"
            ),
            "status": "image_done",
            "image_candidates": [],
        },
        {
            "shot_index": 2,
            "prompt": "shot 2",
            "selected_image": (
                "https://cdn.test/shot-2.png?"
                "X-Tos-Date=20260525T010203Z&X-Tos-Expires=864000&X-Tos-Signature=x"
            ),
            "status": "image_done",
            "image_candidates": [],
        },
    ]

    targets = _keyframe_generation_targets(rows)

    assert [row["shot_index"] for row in targets] == [1]
    assert targets[0]["regeneration"]["reason"] == "selected_image_url_expired"
    assert targets[0]["regeneration"]["previous_selected_image"] == rows[0]["selected_image"]


def test_showrunner_generation_preflight_blocks_bad_creative_prompt_before_dispatch():
    before = {
        "context": {
            "project": "我做这个工具快一个月了，从开始立项，到现在，经历了很多，我希望你能把这个过程做成短剧"
        }
    }
    decision = workbench._evaluate_showrunner_generation_preflight(
        before=before,
        name="real-provider-e31ba157",
        targets=[
            {
                "shot_index": 1,
                "prompt": "第1集第1场，建立镜头：real-provider-e31ba157，围绕电视剧主角的开场段落戏。",
                "status": "ready",
            }
        ],
        action="generate_keyframes",
        run_id="run-1",
    )

    assert decision.status == "blocked"
    assert decision.action == "rewrite_shots_and_prompts"
    assert decision.selected_lane == "b_lane_agent_runs"
    assert decision.root_cause_layer in {"shot", "prompt"}


def test_showrunner_generation_preflight_allows_concrete_real_project_prompt():
    before = {
        "context": {
            "project": "我做这个工具快一个月了，从开始立项，到现在，经历了很多，我希望你能把这个过程做成短剧"
        }
    }
    decision = workbench._evaluate_showrunner_generation_preflight(
        before=before,
        name="AI短剧工具开发过程",
        targets=[
            {
                "shot_index": 1,
                "prompt": "第1镜：深夜，开发者盯着第四次失败的测试日志，电脑屏幕反光压在脸上。职责是建立真实困境和前三秒钩子。",
                "status": "ready",
            }
        ],
        action="generate_keyframes",
        run_id="run-1",
    )

    assert decision.status == "execute"
    assert decision.action == "continue"
