from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from lib.project_fixture import AsyncSessionLocal


async def wait_task_result(task_id: str, *, attempts: int = 90, interval: float = 1.0) -> dict[str, Any]:
    for _ in range(attempts):
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    text("SELECT status, result, error_message FROM tasks WHERE task_id = CAST(:task_id AS UUID)"),
                    {"task_id": task_id},
                )
            ).fetchone()
        if row and row.status == "done" and row.result:
            return dict(row.result)
        if row and row.status in {"failed", "dead_letter"}:
            raise AssertionError(f"task failed: {row.error_message}")
        await asyncio.sleep(interval)
    raise AssertionError(f"task timeout: {task_id}")

