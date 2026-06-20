import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routes import workbench
from app.services.director_preflight import analyze_shot_risk
from app.services import project_continue, project_workspace
from app.routes.workbench import _dispatch_action_after_planning, _estimate_continue_credits, _keyframe_generation_targets, _split_final_edit_rows


class _FakeGenerateBatchResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def mappings(self):
        return self

    def first(self):
        if not self._rows:
            return None
        row = self._rows[0]
        if isinstance(row, dict):
            return row
        return row.__dict__


class _FakeGenerateBatchDb:
    def __init__(self, rows, *, artifact_uri=""):
        self._rows = rows
        self._artifact_uri = artifact_uri
        self.executed = []
        self._select_count = 0

    async def execute(self, statement, params=None):
        text = str(statement)
        self.executed.append((text, params or {}))
        if "FROM agent_artifacts" in text:
            return _FakeGenerateBatchResult(
                [SimpleNamespace(uri=self._artifact_uri)] if self._artifact_uri else []
            )
        if "FROM shot_rows" in text and "ORDER BY shot_index ASC" in text:
            self._select_count += 1
            return _FakeGenerateBatchResult(self._rows)
        return _FakeGenerateBatchResult()

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _shot_row(index, *, selected_image="", selected_video="", status="ready"):
    return SimpleNamespace(
        shot_index=index,
        prompt=f"shot {index}",
        duration=5,
        status=status,
        selected=True,
        character_refs_json=[],
        scene_refs_json=[],
        prop_refs_json=[],
        costume_refs_json=[],
        style_refs_json=[],
        image_candidates_json=[],
        video_variants_json=[],
        selected_image=selected_image,
        selected_video=selected_video,
        last_error="",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


def _patch_generate_batch_dependencies(monkeypatch, sent):
    async def noop_async(*_args, **_kwargs):
        return None

    async def true_async(*_args, **_kwargs):
        return True

    async def price(_operation):
        return 10

    async def reserve(_user_id, operation, _count):
        return f"tx-{operation}-{len(sent)}"

    class Capacity:
        service = "seedream"
        total_concurrency = 0
        available_slots = 99
        estimated_wait_sec = 0

    def send_task(_name, args=None, **_kwargs):
        sent.append((args or [None, None, {}])[2]["shot_index"])

    monkeypatch.setattr(workbench, "revision_public_payload", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(workbench, "_guard_showrunner_generation_preflight", noop_async)
    monkeypatch.setattr(workbench, "check_concurrent_limit", noop_async)
    monkeypatch.setattr(workbench, "check_rate_limit", noop_async)
    monkeypatch.setattr(workbench, "ensure_run_budget", true_async)
    monkeypatch.setattr(workbench, "assert_cost_guard", noop_async)
    monkeypatch.setattr(workbench.credit_service, "get_price", price)
    monkeypatch.setattr(workbench, "reserve_credits", reserve)
    monkeypatch.setattr(workbench, "write_project_workspace_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(workbench, "publish_agent_event", noop_async)
    monkeypatch.setattr(workbench, "update_agent_run", noop_async)
    monkeypatch.setattr(workbench.celery_app, "send_task", send_task)
    monkeypatch.setattr("app.services.capacity_guard.check_capacity_sync", lambda _provider: Capacity())


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


def test_continue_project_from_brain_generates_concrete_courier_office_shots(monkeypatch):
    storage = Path("storage") / "test-project-continue" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        instruction = "我想做一段快递员送黄金区一个高档写字楼的视频"
        result = project_continue.continue_project_from_brain(
            "continue-courier-office",
            instruction=instruction,
            name="快递员高档写字楼送件",
        )

        assert result["applied"] is True
        assert result["intent_constraints"]["story_type"] == "courier_office_delivery"
        prompts = "\n".join(row["prompt"] for row in result["shot_rows"])
        assert "快递员" in prompts
        assert "高档写字楼" in prompts
        assert "包裹" in prompts
        assert "门禁" in prompts
        assert "对手方" not in prompts
        assert all("快递员" in row["prompt"] or "快递包裹" in row["prompt"] for row in result["shot_rows"])
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


@pytest.mark.asyncio
async def test_continue_project_brain_respects_requested_production_action(monkeypatch):
    observed = {}

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return self._rows

    class _Db:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "SELECT name FROM projects" in sql:
                return _Result([SimpleNamespace(name="project-1")])
            if "FROM shot_rows" in sql:
                return _Result([_shot_row(1, selected_image="https://cdn.test/1.png")])
            return _Result([])

        async def commit(self):
            return None

    async def noop_async(*_args, **_kwargs):
        return None

    async def dispatch_action(_db, *, action, **_kwargs):
        observed["action"] = action
        return {"status": "queued", "action": action}

    monkeypatch.setattr(workbench, "_ensure_project_owner", noop_async)
    monkeypatch.setattr(workbench, "_fetch_saved_final_edit_plan", AsyncMock(return_value=None))
    monkeypatch.setattr(workbench, "_fetch_visual_plan_payload", AsyncMock(return_value=(None, None, None)))
    monkeypatch.setattr(
        workbench,
        "build_project_brain",
        lambda *_args, **_kwargs: {
            "next_action": "generate_videos",
            "can_continue": True,
            "signals": {
                "operational_pending_keyframe_count": 1,
                "operational_pending_video_count": 1,
                "workspace_shot_count": 1,
            },
            "context": {},
        },
    )
    monkeypatch.setattr(workbench, "_fetch_project_tasks_for_agent_gate", AsyncMock(return_value=[]))
    monkeypatch.setattr(workbench, "evaluate_action_gate", lambda *_args, **_kwargs: {"allowed": True})
    monkeypatch.setattr(workbench.credit_service, "get_price", AsyncMock(return_value=10))
    monkeypatch.setattr(workbench, "create_agent_run", AsyncMock(return_value="run-1"))
    monkeypatch.setattr(workbench, "emit_brain_snapshot_steps", noop_async)
    monkeypatch.setattr(workbench, "_dispatch_production_action", dispatch_action)

    result = await workbench.continue_project_brain(
        "project-1",
        body={"action": "generate_keyframes", "mode": "step"},
        db=_Db(),
        current_user={"id": 7, "tier": "pro"},
    )

    assert observed["action"] == "generate_keyframes"
    assert result["action"] == "generate_keyframes"


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
async def test_dispatch_production_action_passes_shot_indices_to_generation_handler(monkeypatch):
    observed = {}

    async def fake_load(_db, *, run_id, user_id):
        return None

    async def fake_dispatch(_db, *, packet, context, handlers):
        return await handlers["generate_keyframes"]()

    async def fake_continue_keyframes(*_args, shot_indices=None, **_kwargs):
        observed["shot_indices"] = shot_indices
        return {"ok": True}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)
    monkeypatch.setattr(workbench, "_continue_generate_keyframes", fake_continue_keyframes)

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
        shot_indices=[3],
    )

    assert result == {"ok": True}
    assert observed["shot_indices"] == [3]


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


@pytest.mark.asyncio
async def test_dispatch_production_action_uses_blocked_packet_fallback(monkeypatch):
    observed = {}

    async def fake_load(db, *, run_id, user_id):
        return object()

    def fake_evaluate(facts):
        return workbench.DecisionTickResult(
            packet_version="main_run_chain_phase1",
            status="blocked",
            action="generate_videos",
            stage_id="generate_videos",
            selected_lane="c_lane_production",
            dispatchable=False,
            allowed=False,
            reason="selected_image missing",
            missing=["selected_image"],
            fallback_action="generate_keyframes",
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
                "mission_id": "run-1:generate_videos",
                "lane": "c_lane_production",
                "action": "generate_videos",
                "write_scope": ["tasks"],
                "idempotency_key": "run-1:generate_videos",
            },
        )

    async def fake_dispatch(db, *, packet, context, handlers):
        observed["packet"] = packet
        return {"decision_packet": packet.as_dict()}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "evaluate_decision_tick", fake_evaluate)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="plan_visual_assets",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_keyframe_count": 4, "workspace_shot_count": 8}},
        name="project-1",
        run_id="run-1",
        run_mode="step",
        result={},
        image_unit_price=1,
        video_unit_price=1,
    )

    assert observed["packet"].action == "generate_keyframes"
    assert result["decision_packet"]["action"] == "generate_keyframes"


