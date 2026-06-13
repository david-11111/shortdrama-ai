import os
import uuid

import pytest
import pytest_asyncio
import asyncpg
from sqlalchemy import text

from app import db as app_db
from app import redis_client as app_redis
from app.db import AsyncSessionLocal
from app.services.auth import create_access_token, hash_password
from app.services.agent_runtime import create_agent_run

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not available"),
]


@pytest_asyncio.fixture(autouse=True)
async def isolate_app_db_engine():
    await app_db.engine.dispose()
    await close_app_redis_connections()
    yield
    await close_app_redis_connections()
    await app_db.engine.dispose()
    await cleanup_main_chain_test_records()


async def close_app_redis_connections() -> None:
    try:
        await app_redis.redis_client.aclose(close_connection_pool=False)
    except AttributeError:
        await app_redis.redis_client.close(close_connection_pool=False)
    try:
        await app_redis.redis_pool.disconnect(inuse_connections=True)
    except TypeError:
        await app_redis.redis_pool.disconnect()


async def test_terminal_keyframe_task_dispatches_next_video_stage(monkeypatch):
    from app.services import main_chain_handlers
    from app.tasks import _shared

    observed = {"video_handler": False}
    user_id, project_id, run_id, task_id = await seed_agent_run_with_done_keyframe_and_pending_video()

    def fake_handlers(db, **kwargs):
        async def generate_videos():
            observed["video_handler"] = True
            return {"queued_count": 1, "run_id": kwargs["run_id"]}

        return {"generate_videos": generate_videos}

    monkeypatch.setattr(main_chain_handlers, "build_main_chain_handlers", fake_handlers)

    async def persisted():
        return None

    await _shared._persist_and_publish(
        persisted(),
        task_id,
        {"type": "task_complete", "task_id": task_id, "result": {"image_url": "https://cdn.example.com/keyframe.jpg"}},
    )

    assert observed["video_handler"] is True

    await cleanup_seeded_run(user_id=user_id, project_id=project_id, run_id=run_id)


async def test_entry_to_terminal_hook_dispatches_next_stage(client, monkeypatch):
    from app.routes import workbench
    from app.services import main_chain_handlers
    from app.tasks import _shared

    observed = {"video_handler": False}
    user_id, auth_header = await seed_api_user()

    def fake_handlers(db, **kwargs):
        async def generate_videos():
            observed["video_handler"] = True
            return {"queued_count": 1, "run_id": kwargs["run_id"]}

        return {"generate_videos": generate_videos}

    monkeypatch.setattr(main_chain_handlers, "build_main_chain_handlers", fake_handlers)
    monkeypatch.setattr(workbench.celery_app, "send_task", lambda *args, **kwargs: None)

    try:
        project_response = await client.post(
            "/api/projects",
            json={"name": "main-chain-entry"},
            headers={"Authorization": auth_header},
        )
        assert project_response.status_code == 200, project_response.text
        project_id = project_response.json()["project_id"]
        await seed_project_for_keyframe_entry(project_id=project_id, user_id=user_id)

        continue_response = await client.post(
            f"/api/projects/{project_id}/brain/continue",
            json={"action": "generate_keyframes", "mode": "autopilot"},
            headers={"Authorization": auth_header},
        )
        assert continue_response.status_code == 200, continue_response.text
        payload = continue_response.json()
        run_id = payload["run_id"]
        child_task_ids = payload.get("child_task_ids") or []
        assert child_task_ids

        task_id = child_task_ids[0]
        result_payload = {"image_url": "https://cdn.example.com/generated-entry.jpg"}
        await _shared.update_shot_media(
            project_id,
            1,
            str(user_id),
            image_url=result_payload["image_url"],
            image_candidate={"url": result_payload["image_url"], "source": "integration_test"},
            status="image_done",
        )
        await _shared._persist_and_publish(
            _shared._persist_complete(task_id, result=result_payload, celery_task_id=None),
            task_id,
            {"type": "task_complete", "task_id": task_id, "result": result_payload},
        )

        assert observed["video_handler"] is True
        await assert_dispatch_gateway_event(run_id=run_id, user_id=user_id)
        await assert_agent_event_exists(
            run_id=run_id,
            user_id=user_id,
            source="main_chain",
            event_type="feedback",
        )
        await assert_agent_event_exists(
            run_id=run_id,
            user_id=user_id,
            source="decision_mailbox",
            event_type="decision_mailbox",
        )
        await assert_agent_event_exists(
            run_id=run_id,
            user_id=user_id,
            source="decision_mailbox",
            event_type="decision_mailbox",
            phase="pending",
        )
        await assert_agent_event_exists(
            run_id=run_id,
            user_id=user_id,
            source="decision_mailbox",
            event_type="decision_mailbox",
            phase="completed",
        )
    finally:
        # Prefix-based cleanup runs from the autouse fixture after client teardown.
        pass


