from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionRegistration:
    name: str
    label: str
    lane: str
    allowed_writes: list[str] = field(default_factory=list)
    capability: str = "execute_assigned_mission"
    node_id: str = ""
    planner_allowed: bool = True
    production_stage_id: str = ""
    requires_features: list[str] = field(default_factory=list)
    requires_providers: list[str] = field(default_factory=list)


REGISTRY: dict[str, ActionRegistration] = {
    "generate_story_plan": ActionRegistration(
        name="generate_story_plan",
        label="Generate script/storyboard",
        lane="a_lane_project_brain",
        node_id="plan_shots",
        allowed_writes=["project_workspace", "shot_rows", "agent_events", "agent_runs"],
        capability="plan",
        production_stage_id="generate_story_plan",
    ),
    "plan_visual_assets": ActionRegistration(
        name="plan_visual_assets",
        label="Plan visual assets / reference images",
        lane="a_lane_project_brain",
        node_id="lock_visual_assets",
        allowed_writes=["asset_refs", "project_workspace", "agent_events", "agent_runs"],
        capability="plan",
        production_stage_id="plan_visual_assets",
    ),
    "lock_assets": ActionRegistration(
        name="lock_assets",
        label="Lock reusable character/scene/prop assets",
        lane="a_lane_project_brain",
        node_id="lock_visual_assets",
        planner_allowed=False,
        production_stage_id="lock_assets",
    ),
    "generate_keyframes": ActionRegistration(
        name="generate_keyframes",
        label="Generate keyframe images (Seedream)",
        lane="c_lane_production",
        node_id="generate_keyframes",
        allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
        production_stage_id="generate_keyframes",
        requires_features=["image_generation"],
    ),
    "generate_videos": ActionRegistration(
        name="generate_videos",
        label="Generate video clips (LTX 2.3)",
        lane="c_lane_production",
        node_id="generate_videos",
        allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
        production_stage_id="generate_videos",
        requires_features=[
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        requires_providers=["ltx23_image_to_video"],
    ),
    "plan_final_edit": ActionRegistration(
        name="plan_final_edit",
        label="Plan final video edit / export",
        lane="c_lane_production",
        node_id="ffmpeg_export",
        allowed_writes=["final_edit_plans", "project_workspace", "agent_events", "agent_runs"],
        production_stage_id="final_cut",
        requires_features=[
            "scene_analysis",
            "selected_video_read",
            "final_edit_plan_writeback",
        ],
    ),
    "status_query": ActionRegistration(
        name="status_query",
        label="Query run status and diagnostics",
        lane="main_chain",
    ),
    "writeback_review": ActionRegistration(
        name="writeback_review",
        label="Write back results and review",
        lane="main_chain",
        node_id="writeback",
        planner_allowed=False,
        production_stage_id="writeback_review",
    ),
}


def registered_planner_actions() -> set[str]:
    return {name for name, r in REGISTRY.items() if r.planner_allowed}


def lookup(name: str) -> ActionRegistration | None:
    return REGISTRY.get(name)


def lane_for_action(name: str, *, default: str = "main_chain") -> str:
    r = REGISTRY.get(name)
    return r.lane if r else default


def allowed_writes_for_action(name: str) -> list[str]:
    r = REGISTRY.get(name)
    return list(r.allowed_writes) if r else []


def capability_for_action(name: str, *, default: str = "execute_assigned_mission") -> str:
    r = REGISTRY.get(name)
    return r.capability if r else default


def node_id_for_action(name: str, *, default: str = "writeback") -> str:
    r = REGISTRY.get(name)
    return r.node_id if r else default


def features_for_action(name: str) -> list[str]:
    r = REGISTRY.get(name)
    return list(r.requires_features) if r else []


def providers_for_action(name: str) -> list[str]:
    r = REGISTRY.get(name)
    return list(r.requires_providers) if r else []


def _production_actions_with_handler() -> set[str]:
    return {
        name
        for name, r in REGISTRY.items()
        if r.lane in {"c_lane_production", "a_lane_project_brain"} and r.planner_allowed
    }
