import pytest
from fastapi import HTTPException

from app.routes import agent_runs, workbench
from app.routes.agent_runs import _apply_control_intent_routing, _apply_planner_routing, _build_continue_body, _build_decision_context, _build_human_continue_body, _followup_action_from_evidence, _normalize_input_assets, _stream_history_order
from app.services.llm_planner import PlannerDecision


@pytest.mark.asyncio
async def test_story_plan_writeback_refreshes_run_ledger_and_brain_steps(monkeypatch):
    executed: list[tuple[str, dict]] = []
    emitted: dict[str, object] = {}

    class FakeDb:
        async def execute(self, statement, params=None):
            executed.append((str(statement), params or {}))

    async def fake_emit_brain_snapshot_steps(**kwargs):
        emitted.update(kwargs)

    monkeypatch.setattr(workbench, "emit_brain_snapshot_steps", fake_emit_brain_snapshot_steps)

    after_brain = {
        "phase": "visual_assets",
        "context": {
            "production_ledger": {
                "shot_count": 8,
                "planned_duration_seconds": 60,
                "scenes": [{"scene_key": "ep1-sc1"}],
            }
        },
    }

    await workbench._refresh_run_brain_snapshot_after_writeback(
        FakeDb(),
        run_id="11111111-1111-1111-1111-111111111111",
        project_id="project-1",
        user_id=1,
        brain=after_brain,
        mode="step",
    )

    assert executed
    sql, params = executed[-1]
    assert "UPDATE agent_runs" in sql
    assert "production_ledger" in sql
    assert '"shot_count": 8' in params["production_ledger"]
    assert emitted["run_id"] == "11111111-1111-1111-1111-111111111111"
    assert emitted["project_id"] == "project-1"
    assert emitted["user_id"] == 1
    assert emitted["brain"] is after_brain
    assert emitted["mode"] == "step"


def test_agent_run_continue_body_infers_action_from_goal():
    body = _build_continue_body(
        payload={},
        params={},
        mode="step",
        goal="继续生成关键帧",
    )

    assert body["mode"] == "step"
    assert body["goal"] == "继续生成关键帧"
    assert body["instruction"] == "继续生成关键帧"
    assert body["action"] == "generate_keyframes"
    assert body["intent"]["action"] == "generate_keyframes"


def test_agent_run_continue_body_preserves_explicit_action_priority():
    body = _build_continue_body(
        payload={"continue_action": "generate_videos", "instruction": "先做关键帧"},
        params={"continue_action": "generate_keyframes"},
        mode="autopilot",
        goal="继续生成关键帧",
    )

    assert body["mode"] == "autopilot"
    assert body["instruction"] == "先做关键帧"
    assert body["action"] == "generate_videos"
    assert "intent" not in body


def test_agent_run_continue_body_carries_credit_limit_for_audit():
    body = _build_continue_body(
        payload={"allowed_max_credits": 120},
        params={"allowed_max_credits": 60},
        mode="preview",
        goal="只预览下一步",
    )

    assert body["mode"] == "preview"
    assert body["allowed_max_credits"] == 120


def test_normalize_input_assets_keeps_image_and_video_refs():
    assets = _normalize_input_assets(
        [
            {"asset_id": "img-1", "asset_type": "image", "file_url": "/assets/p/gold.png", "role": "golden_reference"},
            {"id": "vid-1", "type": "video", "url": "/assets/p/source.mp4", "role": "source_video"},
            {"asset_id": "", "type": "image", "url": ""},
        ]
    )

    assert assets == [
        {
            "asset_id": "img-1",
            "asset_type": "image",
            "file_url": "/assets/p/gold.png",
            "role": "golden_reference",
        },
        {
            "asset_id": "vid-1",
            "asset_type": "video",
            "file_url": "/assets/p/source.mp4",
            "role": "source_video",
        },
    ]


def test_agent_run_continue_body_preserves_input_assets():
    body = _build_continue_body(
        payload={},
        params={
            "input_assets": [
                {"asset_id": "img-1", "asset_type": "image", "file_url": "/assets/p/gold.png", "role": "golden_reference"}
            ]
        },
        mode="autopilot",
        goal="用这张图生成产品视频",
    )

    assert body["input_assets"][0]["asset_id"] == "img-1"
    assert body["input_assets"][0]["role"] == "golden_reference"


