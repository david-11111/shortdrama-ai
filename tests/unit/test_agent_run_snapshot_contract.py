from copy import deepcopy
from pathlib import Path

import pytest

from app.services.agent_run_snapshot import SNAPSHOT_VERSION, STANDARD_NODES, _build_decision_context, _build_outputs, _build_stream, _event, _filter_shots_for_clean_start, _merge_final_video_preview, validate_snapshot_contract
from app.services.agent_run_state_machine import evaluate_production_stages


ROOT = Path(__file__).resolve().parents[2]
ROUTES_INIT_SOURCE = (ROOT / "app" / "routes" / "__init__.py").read_text(encoding="utf-8")
AGENT_RUNS_ROUTE_SOURCE = (ROOT / "app" / "routes" / "agent_runs.py").read_text(encoding="utf-8")


def _valid_snapshot() -> dict:
    return {
        "version": SNAPSHOT_VERSION,
        "run": {"run_id": "run-1", "project_id": "project-1", "user_id": 1, "status": "running"},
        "project": {"project_id": "project-1", "name": "Demo"},
        "budget": {
            "estimated_max_credits": 0,
            "allowed_max_credits": 0,
            "reserved_credits": 0,
            "spent_credits": 0,
            "refunded_credits": 0,
            "remaining_run_budget": 0,
            "task_credits_reserved": 0,
        },
        "ledger": {},
        "nodes": [
            {
                "id": node["id"],
                "title": node["title"],
                "status": "pending",
                "summary": "",
                "progress": 0,
                "event_ids": [],
                "task_ids": [],
                "available_actions": [],
            }
            for node in STANDARD_NODES
        ],
        "flow": evaluate_production_stages(shots=[], tasks=[]),
        "state_machine": {
            "stage": "read_context",
            "allowed": True,
            "blocked": False,
            "missing": [],
            "reason": "",
            "next_action": "analyze_project",
            "available_actions": ["analyze_project"],
        },
        "stream": [],
        "decision_context": {
            "current_goal": "Demo",
            "awaiting_user": "",
            "pending_action": None,
            "last_recommendation": "",
            "blocked_by": [],
            "block_reason": "",
            "next_action": "analyze_project",
            "routing_source": "",
            "target_domain": "",
            "updated_at": "",
        },
        "events": {"user": [], "expert": [], "debug": []},
        "evidence": {node["id"]: {} for node in STANDARD_NODES},
        "evidence_layers": {
            "agent_execution_log": {"id": "agent_execution_log", "title": "Agent 执行日志", "summary": "", "count": 0, "items": [], "meta": {}},
            "brain_trace": {"id": "brain_trace", "title": "大脑执行轨迹", "summary": "", "count": 0, "items": [], "meta": {}},
            "detailed_flow_ledger": {"id": "detailed_flow_ledger", "title": "详细流程账本", "summary": "", "count": 0, "items": [], "meta": {}},
            "raw_read_list": {"id": "raw_read_list", "title": "原始读取清单", "summary": "", "count": 0, "items": [], "meta": {}},
            "production_stream_terminal": {"id": "production_stream_terminal", "title": "制片流式终端", "summary": "", "count": 0, "items": [], "meta": {}},
            "progress_ledger": {"id": "progress_ledger", "title": "进度账本", "summary": "", "count": 0, "items": [], "meta": {}},
            "creative_technique_ledger": {"id": "creative_technique_ledger", "title": "制作技巧账本", "summary": "", "count": 0, "items": [], "meta": {}},
            "state_machine_flow": {"id": "state_machine_flow", "title": "Commercial production state machine", "summary": "", "count": 0, "items": [], "meta": {}},
        },
        "outputs": {
            "script": {"content": "", "items": []},
            "director_notes": [],
            "images": [],
            "videos": [],
            "shots": [],
            "summary": {"image_count": 0, "video_count": 0, "shot_count": 0, "final_video_url": "", "run_summary": ""},
        },
        "actions": [],
        "artifacts": [],
        "tasks": [],
    }