@pytest.mark.asyncio
async def test_dispatch_production_action_uses_blocked_same_action_fallback(monkeypatch):
    observed = {}

    async def fake_load(db, *, run_id, user_id):
        return object()

    def fake_evaluate(facts):
        return workbench.DecisionTickResult(
            packet_version="main_run_chain_phase1",
            status="blocked",
            action="generate_videos",
            stage_id="generate_videos",
            selected_lane="c_lane_production",
            dispatchable=False,
            allowed=False,
            reason="image_review_blockers",
            missing=["image_review_blockers"],
            fallback_action="generate_keyframes",
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
                "mission_id": "run-1:generate_videos",
                "lane": "c_lane_production",
                "action": "generate_videos",
                "write_scope": ["tasks"],
                "idempotency_key": "run-1:generate_videos",
            },
        )

    async def fake_dispatch(db, *, packet, context, handlers):
        observed["packet"] = packet
        return {"decision_packet": packet.as_dict()}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "evaluate_decision_tick", fake_evaluate)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="generate_videos",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_keyframe_count": 1, "workspace_shot_count": 1}},
        name="project-1",
        run_id="run-1",
        run_mode="step",
        result={},
        image_unit_price=1,
        video_unit_price=1,
    )

    assert observed["packet"].action == "generate_keyframes"
    assert result["decision_packet"]["action"] == "generate_keyframes"


