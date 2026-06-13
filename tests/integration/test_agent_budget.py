"""
P9-QA-1: Agent 预算拦截集成测试。

覆盖路径：
1. 创建 run 带 allowed_max_credits=10
2. 派发一个需要 80 积分的视频任务（video_gen_5s = 10 积分/个，8 个 = 80）
3. 验证被 run budget 拦截（ensure_run_budget 返回 False）
4. 验证 agent_runs.status = 'blocked'
5. 验证 agent_events 有 risk 事件（event_type='risk', phase='cost_guard'）

注意：
- ensure_run_budget 只在 allowed_max_credits > 0 时生效
- 直接调用 service 层函数，不走 HTTP 路由（预算拦截是内部逻辑）
- 也测试通过 brain/continue 路由触发预算拦截的场景
"""
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services.auth import hash_password, create_access_token
from app.services.agent_runtime import (
    create_agent_run,
    ensure_run_budget,
    publish_agent_event,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ─── fixtures ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def budget_user():
    """创建有 500 积分的 pro 用户，提交到 DB，测试后清理。"""
    username = f"budget_test_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            result = await s.execute(
                text("""
                    INSERT INTO users (username, email, password_hash, tier, status)
                    VALUES (:u, :e, :p, 'pro', 'active')
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
    yield {"id": user_id, "auth_header": f"Bearer {token}"}

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM agent_events WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM agent_steps WHERE run_id IN (SELECT id FROM agent_runs WHERE user_id = :uid)"), {"uid": user_id})
            await s.execute(text("DELETE FROM agent_runs WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM tasks WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM credit_transactions WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM credit_accounts WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM shot_rows WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM projects WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})


@pytest_asyncio.fixture
async def budget_project(budget_user, client):
    """创建项目并插入 8 条 shot_rows（无 selected_image，触发 8 个 image_gen 任务）。"""
    resp = await client.post(
        "/api/projects",
        json={"name": "budget_test_project"},
        headers={"Authorization": budget_user["auth_header"]},
    )
    assert resp.status_code == 200
    project_id = resp.json()["project_id"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            for i in range(8):
                await s.execute(
                    text("""
                        INSERT INTO shot_rows (project_id, user_id, shot_index, prompt, duration, status)
                        VALUES (:pid, :uid, :idx, :prompt, 5.0, 'pending')
                    """),
                    {
                        "pid": project_id,
                        "uid": budget_user["id"],
                        "idx": i,
                        "prompt": f"Shot {i}: epic battle scene",
                    },
                )
    return project_id


@pytest_asyncio.fixture
async def budget_rate_limit():
    """插入 pro tier 限流配置。"""
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
async def video_gen_pricing():
    """确保 video_gen_5s 定价存在（10 积分）。"""
    async with AsyncSessionLocal() as s:
        existing = (await s.execute(
            text("SELECT credits_cost FROM credit_pricing WHERE operation = 'video_gen_5s'"),
        )).first()

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("""
                    INSERT INTO credit_pricing (operation, credits_cost, active)
                    VALUES ('video_gen_5s', 10, TRUE)
                    ON CONFLICT (operation) DO UPDATE SET credits_cost = 10, active = TRUE
                """),
            )
    yield
    if existing is None:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(
                    text("DELETE FROM credit_pricing WHERE operation = 'video_gen_5s'"),
                )


# ─── 测试 1：ensure_run_budget 直接拦截超额请求 ──────────────────────────────────

async def test_ensure_run_budget_blocks_when_exceeded():
    """
    allowed_max_credits=10，next_cost=80 → ensure_run_budget 返回 False。
    """
    project_id = f"budget_test_{uuid.uuid4().hex[:8]}"
    user_id = 999999  # 不存在的用户，但 ensure_run_budget 只查 agent_runs

    async with AsyncSessionLocal() as s:
        async with s.begin():
            run_id = await create_agent_run(
                s,
                project_id=project_id,
                user_id=user_id,
                goal="test budget block",
                mode="step",
                allowed_max_credits=10,
            )

        # 在同一事务内检查预算（需要 FOR UPDATE，所以用新事务）
        async with s.begin():
            allowed = await ensure_run_budget(
                s,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                next_cost=80,
                label="8 video tasks × 10 credits",
            )

    assert allowed is False, "预算应被拦截（next_cost=80 > allowed=10）"

    # 验证 agent_runs.status = 'blocked'
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            text("SELECT status FROM agent_runs WHERE id = CAST(:rid AS UUID)"),
            {"rid": run_id},
        )).fetchone()

    assert row is not None
    assert row.status == "blocked", f"期望 status=blocked，实际={row.status}"

    # 清理
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM agent_events WHERE run_id = CAST(:rid AS UUID)"), {"rid": run_id})
            await s.execute(text("DELETE FROM agent_runs WHERE id = CAST(:rid AS UUID)"), {"rid": run_id})


async def test_ensure_run_budget_allows_when_sufficient():
    """
    allowed_max_credits=100，next_cost=10 → ensure_run_budget 返回 True。
    """
    project_id = f"budget_ok_{uuid.uuid4().hex[:8]}"
    user_id = 999998

    async with AsyncSessionLocal() as s:
        async with s.begin():
            run_id = await create_agent_run(
                s,
                project_id=project_id,
                user_id=user_id,
                goal="test budget ok",
                mode="step",
                allowed_max_credits=100,
            )

        async with s.begin():
            allowed = await ensure_run_budget(
                s,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                next_cost=10,
                label="1 image task × 10 credits",
            )

    assert allowed is True, "预算充足时应通过"

    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            text("SELECT status FROM agent_runs WHERE id = CAST(:rid AS UUID)"),
            {"rid": run_id},
        )).fetchone()
    assert row.status != "blocked"

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM agent_events WHERE run_id = CAST(:rid AS UUID)"), {"rid": run_id})
            await s.execute(text("DELETE FROM agent_runs WHERE id = CAST(:rid AS UUID)"), {"rid": run_id})


async def test_ensure_run_budget_no_limit_when_allowed_zero():
    """
    allowed_max_credits=0 → 不限制，ensure_run_budget 返回 True。
    """
    project_id = f"budget_zero_{uuid.uuid4().hex[:8]}"
    user_id = 999997

    async with AsyncSessionLocal() as s:
        async with s.begin():
            run_id = await create_agent_run(
                s,
                project_id=project_id,
                user_id=user_id,
                goal="test no budget limit",
                mode="step",
                allowed_max_credits=0,
            )

        async with s.begin():
            allowed = await ensure_run_budget(
                s,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                next_cost=9999,
                label="huge cost",
            )

    assert allowed is True, "allowed_max_credits=0 时不应限制"

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM agent_events WHERE run_id = CAST(:rid AS UUID)"), {"rid": run_id})
            await s.execute(text("DELETE FROM agent_runs WHERE id = CAST(:rid AS UUID)"), {"rid": run_id})


# ─── 测试 2：预算拦截后 agent_events 有 risk 事件 ────────────────────────────────

async def test_budget_block_emits_risk_event():
    """
    ensure_run_budget 拦截后，agent_events 表有 event_type='risk', phase='cost_guard'。
    """
    project_id = f"budget_risk_{uuid.uuid4().hex[:8]}"
    user_id = 999996

    async with AsyncSessionLocal() as s:
        async with s.begin():
            run_id = await create_agent_run(
                s,
                project_id=project_id,
                user_id=user_id,
                goal="test risk event",
                mode="step",
                allowed_max_credits=5,
            )

        async with s.begin():
            await ensure_run_budget(
                s,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                next_cost=80,
                label="8 video tasks",
            )

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            text("""
                SELECT event_type, phase FROM agent_events
                WHERE run_id = CAST(:rid AS UUID)
                ORDER BY created_at ASC
            """),
            {"rid": run_id},
        )).fetchall()

    event_types = [(r.event_type, r.phase) for r in rows]
    assert any(et == "risk" and ph == "cost_guard" for et, ph in event_types), (
        f"缺少 risk/cost_guard 事件，实际: {event_types}"
    )

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM agent_events WHERE run_id = CAST(:rid AS UUID)"), {"rid": run_id})
            await s.execute(text("DELETE FROM agent_runs WHERE id = CAST(:rid AS UUID)"), {"rid": run_id})


# ─── 测试 3：通过 brain/continue 路由触发预算拦截 ────────────────────────────────

async def test_brain_continue_budget_blocked_via_route(
    client, budget_user, budget_project, budget_rate_limit
):
    """
    POST brain/continue 时传入 allowed_max_credits=1（远小于 image_gen 所需），
    验证请求被拦截（400 或响应中 run 状态为 blocked）。

    注意：_continue_generate_keyframes 中 ensure_run_budget 拦截后抛 HTTPException(400)。
    """
    with patch("app.routes.workbench.celery_app.send_task"):
        resp = await client.post(
            f"/api/projects/{budget_project}/brain/continue",
            json={
                "action": "generate_keyframes",
                "allowed_max_credits": 1,  # 远小于 image_gen 所需
            },
            headers={"Authorization": budget_user["auth_header"]},
        )

    # 预算拦截后路由抛 HTTPException(400)
    assert resp.status_code == 400, (
        f"期望 400（预算拦截），实际 {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "budget" in str(detail).lower() or "blocked" in str(detail).lower(), (
        f"错误信息应包含 budget/blocked，实际: {detail}"
    )


# ─── 测试 4：预算拦截后 agent_runs.status = blocked ──────────────────────────────

async def test_brain_continue_budget_blocked_run_status(
    client, budget_user, budget_project, budget_rate_limit
):
    """
    预算拦截后，agent_runs 表中对应 run 的 status 应为 'blocked'。
    """
    with patch("app.routes.workbench.celery_app.send_task"):
        resp = await client.post(
            f"/api/projects/{budget_project}/brain/continue",
            json={
                "action": "generate_keyframes",
                "allowed_max_credits": 1,
            },
            headers={"Authorization": budget_user["auth_header"]},
        )

    # 无论路由返回什么，检查 DB 中最新的 run
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            text("""
                SELECT status FROM agent_runs
                WHERE project_id = :pid AND user_id = :uid
                ORDER BY started_at DESC
                LIMIT 1
            """),
            {"pid": budget_project, "uid": budget_user["id"]},
        )).fetchone()

    assert row is not None, "agent_runs 表中未找到记录"
    assert row.status == "blocked", f"期望 status=blocked，实际={row.status}"
