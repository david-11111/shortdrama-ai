from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.celery_app import celery_app
from app.db import AsyncSessionLocal


async def main(task_id: str) -> None:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT user_id, payload, priority, credit_transaction_id
                    FROM tasks
                    WHERE task_id = CAST(:task_id AS UUID)
                      AND task_type = 'video_gen'
                    LIMIT 1
                    """
                ),
                {"task_id": task_id},
            )
        ).mappings().first()
        if not row:
            raise SystemExit(f"video task not found: {task_id}")

        celery_app.send_task(
            "app.tasks.video_tasks.generate_video_task",
            args=[task_id, str(row["user_id"]), dict(row["payload"])],
            kwargs={"transaction_id": str(row["credit_transaction_id"] or "")},
            queue="video",
            priority=int(row["priority"] or 5),
        )
        print(f"resent {task_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/requeue_video_task.py <task_id>")
    asyncio.run(main(sys.argv[1]))
