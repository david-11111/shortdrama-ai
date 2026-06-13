"""
P9-QA-1: Agent 事件流集成测试。

覆盖路径：
1. POST /api/projects/{project_id}/brain/continue (action=generate_keyframes)
   - agent_runs 表有记录，run_id 在响应中
   - agent_events 表有 decision + tool_call 事件
   - tasks 表中派发的任务 payload 包含 run_id
2. image_gen 任务完成后（模拟 writeback），agent_events 有 tool_result + writeback

注意：
- _continue_generate_keyframes 需要 shot_rows 有 prompt 且无 selected_image
- 需要 rate_limit_config + credit_pricing 数据
- celery_app.send_task 全部 mock，不真实派发
"""
import json
import os
import uuid
from unittest.mock import patch

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services.auth import hash_password, create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ─── fixtures ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def cleanup_agent_event_test_records_after_client_teardown():
    yield
    await cleanup_agent_event_test_records()


@pytest_asyncio.fixture
async def agent_user():
    """创建有 500 积分的 pro 用户，提交到 DB，测试后清理。"""
    username = f"agent_test_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            result = await s.execute(
                text("""
                    INSERT INTO users (email, password_hash, display_name, tier, status)
                    VALUES (:e, :p, :u, 'pro', 'active')
                    RETURNING id
                """),
                {"u": username, "e": f"{username}@qa.test", "p": hash_password("x")},
            )
            user_id = result.scalar()
            await s.execute(
                text("INSERT INTO credit_accounts (user_id, balance) VALUES (:uid, 500)"),
                {"uid": user_id},
            )

    token = create_access_token({"sub": str(user_id)})
    yield {
        "id": user_id,
        "auth_header": f"Bearer {token}",
    }

    # Prefix-based cleanup runs from the autouse fixture after client teardown.


async def cleanup_agent_event_test_records() -> None:
    conn = await asyncpg.connect(_asyncpg_test_database_url())
    try:
        async with conn.transaction():
            users = await conn.fetch("SELECT id FROM users WHERE email LIKE 'agent_test_%@qa.test'")
            for user in users:
                user_id = int(user["id"])
                run_ids = [
                    str(row["id"])
                    for row in await conn.fetch("SELECT id::text AS id FROM agent_runs WHERE user_id = $1", user_id)
                ]
                await conn.execute("DELETE FROM agent_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM agent_artifacts WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM agent_interrupts WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM video_production_runs WHERE user_id = $1", user_id)
                for run_id in run_ids:
                    await conn.execute("DELETE FROM agent_steps WHERE run_id = $1::uuid", run_id)
                await conn.execute("DELETE FROM tasks WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM shot_rows WHERE user_id = $1", user_id)
                for run_id in run_ids:
                    await conn.execute("DELETE FROM agent_runs WHERE id = $1::uuid", run_id)
                await conn.execute("DELETE FROM credit_transactions WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM credit_accounts WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM projects WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    finally:
        await conn.close()


def _asyncpg_test_database_url() -> str:
    url = os.environ["TEST_DATABASE_URL"]
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest_asyncio.fixture
async def agent_project(agent_user, client):
    """创建项目并插入 2 条有 prompt 的 shot_rows（无 selected_image）。"""
    resp = await client.post(
        "/api/projects",
        json={"name": "agent_test_project"},
        headers={"Authorization": agent_user["auth_header"]},
    )
    assert resp.status_code == 200
    project_id = resp.json()["project_id"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            for i in range(2):
                await s.execute(
                    text("""
                        INSERT INTO shot_rows (project_id, user_id, shot_index, prompt, duration, status)
                        VALUES (:pid, :uid, :idx, :prompt, 5.0, 'pending')
                    """),
                    {
                        "pid": project_id,
                        "uid": agent_user["id"],
                        "idx": i,
                        "prompt": f"Shot {i}: a dramatic scene in the rain",
                    },
                )

    return project_id


@pytest_asyncio.fixture
async def agent_rate_limit(agent_user):
    """插入 pro tier 限流配置，测试后清理。"""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            for resource, window, max_count in [
                ("image_gen", 3600, 100),
                ("concurrent_tasks", 0, 10),
            ]:
                await s.execute(
                    text("""
                        INSERT INTO rate_limit_config (tier, resource, window_seconds, max_count)
                        VALUES ('pro', :resource, :window, :max_count)
                        ON CONFLICT (tier, resource) DO UPDATE
                        SET window_seconds = EXCLUDED.window_seconds, max_count = EXCLUDED.max_count
                    """),
                    {"resource": resource, "window": window, "max_count": max_count},
                )
    yield


@pytest_asyncio.fixture
async def image_gen_pricing():
    """确保 image_gen 定价存在，测试后恢复。"""
    async with AsyncSessionLocal() as s:
        existing = (await s.execute(
            text("SELECT credits_cost FROM credit_pricing WHERE operation = 'image_gen'"),
        )).first()

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("""
                    INSERT INTO credit_pricing (operation, credits_cost, active)
                    VALUES ('image_gen', 2, TRUE)
                    ON CONFLICT (operation) DO UPDATE SET credits_cost = 2, active = TRUE
                """),
            )
    yield
    if existing is None:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(
                    text("DELETE FROM credit_pricing WHERE operation = 'image_gen'"),
                )


# ─── 测试 1：brain/continue(generate_keyframes) 写入 agent_runs ──────────────────

async def test_brain_continue_creates_agent_run(
    client, agent_user, agent_project, agent_rate_limit, image_gen_pricing
):
    """POST brain/continue 后 agent_runs 表有记录，响应包含 run_id。"""
    with patch("app.routes.workbench.celery_app.send_task"):
        resp = await client.post(
            f"/api/projects/{agent_project}/brain/continue",
            json={"action": "generate_keyframes"},
            headers={"Authorization": agent_user["auth_header"]},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "run_id" in data
    run_id = data["run_id"]
    assert run_id

    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            text("SELECT status, project_id, user_id FROM agent_runs WHERE id = CAST(:rid AS UUID)"),
            {"rid": run_id},
        )).fetchone()

    assert row is not None, "agent_runs 表中未找到 run 记录"
    assert str(row.project_id) == agent_project
    assert int(row.user_id) == agent_user["id"]