def test_human_continue_body_routes_script_feedback_to_story_plan():
    body, routing = _build_human_continue_body(
        {"instruction": "剧本不够好，再修饰一下产品高级感"},
        source_run_id="run-1",
    )

    assert routing["resolved_action"] == "generate_story_plan"
    assert routing["routing_source"] == "natural_language_rule"
    assert body["action"] == "generate_story_plan"
    assert body["continue_action"] == "generate_story_plan"
    assert body["human_intervention"] is True
    assert body["_chain_run_id"] == "run-1"


def test_human_continue_body_routes_reference_feedback_to_visual_assets():
    body, routing = _build_human_continue_body(
        {"instruction": "参考图不行，重新走 seedream 做电影感产品图"},
        source_run_id="run-1",
    )

    assert routing["resolved_action"] == "plan_visual_assets"
    assert body["action"] == "plan_visual_assets"


def test_human_continue_body_manual_selector_overrides_text_intent():
    body, routing = _build_human_continue_body(
        {"instruction": "参考图不行，但这次我明确要先改剧本", "continue_action": "generate_story_plan"},
        source_run_id="run-1",
    )

    assert routing["resolved_action"] == "generate_story_plan"
    assert routing["routing_source"] == "manual_selector"
    assert body["action"] == "generate_story_plan"
    assert routing["intent"] == {}


def test_control_intent_routing_does_not_treat_script_context_as_story_regen():
    continue_body, routing = _build_human_continue_body(
        {"instruction": "根据剧本情况自行剪辑，配音，配字幕，配音乐"},
        source_run_id="run-1",
    )

    body, routed = _apply_control_intent_routing(continue_body, routing)

    assert routed["resolved_action"] == "plan_final_edit"
    assert routed["intent_type"] == "production_action"
    assert body["action"] == "plan_final_edit"
    assert body["continue_action"] == "plan_final_edit"


def test_control_intent_routing_preserves_deepseek_final_edit_decision():
    continue_body = {
        "instruction": "根据剧本情况自行剪辑，配音，配字幕，配音乐",
        "action": "plan_final_edit",
        "continue_action": "plan_final_edit",
    }
    routing = {
        "instruction": "根据剧本情况自行剪辑，配音，配字幕，配音乐",
        "resolved_action": "plan_final_edit",
        "routing_source": "deepseek",
        "intent_type": "production_action",
        "planner": {
            "action": "plan_final_edit",
            "confidence": 0.91,
            "dispatch_ready": True,
        },
    }

    body, routed = _apply_control_intent_routing(continue_body, routing)

    assert body is continue_body
    assert routed is routing
    assert routed["resolved_action"] == "plan_final_edit"
    assert routed["routing_source"] == "deepseek"


def test_final_edit_status_diagnostic_does_not_auto_dispatch_keyframes():
    action = _followup_action_from_evidence(
        composer=None,
        diagnostics={"outputs": {"tool_name": "diagnose_outputs", "recommended_action": "repair_missing_images"}},
        routing={
            "instruction": "我感觉到没在剪辑呢？这么久了",
            "resolved_action": "status_query",
            "intent_type": "ui_diagnostic",
            "control_tool": {"tool_name": "diagnose_outputs"},
        },
    )

    assert action == ""


def test_inspect_only_ceiling_blocks_any_diagnostic_followup_dispatch():
    action = _followup_action_from_evidence(
        composer={"recommended_action": "repair_missing_videos"},
        diagnostics={"outputs": {"tool_name": "diagnose_outputs", "recommended_action": "repair_missing_videos"}},
        routing={
            "instruction": "视频生成到哪一步了？",
            "resolved_action": "status_query",
            "intent_type": "ui_diagnostic",
            "action_ceiling": "inspect_only",
        },
    )

    assert action == ""