@pytest.mark.asyncio
async def test_dispatch_production_action_preserves_manual_visual_asset_request(monkeypatch):
    observed = {}

    async def fake_load(db, *, run_id, user_id):
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
            reason="canonical keyframe recommendation",
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
        observed["packet"] = packet
        return {"decision_packet": packet.as_dict()}

    monkeypatch.setattr(workbench, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(workbench, "evaluate_decision_tick", fake_evaluate)
    monkeypatch.setattr(workbench, "dispatch_authoritative_packet", fake_dispatch)

    result = await workbench._dispatch_production_action(
        object(),
        action="plan_visual_assets",
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={"signals": {"operational_pending_keyframe_count": 4, "workspace_shot_count": 8}},
        name="project-1",
        run_id="run-1",
        run_mode="step",
        result={},
        image_unit_price=1,
        video_unit_price=1,
        semantic_control={
            "human_routing": {
                "routing_source": "manual_selector",
                "explicit_action": "plan_visual_assets",
            }
        },
    )

    assert observed["packet"].action == "plan_visual_assets"
    assert result["decision_packet"]["action"] == "plan_visual_assets"


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


def test_normalize_continue_shot_indices_rejects_invalid_payload():
    with pytest.raises(workbench.HTTPException) as exc:
        workbench._normalize_continue_shot_indices("3")

    assert exc.value.status_code == 400
    assert exc.value.detail == "shot_indices must be a list"


def test_generate_video_requires_approved_director_protocol():
    with pytest.raises(workbench.HTTPException) as exc:
        workbench._guard_director_protocol_next_step(
            "generate_videos",
            {
                "approval_status": "draft",
                "allowed_next_step": False,
                "task_type": "reference_image",
            },
        )

    assert exc.value.status_code == 400
    assert "director input protocol" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_continue_generate_batch_filters_requested_shot_indices(monkeypatch):
    sent = []
    db = _FakeGenerateBatchDb([
        _shot_row(1, selected_image=""),
        _shot_row(2, selected_image="https://cdn.test/2.png"),
        _shot_row(3, selected_image=""),
    ])
    _patch_generate_batch_dependencies(monkeypatch, sent)

    result = await workbench._continue_generate_batch(
        db,
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={},
        run_id="11111111-1111-1111-1111-111111111111",
        media_type="keyframe",
        shot_indices=[3],
    )

    assert sent == [3]
    assert result["status"] == "queued"
    assert result["task_ids"] == result["child_task_ids"]
    assert result["task_id"] == result["child_task_ids"][0]
    assert result["queued_count"] == 1


@pytest.mark.asyncio
async def test_continue_generate_batch_without_shot_indices_keeps_batch_targets(monkeypatch):
    sent = []
    db = _FakeGenerateBatchDb([
        _shot_row(1, selected_image=""),
        _shot_row(2, selected_image="https://cdn.test/2.png"),
        _shot_row(3, selected_image=""),
    ])
    _patch_generate_batch_dependencies(monkeypatch, sent)

    result = await workbench._continue_generate_batch(
        db,
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={},
        run_id="11111111-1111-1111-1111-111111111111",
        media_type="keyframe",
    )

    assert sent == [1, 3]
    assert result["queued_count"] == 2


@pytest.mark.asyncio
async def test_continue_generate_video_uses_selected_image_override(monkeypatch):
    payloads = []
    db = _FakeGenerateBatchDb([
        _shot_row(2, selected_image="https://cdn.test/old.png"),
    ])
    _patch_generate_batch_dependencies(monkeypatch, [])
    monkeypatch.setattr(
        workbench.celery_app,
        "send_task",
        lambda _name, args=None, **_kwargs: payloads.append((args or [None, None, {}])[2]),
    )

    result = await workbench._continue_generate_batch(
        db,
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={},
        run_id="11111111-1111-1111-1111-111111111111",
        media_type="video",
        provider="seedance",
        shot_indices=[2],
        selected_image="https://cdn.test/new.png",
    )

    selected_updates = [
        params
        for statement, params in db.executed
        if "SET selected_image = :selected_image" in statement
    ]
    assert result["queued_count"] == 1
    assert payloads[0]["image_url"] == "https://cdn.test/new.png"
    assert selected_updates[0]["selected_image"] == "https://cdn.test/new.png"


@pytest.mark.asyncio
async def test_continue_generate_ltx23_video_omits_reference_images(monkeypatch):
    payloads = []
    db = _FakeGenerateBatchDb([
        _shot_row(2, selected_image="https://cdn.test/keyframe.png"),
    ])
    _patch_generate_batch_dependencies(monkeypatch, [])
    monkeypatch.setattr(
        workbench.celery_app,
        "send_task",
        lambda _name, args=None, **_kwargs: payloads.append((args or [None, None, {}])[2]),
    )

    result = await workbench._continue_generate_batch(
        db,
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={},
        run_id="11111111-1111-1111-1111-111111111111",
        media_type="video",
        provider="ltx2.3",
        shot_indices=[2],
    )

    assert result["queued_count"] == 1
    assert "image_url" not in payloads[0]
    assert "ref_images" not in payloads[0]


@pytest.mark.asyncio
async def test_continue_generate_video_resolves_artifact_image_override(monkeypatch):
    payloads = []
    db = _FakeGenerateBatchDb([
        _shot_row(2, selected_image="https://cdn.test/old.png"),
    ], artifact_uri="https://cdn.test/artifact.png")
    _patch_generate_batch_dependencies(monkeypatch, [])
    monkeypatch.setattr(
        workbench.celery_app,
        "send_task",
        lambda _name, args=None, **_kwargs: payloads.append((args or [None, None, {}])[2]),
    )

    result = await workbench._continue_generate_batch(
        db,
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        before={},
        run_id="11111111-1111-1111-1111-111111111111",
        media_type="video",
        provider="seedance",
        shot_indices=[2],
        artifact_id="11111111-1111-1111-1111-111111111111",
    )

    assert result["queued_count"] == 1
    assert payloads[0]["image_url"] == "https://cdn.test/artifact.png"


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


def test_keyframe_generation_targets_review_failed_selected_images_without_repair_request():
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
                    "review": {"status": "approved"},
                }
            ],
        },
    ]

    targets = _keyframe_generation_targets(rows)

    assert [row["shot_index"] for row in targets] == [1]
    assert targets[0]["regeneration"]["reason"] == "image_review_blockers"
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
