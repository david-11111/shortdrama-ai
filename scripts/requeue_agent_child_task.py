from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import text

from app.celery_app import celery_app
from app.db import AsyncSessionLocal


ROUTES = {
    "image_gen": ("app.tasks.image_tasks.generate_image_task", "image"),
    "video_gen": ("app.tasks.video_tasks.generate_video_task", "video"),
}


async def requeue(task_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT task_id::text AS task_id, task_type, status, user_id,
                       payload, credit_transaction_id::text AS credit_transaction_id,
                       priority
                FROM tasks
                WHERE task_id = CAST(:task_id AS UUID)
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
        row = result.mappings().first()
        if not row:
            raise SystemExit(f"task not found: {task_id}")
        if str(row["status"]) != "queued":
            raise SystemExit(f"task is not queued: {task_id} status={row['status']}")
        celery_task, queue = ROUTES.get(str(row["task_type"]) or "", ("", ""))
        if not celery_task:
            raise SystemExit(f"unsupported task_type: {row['task_type']}")
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        transaction_id = str(row["credit_transaction_id"] or payload.get("_credit_transaction_id") or "").strip() or None
        celery_app.send_task(
            celery_task,
            args=[str(row["task_id"]), str(row["user_id"]), payload],
            kwargs={"transaction_id": transaction_id},
            queue=queue,
            priority=int(row["priority"] or 5),
        )
        await db.execute(
            text(
                """
                UPDATE tasks
                SET updated_at = NOW(),
                    stage_text = COALESCE(NULLIF(stage_text, ''), 'Manually requeued')
                WHERE task_id = CAST(:task_id AS UUID)
                """
            ),
            {"task_id": task_id},
        )
        await db.commit()
        return {"task_id": str(row["task_id"]), "task_type": str(row["task_type"]), "queue": queue}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    print(asyncio.run(requeue(args.task_id)))


if __name__ == "__main__":
    main()
