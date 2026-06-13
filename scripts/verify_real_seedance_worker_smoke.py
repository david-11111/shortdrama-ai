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
                    INSERT INTO shot_rows (
                      project_id, user_id, shot_index, prompt, duration, status
                    )
                    VALUES (:project_id, :user_id, 1, :prompt, 5, 'pending')
                    ON CONFLICT (project_id, shot_index)
                    DO UPDATE SET
                      prompt = EXCLUDED.prompt,
                      duration = EXCLUDED.duration,
                      status = EXCLUDED.status,
                      selected_image = NULL,
                      selected_video = NULL,
                      updated_at = NOW()
                    """
                ),
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "prompt": (
                        "Slow cinematic push-in over a dramatic alpine ridge at sunrise, "
                        "soft clouds moving, premium short-drama establishing shot, stable camera."
                    ),
                },
            )


async def _read_keyframe(project_id: str, user_id: int, task_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT selected_image FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id AND shot_index = 1) AS selected_image,
                      (SELECT status FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id AND shot_index = 1) AS shot_status,
                      (SELECT status FROM tasks WHERE task_id = CAST(:task_id AS UUID)) AS task_status
                    """
                ),
                {"project_id": project_id, "user_id": user_id, "task_id": task_id},
            )
        ).mappings().first()
    return dict(row or {})


async def _read_result(project_id: str, user_id: int, run_id: str, task_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT selected_video FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id AND shot_index = 1) AS selected_video,
                      (SELECT status FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id AND shot_index = 1) AS shot_status,
                      (SELECT COUNT(*) FROM agent_events WHERE run_id = CAST(:run_id AS UUID)) AS events,
                      (
                        SELECT COUNT(*)
                        FROM agent_events
                        WHERE run_id = CAST(:run_id AS UUID)
                          AND meta->'agent_event'->>'actor' = 'seedance'
                      ) AS seedance_events,
                      (SELECT COUNT(*) FROM provider_usage_costs WHERE task_id = CAST(:task_id AS UUID)) AS usage_rows,
                      (SELECT status FROM tasks WHERE task_id = CAST(:task_id AS UUID)) AS task_status
                    """
                ),
                {"project_id": project_id, "user_id": user_id, "run_id": run_id, "task_id": task_id},
            )
        ).mappings().first()
    return dict(row or {})


async def main() -> None:
    async with test_project("Real Seedance Worker Smoke", prefix="real-seedance", balance=2000) as ctx:
        await _insert_one_shot(ctx.project_id, ctx.user_id)
        with httpx.Client(base_url=BASE_URL, headers=ctx.headers, timeout=60.0) as client:
            client.get("/health").raise_for_status()
            keyframe_response = client.post(
                f"/api/projects/{ctx.project_id}/brain/continue",
                json={
                    "mode": "step",
                    "action": "generate_keyframes",
                    "allowed_max_credits": 2000,
                    "instruction": "先为第一个镜头生成一张真实 Seedream 首帧。",
                },
            )
            keyframe_response.raise_for_status()
            keyframe_payload = keyframe_response.json()
            require(keyframe_payload.get("queued_count") == 1, "expected exactly one image task", keyframe_payload)
            keyframe_task_id = keyframe_payload["child_task_ids"][0]
            await wait_task_result(keyframe_task_id, attempts=180, interval=2.0)
            keyframe = await _read_keyframe(ctx.project_id, ctx.user_id, keyframe_task_id)
            require(keyframe.get("task_status") == "done", "keyframe task not done", keyframe)
            require(keyframe.get("shot_status") == "image_done", "keyframe was not written back", keyframe)
            require(str(keyframe.get("selected_image") or "").strip(), "selected_image missing before video", keyframe)

            response = client.post(
                f"/api/projects/{ctx.project_id}/brain/continue",
                json={
                    "mode": "step",
                    "action": "generate_videos",
                    "video_provider": "seedance",
                    "allowed_max_credits": 2000,
                    "instruction": "基于刚生成的首帧，只为第一个镜头生成一段真实 Seedance 5 秒视频。",
                },
            )
            response.raise_for_status()
            payload = response.json()
            require(payload.get("queued_count") == 1, "expected exactly one video task", payload)
            task_id = payload["child_task_ids"][0]
            run_id = payload["run_id"]

            task_result = await wait_task_result(task_id, attempts=420, interval=2.0)
            result = await _read_result(ctx.project_id, ctx.user_id, run_id, task_id)
            require(result.get("task_status") == "done", "task not done", result)
            require(result.get("shot_status") == "video_done", "shot row was not written back", result)
            require(str(result.get("selected_video") or "").strip(), "selected_video missing", result)
            require(int(result.get("seedance_events") or 0) >= 2, "missing seedance agent events", result)
            require(int(result.get("usage_rows") or 0) >= 1, "missing provider usage row", result)

        print(
            json.dumps(
                {
                    "ok": True,
                    "project_id": ctx.project_id,
                    "keyframe_task_id": keyframe_task_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "selected_image": keyframe.get("selected_image"),
                    "selected_video": result.get("selected_video"),
                    "event_count": int(result.get("events") or 0),
                    "seedance_event_count": int(result.get("seedance_events") or 0),
                    "task_result_keys": sorted(task_result.keys()),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