async def seed_api_user() -> tuple[int, str]:
    suffix = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, display_name, tier, status)
                    VALUES (:email, :password_hash, :display_name, 'pro', 'active')
                    RETURNING id
                    """
                ),
                {
                    "email": f"main-chain-entry-{suffix}@test.local",
                    "password_hash": hash_password("main-chain-test"),
                    "display_name": f"main_chain_entry_{suffix}",
                },
            )
            user_id = int(result.scalar_one())
            await session.execute(
                text("INSERT INTO credit_accounts (user_id, balance) VALUES (:user_id, 500)"),
                {"user_id": user_id},
            )
    token = create_access_token({"sub": str(user_id)})
    return user_id, f"Bearer {token}"


async def seed_project_for_keyframe_entry(*, project_id: str, user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO shot_rows (project_id, user_id, shot_index, prompt, duration, status)
                    VALUES (:project_id, :user_id, 1, 'entry shot', 5.0, 'pending')
                    """
                ),
                {"project_id": project_id, "user_id": user_id},
            )
            for resource, window, max_count in [
                ("image_gen", 3600, 100),
                ("concurrent_tasks", 0, 10),
            ]:
                await session.execute(
                    text(
                        """
                        INSERT INTO rate_limit_config (tier, resource, window_seconds, max_count)
                        VALUES ('pro', :resource, :window, :max_count)
                        ON CONFLICT (tier, resource) DO UPDATE
                        SET window_seconds = EXCLUDED.window_seconds, max_count = EXCLUDED.max_count
                        """
                    ),
                    {"resource": resource, "window": window, "max_count": max_count},
                )
            await session.execute(
                text(
                    """
                    INSERT INTO credit_pricing (operation, credits_cost, active)
                    VALUES ('image_gen', 2, TRUE)
                    ON CONFLICT (operation) DO UPDATE SET credits_cost = 2, active = TRUE
                    """
                )
            )


