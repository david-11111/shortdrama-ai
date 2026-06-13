from app.services.agent_control_registry import CAPABILITY_REGISTRY
from app.services.agent_semantic_controller import (
    attach_semantic_control,
    build_constraint_packet,
    build_intent_brief,
    build_verification_plan,
    classify_controller_intent,
    classify_target_domain,
    classify_utterance,
    compile_semantic_plan,
)


def test_controller_intent_routes_no_video_question_to_output_diagnostics():
    intent = classify_controller_intent("为何没生成视频呢")

    assert intent is not None
    assert intent.intent_type == "ui_diagnostic"
    assert intent.tool_name == "diagnose_outputs"
    assert intent.action == "status_query"


def test_controller_intent_routes_task_question_to_task_diagnostics():
    intent = classify_controller_intent("什么什么任务呢？")

    assert intent is not None
    assert intent.intent_type == "task_diagnostic"
    assert intent.tool_name == "diagnose_tasks"
    assert intent.action == "status_query"


def test_utterance_question_sets_inspect_only_ceiling():
    frame = classify_utterance("我感觉到没在剪辑呢？这么久了")

    assert frame.utterance_type == "question"
    assert frame.action_ceiling == "inspect_only"


def test_utterance_command_allows_execution():
    frame = classify_utterance("直接进入剪辑")

    assert frame.utterance_type == "command"
    assert frame.action_ceiling == "execute_allowed"


def test_utterance_confirmation_requires_pending_confirm():
    frame = classify_utterance("好的，执行吧")

    assert frame.utterance_type == "confirm"
    assert frame.action_ceiling == "pending_confirm"


def test_short_confirmation_with_execute_phrase_requires_pending_confirm():
    frame = classify_utterance("好，执行吧")

    assert frame.utterance_type == "confirm"
    assert frame.action_ceiling == "pending_confirm"


def test_target_domain_prefers_final_edit_for_edit_video_status():
    assert classify_target_domain("剪辑视频怎么还没好？", action="status_query") == "final_edit"


def test_controller_intent_prefers_final_edit_when_script_is_context():
    intent = classify_controller_intent("根据剧本情况自行剪辑，配音，配字幕，配音乐")

    assert intent is not None
    assert intent.intent_type == "production_action"
    assert intent.tool_name == "plan_final_edit"
    assert intent.action == "plan_final_edit"


def test_controller_intent_routes_missing_final_edit_question_to_diagnostics():
    intent = classify_controller_intent("怎么没剪辑成片呢")

    assert intent is not None
    assert intent.intent_type == "ui_diagnostic"
    assert intent.tool_name == "diagnose_outputs"
    assert intent.action == "status_query"


def test_controller_intent_routes_final_edit_completion_question_to_diagnostics():
    intent = classify_controller_intent("剪辑好了吗")

    assert intent is not None
    assert intent.intent_type == "ui_diagnostic"
    assert intent.tool_name == "diagnose_outputs"
    assert intent.action == "status_query"


def test_intent_brief_preserves_ad_semantics_and_negative_constraints():
    brief = build_intent_brief("我想做一段30秒的黄金首饰广告视频，电影级别，小金饰品牌，高级、精致、有光影质感")

    assert brief["category"] == "commercial_video"
    assert brief["duration_sec"] == 30
    assert "黄金首饰是画面主角" in brief["must_keep"]
    assert "品牌调性优先于剧情冲突" in brief["must_keep"]
    assert "短剧冲突" in brief["must_avoid"]
    assert "廉价电商促销风" in brief["must_avoid"]
    assert "电影级" in brief["tone"]


def test_semantic_plan_constraint_packet_and_verification_are_machine_readable():
    brief = build_intent_brief("做30秒黄金首饰广告")
    plan = compile_semantic_plan(brief, routing={"resolved_action": "generate_keyframes"})
    constraints = build_constraint_packet(brief)
    verification = build_verification_plan("generate_keyframes", diagnostics={"outputs": {"recommended_action": "repair_missing_images"}})

    assert plan["target_action"] == "generate_keyframes"
    assert "inspect_missing_keyframes" in plan["steps"]
    assert constraints["version"] == "constraint_packet_v1"
    assert "结果必须符合用户原始意图" in constraints["quality_bar"]
    assert "selected_image_writeback" in verification["checks"]
    assert verification["source_diagnostics"] == ["outputs"]


def test_attach_semantic_control_writes_brief_plan_constraints_to_body_and_routing():
    body, routing = attach_semantic_control(
        {"instruction": "做30秒黄金首饰广告", "action": "generate_story_plan"},
        {"instruction": "做30秒黄金首饰广告", "resolved_action": "generate_story_plan"},
    )

    assert body["intent_brief"]["category"] == "commercial_video"
    assert body["semantic_plan"]["target_action"] == "generate_story_plan"
    assert body["constraint_packet"]["version"] == "constraint_packet_v1"
    assert routing["semantic"]["verification_plan"]["action"] == "generate_story_plan"


def test_core_capabilities_are_registered_with_policy_and_verify_contracts():
    for action in ["status_query", "generate_story_plan", "plan_visual_assets", "generate_keyframes", "generate_videos", "plan_final_edit"]:
        capability = CAPABILITY_REGISTRY[action]
        assert capability["version"]
        assert capability["risk_level"] in {"read_only", "safe_write", "expensive_write"}
        assert capability["auto_execute_policy"]
        assert capability["required_permission"]
        assert capability["gate_rules"]
        assert capability["verify"]