def test_snapshot_contract_accepts_minimal_v1_shape():
    validate_snapshot_contract(_valid_snapshot())


def test_snapshot_contract_requires_versioned_top_level_fields():
    snapshot = _valid_snapshot()
    snapshot.pop("evidence_layers")

    with pytest.raises(ValueError, match="top-level"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_requires_all_evidence_layers():
    snapshot = _valid_snapshot()
    snapshot["evidence_layers"].pop("raw_read_list")

    with pytest.raises(ValueError, match="raw_read_list"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_rejects_unsupported_version():
    snapshot = _valid_snapshot()
    snapshot["version"] = "agent_run_snapshot_v0"

    with pytest.raises(ValueError, match="unsupported"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_requires_all_standard_nodes():
    snapshot = _valid_snapshot()
    snapshot["nodes"] = [node for node in snapshot["nodes"] if node["id"] != "ffmpeg_export"]

    with pytest.raises(ValueError, match="ffmpeg_export"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_requires_node_runtime_fields():
    snapshot = _valid_snapshot()
    broken = deepcopy(snapshot["nodes"][0])
    broken.pop("available_actions")
    snapshot["nodes"][0] = broken

    with pytest.raises(ValueError, match="available_actions"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_requires_flow_stage_runtime_fields():
    snapshot = _valid_snapshot()
    broken = deepcopy(snapshot["flow"][0])
    broken.pop("source")
    snapshot["flow"][0] = broken

    with pytest.raises(ValueError, match="source"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_requires_flow_policy_metadata():
    snapshot = _valid_snapshot()
    broken = deepcopy(snapshot["flow"][0])
    broken.pop("policy")
    snapshot["flow"][0] = broken

    with pytest.raises(ValueError, match="policy"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_requires_state_machine_runtime_fields():
    snapshot = _valid_snapshot()
    snapshot["state_machine"].pop("next_action")

    with pytest.raises(ValueError, match="state_machine"):
        validate_snapshot_contract(snapshot)


def test_snapshot_contract_requires_decision_context_fields():
    snapshot = _valid_snapshot()
    snapshot["decision_context"].pop("pending_action")

    with pytest.raises(ValueError, match="decision_context"):
        validate_snapshot_contract(snapshot)


def test_decision_context_does_not_show_stale_pending_action_over_blocker():
    context = _build_decision_context(
        run={
            "goal": "make video",
            "meta": {
                "decision_context": {
                    "next_action": "generate_videos",
                    "awaiting_user": "confirm",
                    "blocked_by": [],
                },
                "pending_action": {
                    "action": "generate_videos",
                    "recommendation": "repair_missing_videos",
                    "domain": "video",
                },
            },
        },
        state_machine={
            "blocked": True,
            "missing": ["image_review_blockers"],
            "reason": "Keyframe review found shots that must be regenerated before video generation.",
            "next_action": "review_keyframes",
        },
    )

    assert context["awaiting_user"] == ""
    assert context["pending_action"] is None
    assert context["blocked_by"] == ["image_review_blockers"]
    assert context["next_action"] == "generate_keyframes"


def test_decision_context_keeps_review_repair_pending_action_for_recovery_action():
    context = _build_decision_context(
        run={
            "goal": "make video",
            "meta": {
                "decision_context": {
                    "next_action": "generate_keyframes",
                    "awaiting_user": "confirm",
                },
                "pending_action": {
                    "action": "generate_keyframes",
                    "recommendation": "regenerate_review_failed_keyframes",
                    "domain": "keyframe",
                },
            },
        },
        state_machine={
            "blocked": True,
            "missing": ["image_review_blockers"],
            "reason": "Keyframe review found shots that must be regenerated before video generation.",
            "next_action": "review_keyframes",
        },
    )

    assert context["awaiting_user"] == "confirm"
    assert context["pending_action"]["action"] == "generate_keyframes"
    assert context["blocked_by"] == ["image_review_blockers"]
    assert context["next_action"] == "generate_keyframes"


def test_snapshot_contract_requires_agent_event_protocol_fields():
    snapshot = _valid_snapshot()
    snapshot["events"]["user"].append({"id": "event-1", "visibility": "user", "event_kind": "decision", "summary": "ok"})

    with pytest.raises(ValueError, match="actor"):
        validate_snapshot_contract(snapshot)


def test_snapshot_event_protocol_keeps_debug_out_of_main_stream():
    user_event = _event(
        {
            "id": "event-user",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "seedream",
            "event_type": "tool_call",
            "phase": "seedream_requesting",
            "title": "Requesting Seedream",
            "detail": "prompt accepted",
            "status": "running",
            "progress": 30,
            "meta": {"agent_event": {"summary": "Seedream is generating a keyframe", "reason": "shot 1 needs an image"}},
            "created_at": None,
        }
    )
    debug_event = _event(
        {
            "id": "event-debug",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "deepseek",
            "event_type": "trace",
            "phase": "read_context",
            "title": "Raw planner payload",
            "detail": "{\"tokens\": 12}",
            "status": "done",
            "progress": 10,
            "meta": {
                "agent_event": {
                    "visibility": "debug",
                    "summary": "Planner raw JSON captured",
                    "debug": {"tokens": 12, "raw": {"ok": True}},
                }
            },
            "created_at": None,
        }
    )

    stream = _build_stream(events=[user_event, debug_event], nodes=STANDARD_NODES, limit=20)

    assert user_event["actor"] == "seedream"
    assert user_event["event_kind"] == "tool_call"
    assert user_event["summary"] == "Seedream is generating a keyframe"
    assert debug_event["visibility"] == "debug"
    assert debug_event["debug"] == {"tokens": 12, "raw": {"ok": True}}
    assert [item["id"] for item in stream] == ["event-user"]
    assert stream[0]["actor"] == "seedream"
    assert stream[0]["event_kind"] == "tool_call"
    assert stream[0]["summary"] == "Seedream is generating a keyframe"


def test_snapshot_stream_keeps_deepseek_planner_decision_as_main_trace():
    planner_event = _event(
        {
            "id": "event-planner",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "deepseek",
            "event_type": "decision",
            "phase": "llm_planner",
            "title": "DeepSeek 中控判断",
            "detail": "DeepSeek decided the next action should repair keyframes.",
            "status": "done",
            "progress": 72,
            "meta": {
                "agent_event": {
                    "actor": "deepseek",
                    "event_kind": "decision",
                    "visibility": "debug",
                    "summary": "DeepSeek chose generate_keyframes",
                    "reason": "keyframe review blocked video generation",
                }
            },
            "created_at": None,
        }
    )
    raw_debug_event = _event(
        {
            "id": "event-raw-debug",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "deepseek",
            "event_type": "trace",
            "phase": "read_context",
            "title": "Raw debug",
            "detail": "raw payload",
            "status": "done",
            "progress": 1,
            "meta": {"agent_event": {"visibility": "debug", "summary": "raw payload"}},
            "created_at": None,
        }
    )

    stream = _build_stream(events=[planner_event, raw_debug_event], nodes=STANDARD_NODES, limit=20)

    assert [item["id"] for item in stream] == ["event-planner"]
    assert stream[0]["visibility"] == "debug"
    assert stream[0]["phase"] == "llm_planner"
    assert stream[0]["actor"] == "deepseek"
    assert stream[0]["summary"] == "DeepSeek chose generate_keyframes"


def test_snapshot_stream_drops_duplicate_planner_when_human_response_has_same_text():
    text = "I see shots 1, 2, 3 failed review. Confirm repair?"
    response_event = _event(
        {
            "id": "event-response",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "deepseek",
            "event_type": "tool_result",
            "phase": "human_response",
            "title": "DeepSeek 先答复人工输入",
            "detail": text,
            "status": "done",
            "progress": 75,
            "meta": {"agent_event": {"actor": "deepseek", "event_kind": "tool_result", "visibility": "user", "summary": text}},
            "created_at": "2026-05-25T06:12:43+00:00",
        }
    )
    duplicate_planner = _event(
        {
            "id": "event-planner",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "deepseek",
            "event_type": "decision",
            "phase": "llm_planner",
            "title": "DeepSeek 中控判断",
            "detail": text,
            "status": "done",
            "progress": 72,
            "meta": {"agent_event": {"actor": "deepseek", "event_kind": "decision", "visibility": "debug", "summary": text}},
            "created_at": "2026-05-25T06:12:43+00:00",
        }
    )

    stream = _build_stream(events=[response_event, duplicate_planner], nodes=STANDARD_NODES, limit=20)

    assert [item["id"] for item in stream] == ["event-response"]


def test_snapshot_stream_drops_duplicate_human_response_text():
    first = _event(
        {
            "id": "event-response-1",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "deepseek",
            "event_type": "tool_result",
            "phase": "human_response",
            "title": "DeepSeek 先答复人工输入",
            "detail": "Confirm repair for shots 1, 2, 3.",
            "status": "done",
            "progress": 75,
            "meta": {"agent_event": {"actor": "deepseek", "event_kind": "tool_result", "visibility": "user", "summary": "Confirm repair for shots 1, 2, 3."}},
            "created_at": "2026-05-25T06:12:43+00:00",
        }
    )
    duplicate = {**first, "id": "event-response-2", "created_at": "2026-05-25T06:12:50+00:00"}

    stream = _build_stream(events=[first, duplicate], nodes=STANDARD_NODES, limit=20)

    assert [item["id"] for item in stream] == ["event-response-1"]


def test_legacy_agent_event_gets_compatible_protocol_defaults():
    event = _event(
        {
            "id": "event-old",
            "run_id": "run-1",
            "project_id": "project-1",
            "task_id": None,
            "step_id": None,
            "user_id": 1,
            "source": "brain",
            "event_type": "risk",
            "phase": "cost_guard",
            "title": "Budget blocked",
            "detail": "needs more credits",
            "status": "blocked",
            "progress": 100,
            "meta": {},
            "created_at": None,
        }
    )

    assert event["actor"] == "brain"
    assert event["event_kind"] == "guardrail"
    assert event["visibility"] == "user"
    assert event["summary"] == "Budget blocked"


def test_standard_nodes_cover_video_production_backbone():
    node_ids = {node["id"] for node in STANDARD_NODES}

    assert {
        "read_context",
        "merge_memory",
        "generate_keyframes",
        "generate_videos",
        "audio_subtitles",
        "ffmpeg_export",
        "quality_check",
        "writeback",
    }.issubset(node_ids)


def test_snapshot_outputs_collect_visible_media_and_notes():
    outputs = _build_outputs(
        run={"summary": "run summary"},
        events=[{"event_type": "decision", "title": "导演判断", "detail": "先确认视觉资产", "created_at": "t1"}],
        tasks=[
            {
                "task_id": "task-image",
                "task_type": "image_gen",
                "stage_text": "Image done",
                "payload": {"shot_index": 1},
                "result": {"image_url": "https://example.test/shot1.png"},
            }
        ],
        steps=[{"phase": "generate_story_plan", "title": "分镜", "output_summary": "第一镜开场"}],
        artifacts=[],
        shots=[
            {
                "shot_index": 1,
                "prompt": "黄金首饰特写",
                "duration": 4,
                "status": "image_done",
                "selected_image": "https://example.test/selected.png",
                "selected_video": "https://example.test/selected.mp4",
                "image_candidates": [],
                "video_variants": [],
            }
        ],
        production_run={"final_video_url": "https://example.test/final.mp4"},
    )

    assert outputs["summary"]["image_count"] == 2
    assert outputs["summary"]["video_count"] == 2
    assert outputs["script"]["content"] == "第一镜开场"
    assert outputs["director_notes"][-1]["content"] == "先确认视觉资产"
    assert outputs["images"][0]["url"] == "https://example.test/selected.png"
    assert outputs["videos"][0]["url"] == "https://example.test/selected.mp4"


def test_clean_start_snapshot_filters_project_level_old_shots():
    shots = [
        {
            "shot_index": 1,
            "prompt": "old project shadow",
            "selected_image": "https://example.test/old.png",
            "updated_at": "2026-05-28T09:59:00",
        },
        {
            "shot_index": 2,
            "prompt": "new run shot",
            "selected_image": "https://example.test/new.png",
            "updated_at": "2026-05-28T10:01:00",
        },
    ]

    filtered = _filter_shots_for_clean_start(
        shots,
        run={"started_at": "2026-05-28T10:00:00", "meta": {"clean_start": True}},
    )

    assert [shot["shot_index"] for shot in filtered] == [2]


def test_snapshot_uses_preview_final_video_when_production_run_has_no_url():
    production_run = {
        "id": "production-1",
        "project_id": "project-1",
        "user_id": 4,
        "final_video_url": "",
        "final_task_id": "",
    }
    preview = {
        "final_video_url": "/api/director/final-video/task-preview",
        "final_task_id": "task-preview",
        "project_id": "project-1",
        "user_id": 4,
    }

    merged = _merge_final_video_preview(production_run, preview)
    outputs = _build_outputs(
        run={"summary": "preview exported"},
        events=[],
        tasks=[],
        steps=[],
        artifacts=[],
        shots=[],
        production_run=merged,
    )

    assert merged["final_video_url"] == "/api/director/final-video/task-preview"
    assert merged["final_task_id"] == "task-preview"
    assert outputs["summary"]["final_video_url"] == "/api/director/final-video/task-preview"
    assert outputs["videos"][0]["kind"] == "final_video"
    assert outputs["videos"][0]["url"] == "/api/director/final-video/task-preview"


def test_snapshot_keeps_production_run_final_url_over_preview_fallback():
    production_run = {
        "id": "production-1",
        "project_id": "project-1",
        "user_id": 4,
        "final_video_url": "/api/director/final-video/final-task",
        "final_task_id": "final-task",
    }
    preview = {
        "final_video_url": "/api/director/final-video/preview-task",
        "final_task_id": "preview-task",
    }

    merged = _merge_final_video_preview(production_run, preview)

    assert merged["final_video_url"] == "/api/director/final-video/final-task"
    assert merged["final_task_id"] == "final-task"


def test_snapshot_route_is_registered_and_user_scoped():
    assert "from app.routes.agent_runs import router as agent_runs_router" in ROUTES_INIT_SOURCE
    assert "api_router.include_router(agent_runs_router)" in ROUTES_INIT_SOURCE
    assert 'APIRouter(prefix="/agent-runs"' in AGENT_RUNS_ROUTE_SOURCE
    assert '@router.get("/{run_id}/snapshot")' in AGENT_RUNS_ROUTE_SOURCE
    assert '@router.get("/{run_id}/events")' in AGENT_RUNS_ROUTE_SOURCE
    assert '@router.post("/{run_id}/actions/retry-failed")' in AGENT_RUNS_ROUTE_SOURCE
    assert '@router.post("/{run_id}/actions/export-partial")' in AGENT_RUNS_ROUTE_SOURCE
    assert '@router.post("/{run_id}/actions/change-provider")' in AGENT_RUNS_ROUTE_SOURCE
    assert '@router.post("/{run_id}/actions/cancel")' in AGENT_RUNS_ROUTE_SOURCE
    assert "current_user: dict = Depends(get_current_user)" in AGENT_RUNS_ROUTE_SOURCE
    assert "user_id=int(current_user[\"id\"])" in AGENT_RUNS_ROUTE_SOURCE
    assert "event_limit: int = Query(300, ge=1, le=1000)" in AGENT_RUNS_ROUTE_SOURCE
    assert "project_id = await _ensure_run_owner" in AGENT_RUNS_ROUTE_SOURCE
    assert "credit_ledger" in (ROOT / "app" / "services" / "agent_run_snapshot.py").read_text(encoding="utf-8")
