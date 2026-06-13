from __future__ import annotations


HUMAN_REQUESTABLE_ACTIONS: set[str] = {
    "status_query",
    "generate_story_plan",
    "plan_visual_assets",
    "generate_keyframes",
    "generate_videos",
    "plan_final_edit",
}

HUMAN_DIRECT_EXECUTABLE_ACTIONS: set[str] = {
    "status_query",
}

HUMAN_EXECUTABLE_ACTIONS = HUMAN_REQUESTABLE_ACTIONS

CAPABILITY_REGISTRY: dict[str, dict] = {
    "status_query": {
        "version": "v1",
        "kind": "read",
        "risk_level": "read_only",
        "auto_execute_policy": "always",
        "required_permission": "agent_run:read",
        "tools": ["diagnose_outputs", "diagnose_tasks", "diagnose_provider_writeback", "diagnose_script", "diagnose_keyframe_pool"],
        "parameters_schema": {"type": "object", "properties": {"instruction": {"type": "string"}}},
        "gate_rules": ["run_owner"],
        "verify": ["agent_event_written", "snapshot_refreshable"],
    },
    "generate_story_plan": {
        "version": "v1",
        "kind": "write",
        "risk_level": "safe_write",
        "auto_execute_policy": "idle_auto_execute",
        "required_permission": "agent_run:write",
        "tools": ["doubao", "project_brain"],
        "parameters_schema": {"type": "object", "properties": {"intent_brief": {"type": "object"}, "constraint_packet": {"type": "object"}}},
        "gate_rules": ["run_owner", "busy_gate", "state_machine_gate"],
        "verify": ["script_content_present", "shot_rows_present", "sse_visible"],
    },
    "plan_visual_assets": {
        "version": "v1",
        "kind": "write",
        "risk_level": "safe_write",
        "auto_execute_policy": "idle_auto_execute",
        "required_permission": "agent_run:write",
        "tools": ["project_brain", "seedream"],
        "parameters_schema": {"type": "object", "properties": {"intent_brief": {"type": "object"}, "constraint_packet": {"type": "object"}}},
        "gate_rules": ["run_owner", "busy_gate", "state_machine_gate"],
        "verify": ["visual_assets_present", "snapshot_refreshable", "sse_visible"],
    },
    "generate_keyframes": {
        "version": "v1",
        "kind": "write",
        "risk_level": "expensive_write",
        "auto_execute_policy": "idle_auto_execute_with_budget_gate",
        "required_permission": "agent_run:write",
        "tools": ["seedream"],
        "parameters_schema": {"type": "object", "properties": {"target_shots": {"type": "array"}, "constraint_packet": {"type": "object"}}},
        "gate_rules": ["run_owner", "busy_gate", "state_machine_gate", "cost_gate"],
        "verify": ["image_task_dispatched", "selected_image_writeback", "outputs_images_increment", "sse_visible"],
    },
    "generate_videos": {
        "version": "v1",
        "kind": "write",
        "risk_level": "expensive_write",
        "auto_execute_policy": "idle_auto_execute_with_budget_gate",
        "required_permission": "agent_run:write",
        "tools": ["seedance", "kling"],
        "parameters_schema": {"type": "object", "properties": {"target_shots": {"type": "array"}, "constraint_packet": {"type": "object"}}},
        "gate_rules": ["run_owner", "busy_gate", "state_machine_gate", "cost_gate", "selected_image_required"],
        "verify": ["video_task_dispatched", "selected_video_writeback", "outputs_videos_increment", "sse_visible"],
    },
    "plan_final_edit": {
        "version": "v1",
        "kind": "write",
        "risk_level": "expensive_write",
        "auto_execute_policy": "idle_auto_execute_with_budget_gate",
        "required_permission": "agent_run:write",
        "tools": ["ffmpeg"],
        "parameters_schema": {"type": "object", "properties": {"constraint_packet": {"type": "object"}}},
        "gate_rules": ["run_owner", "busy_gate", "state_machine_gate", "selected_video_required"],
        "verify": ["final_preview_or_export_present", "sse_visible"],
    },
}

CONTROL_DIAGNOSTIC_TOOLS: set[str] = {
    "diagnose_outputs",
    "diagnose_tasks",
    "diagnose_provider_writeback",
    "diagnose_script",
    "diagnose_keyframe_pool",
}

