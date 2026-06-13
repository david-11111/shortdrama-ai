from app.services.agent_control_registry import (
    allowed_recommendations_for_tool,
    followup_action_for_recommendation,
    is_control_diagnostic_tool,
)


def test_script_capability_allows_director_note_and_shot_revision_recommendations():
    allowed = allowed_recommendations_for_tool("diagnose_script", recommended="revise_director_notes")

    assert "revise_director_notes" in allowed
    assert "revise_shots" in allowed
    assert "generate_story_plan" in allowed
    assert "drop_database" not in allowed


def test_script_revision_recommendations_map_to_story_plan_execution():
    assert followup_action_for_recommendation("revise_story_plan") == "generate_story_plan"
    assert followup_action_for_recommendation("revise_director_notes") == "generate_story_plan"
    assert followup_action_for_recommendation("revise_shots") == "generate_story_plan"


def test_only_registered_diagnostic_tools_are_control_tools():
    assert is_control_diagnostic_tool("diagnose_outputs") is True
    assert is_control_diagnostic_tool("diagnose_script") is True
    assert is_control_diagnostic_tool("diagnose_keyframe_pool") is True
    assert is_control_diagnostic_tool("direct_sql") is False


def test_keyframe_pool_recommendations_are_split_between_preview_and_dispatch():
    allowed = allowed_recommendations_for_tool("diagnose_keyframe_pool", recommended="generate_keyframe_batch")

    assert "expand_shot_to_keyframe_prompts" in allowed
    assert "generate_keyframe_batch" in allowed
    assert "select_keyframe_candidate" in allowed
    assert followup_action_for_recommendation("generate_keyframe_batch") == "generate_keyframes"
    assert followup_action_for_recommendation("generate_video_from_pool") == "generate_videos"