async def assert_dispatch_gateway_event(*, run_id: str, user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT 1
                    FROM agent_events
                    WHERE run_id = CAST(:run_id AS UUID)
                      AND user_id = :user_id
                      AND source = 'dispatch_gateway'
                      AND phase = 'dispatch_gateway'
                    LIMIT 1
                    """
                ),
                {"run_id": run_id, "user_id": user_id},
            )
        ).first()
    assert row is not None


async def assert_agent_event_exists(
    *,
    run_id: str,
    user_id: int,
    source: str,
    event_type: str,
    phase: str | None = None,
) -> None:
    phase_filter = "AND phase = :phase" if phase else ""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    f"""
                    SELECT 1
                    FROM agent_events
                    WHERE run_id = CAST(:run_id AS UUID)
                      AND user_id = :user_id
                      AND source = :source
                      AND event_type = :event_type
                      {phase_filter}
                    LIMIT 1
                    """
                ),
                {
                    "run_id": run_id,
                    "user_id": user_id,
                    "source": source,
                    "event_type": event_type,
                    "phase": phase,
                },
            )
        ).first()
    assert row is not None


async def cleanup_seeded_user(*, user_id: int) -> None:
    conn = await asyncpg.connect(_asyncpg_test_database_url())
    try:
        async with conn.transaction():
            run_rows = await conn.fetch("SELECT id::text AS id FROM agent_runs WHERE user_id = $1", user_id)
            run_ids = [str(row["id"]) for row in run_rows]
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
            await conn.execute("DELETE FROM projects WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM credit_transactions WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM credit_accounts WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    finally:
        await conn.close()


def _asyncpg_test_database_url() -> str:
    url = os.environ["TEST_DATABASE_URL"]
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def cleanup_main_chain_test_records() -> None:
    conn = await asyncpg.connect(_asyncpg_test_database_url())
    try:
        async with conn.transaction():
            users = await conn.fetch(
                """
                SELECT id FROM users
                WHERE email LIKE 'main-chain-entry-%@test.local'
                   OR email LIKE 'main-chain-loop-%@test.local'
                """
            )
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
                await conn.execute("DELETE FROM projects WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM credit_transactions WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM credit_accounts WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    finally:
        await conn.close()


async def seed_agent_run_with_done_keyframe_and_pending_video() -> tuple[int, str, str, str]:
    suffix = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user_row = await session.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, display_name, tier, status)
                    VALUES (:email, 'x', 'main_chain_loop', 'pro', 'active')
                    RETURNING id
                    """
                ),
                {"email": f"main-chain-loop-{suffix}@test.local"},
            )
            user_id = int(user_row.scalar_one())
            project_id = f"main_chain_{suffix}"
            await session.execute(
                text(
                    """
                    INSERT INTO projects (project_id, user_id, name, status)
                    VALUES (:project_id, :user_id, 'main chain loop', 'active')
                    """
                ),
                {"project_id": project_id, "user_id": user_id},
            )
        run_id = await create_agent_run(
            session,
            project_id=project_id,
            user_id=user_id,
            trigger_type="test",
            goal="continue after keyframe",
            mode="autopilot",
        )
        await session.execute(
            text(
                """
                INSERT INTO shot_rows (
                    project_id, user_id, shot_index, prompt, duration, status, selected_image, selected_video
                )
                VALUES (:project_id, :user_id, 1, 'shot with keyframe', 5.0, 'image_done', :image, '')
                """
            ),
            {
                "project_id": project_id,
                "user_id": user_id,
                "image": "https://cdn.example.com/keyframe.jpg",
            },
        )
        task_row = await session.execute(
            text(
                """
                INSERT INTO tasks (user_id, project_id, run_id, task_type, status, priority, payload, credits_reserved)
                VALUES (:user_id, :project_id, CAST(:run_id AS UUID), 'image_gen', 'done', 3, CAST('{}' AS JSONB), 0)
                RETURNING task_id::text
                """
            ),
            {"user_id": user_id, "project_id": project_id, "run_id": run_id},
        )
        task_id = str(task_row.scalar_one())
        await session.commit()
        return user_id, project_id, run_id, task_id


async def cleanup_seeded_run(*, user_id: int, project_id: str, run_id: str) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM agent_events WHERE user_id = :user_id"), {"user_id": user_id})
            await session.execute(text("DELETE FROM agent_artifacts WHERE user_id = :user_id"), {"user_id": user_id})
            await session.execute(text("DELETE FROM agent_interrupts WHERE user_id = :user_id"), {"user_id": user_id})
            await session.execute(text("DELETE FROM video_production_runs WHERE user_id = :user_id"), {"user_id": user_id})
            await session.execute(text("DELETE FROM agent_steps WHERE run_id = CAST(:run_id AS UUID)"), {"run_id": run_id})
            await session.execute(text("DELETE FROM tasks WHERE user_id = :user_id"), {"user_id": user_id})
            await session.execute(text("DELETE FROM shot_rows WHERE user_id = :user_id"), {"user_id": user_id})
            await session.execute(text("DELETE FROM agent_runs WHERE id = CAST(:run_id AS UUID)"), {"run_id": run_id})
            await session.execute(text("DELETE FROM projects WHERE project_id = :project_id"), {"project_id": project_id})
            await session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