PRODUCTION_ACTIONS: set[str] = {
    "generate_story_plan",
    "plan_visual_assets",
    "generate_keyframes",
    "generate_videos",
    "plan_final_edit",
}

DIAGNOSTIC_ALLOWED_RECOMMENDATIONS: dict[str, set[str]] = {
    "diagnose_outputs": {
        "inspect_outputs",
        "inspect_browser_network",
        "refresh_asset_urls",
        "repair_missing_images",
        "repair_missing_videos",
        "reload_snapshot",
    },
    "diagnose_tasks": {
        "inspect_outputs",
        "wait_active_tasks",
        "retry_failed_keyframes",
        "retry_failed_videos",
    },
    "diagnose_provider_writeback": {
        "inspect_outputs",
        "repair_missing_images",
        "repair_missing_videos",
    },
    "diagnose_script": {
        "inspect_script",
        "inspect_director_notes",
        "inspect_shots",
        "revise_story_plan",
        "revise_director_notes",
        "revise_shots",
        "generate_story_plan",
    },
    "diagnose_keyframe_pool": {
        "inspect_keyframe_pool",
        "expand_shot_to_keyframe_prompts",
        "generate_keyframe_batch",
        "select_keyframe_candidate",
        "repair_keyframe_pool",
        "generate_video_from_pool",
    },
}

RECOMMENDATION_TO_PRODUCTION_ACTION: dict[str, str] = {
    "repair_missing_images": "generate_keyframes",
    "repair_missing_videos": "generate_videos",
    "retry_failed_keyframes": "generate_keyframes",
    "retry_failed_videos": "generate_videos",
    "revise_story_plan": "generate_story_plan",
    "revise_director_notes": "generate_story_plan",
    "revise_shots": "generate_story_plan",
    "generate_story_plan": "generate_story_plan",
    "generate_keyframe_batch": "generate_keyframes",
    "repair_keyframe_pool": "generate_keyframes",
    "generate_video_from_pool": "generate_videos",
}

ACTION_DOMAINS: dict[str, str] = {
    "generate_story_plan": "story",
    "plan_visual_assets": "visual_asset",
    "generate_keyframes": "keyframe",
    "generate_videos": "video",
    "plan_final_edit": "final_edit",
}

RECOMMENDATION_DOMAINS: dict[str, str] = {
    "repair_missing_images": "keyframe",
    "repair_missing_videos": "video",
    "retry_failed_keyframes": "keyframe",
    "retry_failed_videos": "video",
    "revise_story_plan": "story",
    "revise_director_notes": "story",
    "revise_shots": "story",
    "generate_story_plan": "story",
    "generate_keyframe_batch": "keyframe",
    "repair_keyframe_pool": "keyframe",
    "generate_video_from_pool": "video",
}

NON_DISPATCH_RECOMMENDATIONS: set[str] = {
    "",
    "inspect_outputs",
    "inspect_browser_network",
    "inspect_script",
    "inspect_director_notes",
    "inspect_shots",
    "reload_snapshot",
    "refresh_asset_urls",
    "wait_active_tasks",
    "change_provider",
    "inspect_keyframe_pool",
    "expand_shot_to_keyframe_prompts",
    "select_keyframe_candidate",
}

COMPOSER_ACTIONS: set[str] = (
    set(NON_DISPATCH_RECOMMENDATIONS)
    | set(RECOMMENDATION_TO_PRODUCTION_ACTION)
    | set(PRODUCTION_ACTIONS)
)


def allowed_recommendations_for_tool(tool_name: str, *, recommended: str = "") -> list[str]:
    allowed = {"", "inspect_outputs"}
    allowed.update(DIAGNOSTIC_ALLOWED_RECOMMENDATIONS.get(tool_name, set()))
    if recommended:
        allowed.add(recommended)
    return sorted(action for action in allowed if action in COMPOSER_ACTIONS)


def followup_action_for_recommendation(recommendation: str) -> str:
    return RECOMMENDATION_TO_PRODUCTION_ACTION.get(str(recommendation or "").strip(), "")


def domain_for_action(action: str) -> str:
    return ACTION_DOMAINS.get(str(action or "").strip(), "")


def domain_for_recommendation(recommendation: str) -> str:
    value = str(recommendation or "").strip()
    return RECOMMENDATION_DOMAINS.get(value) or domain_for_action(value)


def is_control_diagnostic_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip() in CONTROL_DIAGNOSTIC_TOOLS