# ─── 测试 2：agent_events 有 decision + tool_call 事件 ───────────────────────────

async def test_brain_continue_emits_decision_and_tool_call_events(
    client, agent_user, agent_project, agent_rate_limit, image_gen_pricing
):
    """brain/continue 后 agent_events 表有 decision 和 tool_call 两种事件。"""
    with patch("app.routes.workbench.celery_app.send_task"):
        resp = await client.post(
            f"/api/projects/{agent_project}/brain/continue",
            json={"action": "generate_keyframes"},
            headers={"Authorization": agent_user["auth_header"]},
        )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            text("""
                SELECT event_type FROM agent_events
                WHERE run_id = CAST(:rid AS UUID)
                ORDER BY created_at ASC
            """),
            {"rid": run_id},
        )).fetchall()

    event_types = {r.event_type for r in rows}
    assert "decision" in event_types, f"缺少 decision 事件，实际: {event_types}"
    assert "tool_call" in event_types, f"缺少 tool_call 事件，实际: {event_types}"


# ─── 测试 3：派发的 tasks.payload 包含 run_id ────────────────────────────────────

async def test_dispatched_tasks_payload_contains_run_id(
    client, agent_user, agent_project, agent_rate_limit, image_gen_pricing
):
    """brain/continue 派发的 tasks 记录中，payload 字段包含 run_id。"""
    with patch("app.routes.workbench.celery_app.send_task"):
        resp = await client.post(
            f"/api/projects/{agent_project}/brain/continue",
            json={"action": "generate_keyframes"},
            headers={"Authorization": agent_user["auth_header"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    run_id = data["run_id"]
    child_task_ids = data.get("child_task_ids", [])
    assert child_task_ids, "没有派发任何子任务"

    async with AsyncSessionLocal() as s:
        for task_id in child_task_ids:
            row = (await s.execute(
                text("SELECT payload, run_id FROM tasks WHERE task_id = :tid"),
                {"tid": task_id},
            )).fetchone()
            assert row is not None, f"tasks 表中未找到 task_id={task_id}"

            # payload 是合法 JSON
            payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
            assert payload.get("run_id") == run_id, (
                f"task {task_id} 的 payload.run_id={payload.get('run_id')} != run_id={run_id}"
            )

            # tasks.run_id 外键也正确
            assert str(row.run_id) == run_id, (
                f"tasks.run_id={row.run_id} != run_id={run_id}"
            )


# ─── 测试 4：模拟 image_gen 完成后 writeback 写入 agent_events ───────────────────

async def test_image_gen_writeback_emits_tool_result_event(
    client, agent_user, agent_project, agent_rate_limit, image_gen_pricing
):
    """
    模拟 image_gen 任务完成后的 writeback 路径：
    直接调用 publish_agent_event 写入 tool_result 事件，
    验证 agent_events 表中有 tool_result 记录。
    """
    # 先创建一个 run
    with patch("app.routes.workbench.celery_app.send_task"):
        resp = await client.post(
            f"/api/projects/{agent_project}/brain/continue",
            json={"action": "generate_keyframes"},
            headers={"Authorization": agent_user["auth_header"]},
        )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    child_task_ids = resp.json().get("child_task_ids", [])
    assert child_task_ids

    task_id = child_task_ids[0]

    # 模拟 worker 完成后调用 publish_agent_event 写入 tool_result
    from app.services.agent_runtime import publish_agent_event
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await publish_agent_event(
                s,
                run_id=run_id,
                project_id=agent_project,
                user_id=agent_user["id"],
                source="queue",
                event_type="tool_result",
                phase="writing_back",
                title="Seedream 关键帧生成完成",
                detail=f"task_id={task_id}；image_url=https://cdn.example.com/test.jpg",
                status="done",
                progress=100,
                task_id=task_id,
                meta={"task_id": task_id, "image_url": "https://cdn.example.com/test.jpg"},
            )

    # 模拟 writeback 事件
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await publish_agent_event(
                s,
                run_id=run_id,
                project_id=agent_project,
                user_id=agent_user["id"],
                source="queue",
                event_type="writeback",
                phase="writing_back",
                title="shot_rows 回写完成",
                detail=f"selected_image 已更新，task_id={task_id}",
                status="done",
                progress=100,
                task_id=task_id,
                meta={"task_id": task_id, "shot_index": 0},
            )

    # 验证 agent_events 有 tool_result + writeback
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            text("""
                SELECT event_type FROM agent_events
                WHERE run_id = CAST(:rid AS UUID)
                ORDER BY created_at ASC
            """),
            {"rid": run_id},
        )).fetchall()

    event_types = [r.event_type for r in rows]
    assert "tool_result" in event_types, f"缺少 tool_result 事件，实际: {event_types}"
    assert "writeback" in event_types, f"缺少 writeback 事件，实际: {event_types}"


# ─── 测试 5：GET agent-events 接口返回正确数据 ───────────────────────────────────

async def test_get_agent_events_returns_run_events(
    client, agent_user, agent_project, agent_rate_limit, image_gen_pricing
):
    """GET /api/projects/{project_id}/agent-events 返回该项目的事件列表。"""
    with patch("app.routes.workbench.celery_app.send_task"):
        await client.post(
            f"/api/projects/{agent_project}/brain/continue",
            json={"action": "generate_keyframes"},
            headers={"Authorization": agent_user["auth_header"]},
        )

    resp = await client.get(
        f"/api/projects/{agent_project}/agent-events",
        headers={"Authorization": agent_user["auth_header"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == agent_project
    assert len(data["items"]) > 0

    event_types = {item["event_type"] for item in data["items"]}
    assert "trace" in event_types or "decision" in event_types or "tool_call" in event_types


async def test_task_terminal_observer_writes_decision_tick_event(
    client, agent_user, agent_project, agent_rate_limit, image_gen_pricing
):
    """Terminal task hook should persist a decision_tick event for the owning run."""
    with patch("app.routes.workbench.celery_app.send_task"):
        resp = await client.post(
            f"/api/projects/{agent_project}/brain/continue",
            json={"action": "generate_keyframes"},
            headers={"Authorization": agent_user["auth_header"]},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    run_id = data["run_id"]
    child_task_ids = data.get("child_task_ids", [])
    assert child_task_ids

    task_id = child_task_ids[0]
    result_payload = {"image_url": "https://cdn.example.com/generated-0.jpg"}

    from app.tasks import _shared

    await _shared._persist_and_publish(
        _shared._persist_complete(task_id, result=result_payload, celery_task_id=None),
        task_id,
        {"type": "task_complete", "task_id": task_id, "result": result_payload},
    )

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    """
                    SELECT status, meta
                    FROM agent_events
                    WHERE run_id = CAST(:rid AS UUID)
                      AND task_id = CAST(:tid AS UUID)
                      AND source = 'state_machine'
                      AND event_type = 'decision'
                      AND phase = 'decision_tick'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"rid": run_id, "tid": task_id},
            )
        ).fetchone()

    assert row is not None, "task terminal observer did not write decision_tick"
    meta = row.meta if isinstance(row.meta, dict) else json.loads(row.meta)
    packet = meta.get("decision_tick")
    assert isinstance(packet, dict), f"invalid decision packet: {meta}"
    assert row.status in {"wait", "execute", "recover", "blocked", "complete"}
    assert packet.get("packet_version") == "main_run_chain_phase1"
    assert packet.get("status") in {"wait", "execute", "recover", "blocked", "complete"}
    assert packet.get("action")
    assert "stage_id" in packet
    assert isinstance(packet.get("candidate_actions"), list)