def test_diagnostic_recommendation_becomes_pending_only_in_same_domain():
    pending = agent_runs._pending_action_from_evidence(
        composer={"recommended_action": "repair_missing_videos"},
        diagnostics={"outputs": {"tool_name": "diagnose_outputs", "recommended_action": "repair_missing_videos"}},
        routing={
            "instruction": "视频生成到哪一步了？",
            "resolved_action": "status_query",
            "intent_type": "ui_diagnostic",
            "action_ceiling": "inspect_only",
            "target_domain": "video",
        },
        instruction="视频生成到哪一步了？",
    )

    assert pending is not None
    assert pending["status"] == "awaiting_confirmation"
    assert pending["action"] == "generate_videos"
    assert pending["domain"] == "video"


def test_diagnostic_recommendation_does_not_cross_target_domain():
    pending = agent_runs._pending_action_from_evidence(
        composer={"recommended_action": "repair_missing_images"},
        diagnostics={"outputs": {"tool_name": "diagnose_outputs", "recommended_action": "repair_missing_images"}},
        routing={
            "instruction": "剪辑怎么还没好？",
            "resolved_action": "status_query",
            "intent_type": "ui_diagnostic",
            "action_ceiling": "inspect_only",
            "target_domain": "final_edit",
        },
        instruction="剪辑怎么还没好？",
    )

    assert pending is None


def test_final_edit_diagnostic_can_pending_missing_video_dependency():
    pending = agent_runs._pending_action_from_evidence(
        composer={"recommended_action": "repair_missing_videos"},
        diagnostics={"outputs": {"tool_name": "diagnose_outputs", "recommended_action": "repair_missing_videos"}},
        routing={
            "instruction": "剪辑怎么还没好？",
            "resolved_action": "status_query",
            "intent_type": "ui_diagnostic",
            "action_ceiling": "inspect_only",
            "target_domain": "final_edit",
        },
        instruction="剪辑怎么还没好？",
    )

    assert pending is not None
    assert pending["action"] == "generate_videos"
    assert pending["domain"] == "video"
    assert pending["target_domain"] == "final_edit"


def test_pending_action_confirmation_cannot_be_overridden_by_planner_or_control_routing():
    body, routing = _build_human_continue_body(
        {"instruction": "好的，执行吧"},
        source_run_id="run-1",
    )
    body, routing = agent_runs._apply_pending_action_confirmation(
        body,
        routing,
        {"action": "generate_videos", "domain": "video", "recommendation": "repair_missing_videos"},
    )

    assert routing["routing_source"] == "pending_action_confirm"
    assert routing["action_ceiling"] == "execute_allowed"
    assert routing["resolved_action"] == "generate_videos"
    assert _apply_control_intent_routing(body, routing) == (body, routing)


def test_build_keyframe_review_repair_proposal_from_blocked_shots():
    proposal = agent_runs._build_keyframe_review_repair_proposal(
        [
            {
                "shot_index": 1,
                "selected_image": "https://cdn.test/shot-1.png",
                "image_candidates": [
                    {
                        "url": "https://cdn.test/shot-1.png",
                        "review": {
                            "status": "needs_review",
                            "notes": ["missing reference assets: scene, character"],
                        },
                    }
                ],
            },
            {
                "shot_index": 2,
                "selected_image": "https://cdn.test/shot-2.png",
                "image_candidates": [
                    {
                        "url": "https://cdn.test/shot-2.png",
                        "review": {
                            "status": "needs_review",
                            "missing_reference_assets": ["character"],
                        },
                    }
                ],
            },
        ]
    )

    assert proposal["action"] == "generate_videos"
    assert proposal["recommendation"] == "approve_review_pending_keyframes"
    assert proposal["shot_indices"] == [1, 2]
    assert proposal["missing_reference_assets_by_shot"] == {1: ["scene", "character"], 2: ["character"]}
    assert proposal["requires_confirmation"] is True
    assert "第1、2镜" in proposal["default_instruction"]
    assert "approved" in proposal["default_instruction"]


def test_build_keyframe_review_repair_proposal_regenerates_failed_shots():
    proposal = agent_runs._build_keyframe_review_repair_proposal(
        [
            {
                "shot_index": 1,
                "selected_image": "https://cdn.test/shot-1.png",
                "image_candidates": [
                    {
                        "url": "https://cdn.test/shot-1.png",
                        "review": {
                            "status": "regenerate",
                            "missing_reference_assets": ["character"],
                        },
                    }
                ],
            }
        ]
    )

    assert proposal["action"] == "generate_keyframes"
    assert proposal["recommendation"] == "regenerate_review_failed_keyframes"
    assert proposal["shot_indices"] == [1]


