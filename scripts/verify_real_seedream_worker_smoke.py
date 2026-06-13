from __future__ import annotations

import asyncio
import json

import httpx
from sqlalchemy import text

from lib.assertions import require
from lib.project_fixture import AsyncSessionLocal, test_project
from lib.tasks import wait_task_result


BASE_URL = "http://localhost:8000"


async def _insert_one_shot(project_id: str, user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO shot_rows (project_id, user_id, shot_index, prompt, duration, status)
                    VALUES (:project_id, :user_id, 1, :prompt, 4, 'pending')
                    ON CONFLICT (project_id, shot_index)
                    DO UPDATE SET prompt = EXCLUDED.prompt, duration = EXCLUDED.duration, status = EXCLUDED.status, updated_at = NOW()
                    """
                ),
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "prompt": (
                        "Cinematic product keyframe, a premium gold bracelet on black velvet, "
                        "soft side light, shallow depth of field, elegant short-drama commercial style."
                    ),
                },
            )


async def _read_result(project_id: str, user_id: int, run_id: str, task_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT selected_image FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id AND shot_index = 1) AS selected_image,
                      (SELECT status FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id AND shot_index = 1) AS shot_status,
                      (SELECT COUNT(*) FROM agent_events WHERE run_id = CAST(:run_id AS UUID)) AS events,
                      (
                        SELECT COUNT(*)
                        FROM agent_events
                        WHERE run_id = CAST(:run_id AS UUID)
                          AND meta->'agent_event'->>'actor' = 'seedream'
                      ) AS seedream_events,
                      (SELECT status FROM tasks WHERE task_id = CAST(:task_id AS UUID)) AS task_status
                    """
                ),
                {"project_id": project_id, "user_id": user_id, "run_id": run_id, "task_id": task_id},
            )
        ).mappings().first()
    return dict(row or {})


async def main() -> None:
    async with test_project("Real Seedream Worker Smoke", prefix="real-seedream", balance=2000) as ctx:
        await _insert_one_shot(ctx.project_id, ctx.user_id)
        with httpx.Client(base_url=BASE_URL, headers=ctx.headers, timeout=60.0) as client:
            client.get("/health").raise_for_status()
            response = client.post(
                f"/api/projects/{ctx.project_id}/brain/continue",
                json={
                    "mode": "step",
                    "action": "generate_keyframes",
                    "allowed_max_credits": 2000,
                    "instruction": "只为第一个镜头生成一张真实 Seedream 关键帧。",
                },
            )
            response.raise_for_status()
            payload = response.json()
            require(payload.get("queued_count") == 1, "expected exactly one image task", payload)
            task_id = payload["child_task_ids"][0]
            run_id = payload["run_id"]

            task_result = await wait_task_result(task_id, attempts=180, interval=2.0)
            result = await _read_result(ctx.project_id, ctx.user_id, run_id, task_id)
            require(result.get("task_status") == "done", "task not done", result)
            require(result.get("shot_status") == "image_done", "shot row was not written back", result)
            require(str(result.get("selected_image") or "").strip(), "selected_image missing", result)
            require(int(result.get("seedream_events") or 0) >= 2, "missing seedream agent events", result)

        print(
            json.dumps(
                {
                    "ok": True,
                    "project_id": ctx.project_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "selected_image": result.get("selected_image"),
                    "event_count": int(result.get("events") or 0),
                    "seedream_event_count": int(result.get("seedream_events") or 0),
                    "task_result_keys": sorted(task_result.keys()),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
