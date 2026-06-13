from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services.credits import credit_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refund one reserved credit transaction and cancel its queued orphan task.")
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--execute", action="store_true", help="Perform the refund and task cancellation. Default is dry-run.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    evidence: dict[str, object] = {
        "transaction_id": args.transaction_id,
        "task_id": args.task_id,
        "dry_run": not args.execute,
    }

    async with AsyncSessionLocal() as session:
        tx_row = (
            await session.execute(
                text(
                    """
                    SELECT transaction_id::text, user_id, amount, tx_type, description
                    FROM credit_transactions
                    WHERE transaction_id = CAST(:transaction_id AS UUID)
                    """
                ),
                {"transaction_id": args.transaction_id},
            )
        ).mappings().first()
        task_row = (
            await session.execute(
                text(
                    """
                    SELECT task_id::text, user_id, status, task_type, error_message
                    FROM tasks
                    WHERE task_id = CAST(:task_id AS UUID)
                    """
                ),
                {"task_id": args.task_id},
            )
        ).mappings().first()

    evidence["transaction"] = dict(tx_row) if tx_row else None
    evidence["task"] = dict(task_row) if task_row else None
    if not tx_row:
        raise RuntimeError(f"transaction not found: {args.transaction_id}")
    if not task_row:
        raise RuntimeError(f"task not found: {args.task_id}")
    if task_row["status"] != "queued":
        raise RuntimeError(f"task must be queued before cancellation, got {task_row['status']}")

    if not args.execute:
        print(json.dumps(evidence, ensure_ascii=False, default=str, indent=2))
        return

    await credit_service.refund(args.transaction_id)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = 'cancelled',
                        error_message = 'cancelled after parent run retry; reserved credits refunded',
                        updated_at = NOW()
                    WHERE task_id = CAST(:task_id AS UUID)
                      AND status = 'queued'
                    """
                ),
                {"task_id": args.task_id},
            )
            evidence["cancelled_tasks"] = int(result.rowcount or 0)
    print(json.dumps(evidence, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