def test_decision_context_compresses_pending_action_and_blockers():
    context = _build_decision_context(
        current_goal="复拍电视剧主角最初1分钟",
        routing={"routing_source": "control_tool", "resolved_action": "status_query", "target_domain": "final_edit"},
        pending_action={"action": "generate_videos", "recommendation": "repair_missing_videos", "domain": "video", "routing": {"debug": "hidden"}},
        answer="当前缺少视频。如需继续，请回复“好，执行吧”，我会按当前证据执行视频生成。",
        state_machine={"blocked": True, "missing": ["selected_video"], "reason": "At least one selected video is required before audio/final cut.", "next_action": "generate_videos"},
    )

    assert context["current_goal"] == "复拍电视剧主角最初1分钟"
    assert context["awaiting_user"] == "confirm"
    assert context["pending_action"]["action"] == "generate_videos"
    assert "routing" not in context["pending_action"]
    assert context["blocked_by"] == ["selected_video"]
    assert context["next_action"] == "generate_videos"
    assert context["routing_source"] == "control_tool"
    assert "好，执行吧" in context["last_recommendation"]


def test_human_continue_body_rejects_unknown_action():
    with pytest.raises(HTTPException) as exc:
        _build_human_continue_body(
            {"instruction": "随便做一下", "continue_action": "unknown_action"},
            source_run_id="run-1",
        )

    assert exc.value.status_code == 400
    assert "allowed_actions" in exc.value.detail


def test_human_continue_body_routes_status_question_to_status_query():
    body, routing = _build_human_continue_body(
        {"instruction": "视频谁在管，到哪一步了"},
        source_run_id="run-1",
    )

    assert routing["resolved_action"] == "status_query"
    assert routing["routing_source"] == "status_query_rule"
    assert body["action"] == "status_query"


def test_video_duration_maps_to_billing_operation():
    assert agent_runs._bounded_video_duration(None, default=15) == 15
    assert agent_runs._bounded_video_duration(5, default=5) == 5
    assert agent_runs._bounded_video_duration(7, default=5) == 8
    assert agent_runs._bounded_video_duration(10, default=5) == 10
    assert agent_runs._bounded_video_duration(11, default=5) == 15
    assert agent_runs._bounded_video_duration(15, default=5) == 15
    assert agent_runs._video_operation_for_duration(5) == "video_gen_5s"
    assert agent_runs._video_operation_for_duration(8) == "video_gen_8s"
    assert agent_runs._video_operation_for_duration(10) == "video_gen_10s"
    assert agent_runs._video_operation_for_duration(15) == "video_gen_15s"


@pytest.mark.asyncio
async def test_generate_video_from_pool_rejects_unverified_multi_image_mode(monkeypatch):
    async def fake_ensure_run_owner(_db, *, run_id, user_id):
        assert run_id == "run-1"
        assert user_id == 7
        return "project-1"

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", fake_ensure_run_owner)

    with pytest.raises(HTTPException) as exc:
        await agent_runs.generate_video_from_pool(
            "run-1",
            {"shot_index": 1, "mode": "morph_sequence"},
            db=object(),
            current_user={"id": 7},
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["supported_modes"] == ["best_single"]


@pytest.mark.asyncio
async def test_planner_routing_can_override_rule_routing(monkeypatch):
    async def fake_deepseek_planner(_instruction, *, project_context):
        assert project_context["source_run_id"] == "run-1"
        assert project_context["rule_routing"]["source_run_id"] == "run-1"
        return PlannerDecision(
            action="plan_visual_assets",
            confidence=0.9,
            reason="Reference image feedback should route to visual assets",
            target={},
            source="deepseek",
        )

    monkeypatch.setattr(agent_runs, "plan_human_instruction", fake_deepseek_planner)
    body, routing = _build_human_continue_body(
        {"instruction": "这个不行，重做一下"},
        source_run_id="run-1",
    )

    body, routing = await _apply_planner_routing(
        {"instruction": "这个不行，重做一下"},
        body,
        routing,
        source_run_id="run-1",
    )

    assert routing["resolved_action"] == "plan_visual_assets"
    assert routing["routing_source"] == "deepseek"
    assert body["action"] == "plan_visual_assets"
    assert body["human_routing"]["planner"]["action"] == "plan_visual_assets"


@pytest.mark.asyncio
async def test_auto_action_hint_still_goes_through_planner(monkeypatch):
    async def fake_deepseek_planner(_instruction, *, project_context):
        assert project_context["source_run_id"] == "run-1"
        assert project_context["action_hint"] == "plan_visual_assets"
        return PlannerDecision(
            action="status_query",
            confidence=0.88,
            reason="User is asking whether outputs are visible, not requesting a new visual asset job",
            target={"surface": "output_board"},
            source="deepseek",
        )

    monkeypatch.setattr(agent_runs, "plan_human_instruction", fake_deepseek_planner)
    body, routing = _build_human_continue_body(
        {"instruction": "有几张参考图没显示你看到了吗", "action_hint": "plan_visual_assets"},
        source_run_id="run-1",
    )

    body, routing = await _apply_planner_routing(
        {"instruction": "有几张参考图没显示你看到了吗", "action_hint": "plan_visual_assets"},
        body,
        routing,
        source_run_id="run-1",
    )

    assert routing["resolved_action"] == "status_query"
    assert routing["routing_source"] == "deepseek"
    assert body["action"] == "status_query"
    assert "continue_action" not in body
    assert body["human_routing"]["planner"]["target"] == {"surface": "output_board"}


@pytest.mark.asyncio
async def test_visibility_diagnostic_stays_in_deepseek_conversation_when_not_dispatch_ready(monkeypatch):
    async def fake_deepseek_planner(_instruction, *, project_context):
        assert project_context["action_hint"] == "plan_visual_assets"
        return PlannerDecision(
            action="status_query",
            confidence=0.9,
            reason="User is asking why output images are not visible; DeepSeek should diagnose before dispatch.",
            target={"surface": "output_board"},
            source="deepseek",
            intent_type="ui_diagnostic",
            reply="我先按成果区显示问题排查，不会重新生成。需要看这些图片 URL 是否过期、403 或加载失败。",
            dispatch_ready=False,
            missing_info=["具体是哪几张图或对应镜头"],
            extracted={"asset_type": "reference_image"},
        )

    monkeypatch.setattr(agent_runs, "plan_human_instruction", fake_deepseek_planner)
    body, routing = _build_human_continue_body(
        {"instruction": "有几张参考图没显示你看到了吗", "action_hint": "plan_visual_assets"},
        source_run_id="run-1",
    )

    body, routing = await _apply_planner_routing(
        {"instruction": "有几张参考图没显示你看到了吗", "action_hint": "plan_visual_assets"},
        body,
        routing,
        source_run_id="run-1",
    )

    assert routing["resolved_action"] == ""
    assert routing["routing_source"] == "deepseek"
    assert routing["planner"]["intent_type"] == "ui_diagnostic"
    assert routing["planner"]["dispatch_ready"] is False
    assert "成果区显示问题" in routing["planner"]["reply"]
    assert "action" not in body
    assert "continue_action" not in body


def test_stream_history_order_replays_same_transaction_by_agent_phase():
    rows = [
        {"id": "cost", "created_at": "2026-05-20T08:00:00+00:00", "phase": "cost_guard", "progress": 50},
        {"id": "created", "created_at": "2026-05-20T08:00:00+00:00", "phase": "created", "progress": 1},
        {"id": "read", "created_at": "2026-05-20T08:00:00+00:00", "phase": "read_context", "progress": 10},
        {"id": "queued", "created_at": "2026-05-20T08:00:01+00:00", "phase": "queued", "progress": 55},
    ]

    assert [row["id"] for row in _stream_history_order(rows)] == ["created", "read", "cost", "queued"]


def test_mark_selected_keyframe_candidate_review_approved_updates_matching_candidate():
    candidates = [
        {
            "url": "https://cdn.test/old.png",
            "review": {"status": "needs_review"},
            "review_status": "needs_review",
        },
        {
            "url": "https://cdn.test/selected.png",
            "review": {"status": "needs_review", "score": 68},
            "review_status": "needs_review",
        },
    ]

    updated = agent_runs._mark_selected_keyframe_candidate_review_approved(
        candidates,
        "https://cdn.test/selected.png",
    )

    assert updated[0]["review_status"] == "needs_review"
    assert updated[1]["review_status"] == "approved"
    assert updated[1]["review"]["status"] == "approved"
    assert updated[1]["review"]["approved_by"] == "human_selection"


@pytest.mark.asyncio
async def test_create_run_action_takes_priority_over_autopilot_mode(monkeypatch):
    called: dict[str, str] = {}

    async def fake_owner(db, *, project_id: str, user_id: int) -> None:
        called["owner"] = project_id

    async def fake_start_video_production(project_id: str, body: dict, db, current_user: dict) -> dict:
        called["branch"] = "production_run"
        called["mode"] = body["mode"]
        return {"agent_run_id": "run-1", "status": "queued", "task_id": "task-1", "production_run_id": "prod-1"}

    async def fake_continue_project_brain(project_id: str, body: dict, db, current_user: dict) -> dict:
        called["branch"] = "continue_project"
        return {"run_id": "run-2", "status": "completed"}

    async def fake_has_storyboard(db, *, project_id: str, user_id: int) -> bool:
        return True

    monkeypatch.setattr(agent_runs, "_ensure_project_owner", fake_owner)
    monkeypatch.setattr(agent_runs, "_project_has_storyboard_shots", fake_has_storyboard)
    monkeypatch.setattr(agent_runs, "start_video_production", fake_start_video_production)
    monkeypatch.setattr(agent_runs, "continue_project_brain", fake_continue_project_brain)

    result = await agent_runs.create_run(
        {"project_id": "project-1", "mode": "autopilot", "action": "production_run", "goal": "生成预览"},
        db=object(),
        current_user={"id": 1},
    )

    assert called == {"owner": "project-1", "branch": "production_run", "mode": "autopilot"}
    assert result["run_id"] == "run-1"
    assert result["production_run_id"] == "prod-1"


@pytest.mark.asyncio
async def test_create_run_production_run_routes_empty_project_to_story_plan_without_stopping_chain(monkeypatch):
    called: dict[str, str] = {}

    async def fake_owner(db, *, project_id: str, user_id: int) -> None:
        called["owner"] = project_id

    async def fake_has_storyboard(db, *, project_id: str, user_id: int) -> bool:
        called["checked_project"] = project_id
        return False

    async def fake_start_video_production(project_id: str, body: dict, db, current_user: dict) -> dict:
        called["branch"] = "production_run"
        return {"agent_run_id": "run-video", "status": "queued"}

    async def fake_continue_project_brain(project_id: str, body: dict, db, current_user: dict) -> dict:
        called["branch"] = "continue_project"
        called["action"] = body["action"]
        called["instruction"] = body["instruction"]
        called["stop_after_planning"] = str(body.get("_stop_after_planning"))
        return {"run_id": "run-story", "status": "completed", "action": body["action"]}

    monkeypatch.setattr(agent_runs, "_ensure_project_owner", fake_owner)
    monkeypatch.setattr(agent_runs, "_project_has_storyboard_shots", fake_has_storyboard)
    monkeypatch.setattr(agent_runs, "start_video_production", fake_start_video_production)
    monkeypatch.setattr(agent_runs, "continue_project_brain", fake_continue_project_brain)

    result = await agent_runs.create_run(
        {"project_id": "project-1", "mode": "step", "action": "production_run", "goal": "做一段接近《主角》的1分钟视频"},
        db=object(),
        current_user={"id": 1},
    )

    assert called["branch"] == "continue_project"
    assert called["action"] == "generate_story_plan"
    assert called["instruction"] == "做一段接近《主角》的1分钟视频"
    assert called["stop_after_planning"] != "True"
    assert result["run_id"] == "run-story"
    assert result["action"] == "continue_project"
    assert result["result"]["routed_from"] == "production_run_missing_storyboard"


@pytest.mark.asyncio
async def test_create_run_production_run_allows_autopilot_to_continue_after_story_plan(monkeypatch):
    called: dict[str, object] = {}

    async def fake_owner(db, *, project_id: str, user_id: int) -> None:
        called["owner"] = project_id

    async def fake_has_storyboard(db, *, project_id: str, user_id: int) -> bool:
        return False

    async def fake_continue_project_brain(project_id: str, body: dict, db, current_user: dict) -> dict:
        called["body"] = body
        return {"run_id": "run-story", "status": "running", "action": body["action"]}

    monkeypatch.setattr(agent_runs, "_ensure_project_owner", fake_owner)
    monkeypatch.setattr(agent_runs, "_project_has_storyboard_shots", fake_has_storyboard)
    monkeypatch.setattr(agent_runs, "continue_project_brain", fake_continue_project_brain)

    result = await agent_runs.create_run(
        {"project_id": "project-1", "mode": "autopilot", "action": "production_run", "goal": "生成一分钟视频", "allowed_max_credits": 500},
        db=object(),
        current_user={"id": 1},
    )

    body = called["body"]
    assert isinstance(body, dict)
    assert body["action"] == "generate_story_plan"
    assert body["mode"] == "autopilot"
    assert body.get("_stop_after_planning") is not True
    assert result["action"] == "continue_project"


@pytest.mark.asyncio
async def test_start_video_production_blocks_empty_project_before_queue(monkeypatch):
    called: dict[str, bool] = {}

    async def fake_owner(db, project_id: str, user_id: int) -> None:
        called["owner"] = True

    async def fake_has_storyboard(db, *, project_id: str, user_id: int) -> bool:
        called["checked_storyboard"] = True
        return False

    async def fake_create_agent_run(*args, **kwargs) -> str:
        called["created_run"] = True
        return "run-1"

    monkeypatch.setattr(workbench, "_ensure_project_owner", fake_owner)
    monkeypatch.setattr(workbench, "_project_has_storyboard_shots", fake_has_storyboard)
    monkeypatch.setattr(workbench, "create_agent_run", fake_create_agent_run)

    with pytest.raises(HTTPException) as exc:
        await workbench.start_video_production(
            "project-1",
            body={"goal": "做一段视频"},
            db=object(),
            current_user={"id": 1, "tier": "free"},
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "storyboard_required"
    assert exc.value.detail["recovery"] == "generate_story_plan"
    assert called == {"owner": True, "checked_storyboard": True}


@pytest.mark.asyncio
async def test_start_video_production_routes_video_runner_through_gateway(monkeypatch):
    observed: dict[str, object] = {}

    async def fake_owner(db, project_id: str, user_id: int) -> None:
        observed["owner"] = project_id

    async def fake_has_storyboard(db, *, project_id: str, user_id: int) -> bool:
        observed["checked_storyboard"] = project_id
        return True

    async def fake_create_agent_run(*args, **kwargs) -> str:
        observed["create_run_meta"] = kwargs["meta"]
        return "11111111-1111-1111-1111-111111111111"

    async def fake_dispatch(_db, *, packet, context, handlers):
        observed["packet"] = packet
        observed["context"] = context
        observed["handler_names"] = sorted(handlers.keys())
        return {
            "agent_run_id": context.run_id,
            "production_run_id": "prod-1",
            "task_id": "task-1",
            "status": "queued",
        }

    monkeypatch.setattr(workbench, "_ensure_project_owner", fake_owner)
    monkeypatch.setattr(workbench, "_project_has_storyboard_shots", fake_has_storyboard)
    monkeypatch.setattr(workbench, "create_agent_run", fake_create_agent_run)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench.start_video_production(
        "project-1",
        body={"goal": "generate preview", "provider_mode": "real", "video_provider": "seedance"},
        db=object(),
        current_user={"id": 1, "tier": "free"},
    )

    packet = observed["packet"]
    context = observed["context"]
    create_run_meta = observed["create_run_meta"]

    assert packet.action == "video_production_run"
    assert packet.selected_lane == "c_lane_production"
    assert context.run_id == "11111111-1111-1111-1111-111111111111"
    assert observed["handler_names"] == ["video_production_run"]
    assert create_run_meta["dispatch"] == "dispatch_gateway"
    assert create_run_meta["compatibility_only"] is True
    assert result["agent_run_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["production_run_id"] == "prod-1"
