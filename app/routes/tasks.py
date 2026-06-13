from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.schemas.tasks import TaskCancelResponse, TaskListResponse, TaskStatusResponse
from app.services.credits import credit_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """查询当前用户的任务列表（分页）"""
    offset = (page - 1) * page_size
    user_id = current_user["id"]

    where_clause = "WHERE user_id = :user_id"
    params: dict = {"limit": page_size, "offset": offset, "user_id": user_id}

    if status:
        where_clause += " AND status = :status"
        params["status"] = status

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM tasks {where_clause}"), params
    )
    total = count_result.scalar()

    result = await db.execute(
        text(f"""
            SELECT task_id, task_type, status, progress, stage_text,
                   result, error_message, created_at, started_at, completed_at
            FROM tasks {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.fetchall()

    tasks = [
        TaskStatusResponse(
            task_id=str(row.task_id),
            task_type=row.task_type,
            status=row.status,
            progress=row.progress,
            stage_text=row.stage_text,
            result=row.result,
            error_message=row.error_message,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )
        for row in rows
    ]

    return TaskListResponse(tasks=tasks, total=total, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """查询单个任务（只能查自己的）"""
    result = await db.execute(
        text("""
            SELECT task_id, task_type, status, progress, stage_text,
                   result, error_message, created_at, started_at, completed_at
            FROM tasks WHERE task_id = :tid AND user_id = :uid
        """),
        {"tid": task_id, "uid": current_user["id"]},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Task not found")

    return TaskStatusResponse(
        task_id=str(row.task_id),
        task_type=row.task_type,
        status=row.status,
        progress=row.progress,
        stage_text=row.stage_text,
        result=row.result,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """取消任务（只能取消自己的，仅 pending/queued 状态可取消）"""
    async with db.begin():
        result = await db.execute(
            text("""
                SELECT status, credits_reserved, credit_transaction_id, payload
                FROM tasks
                WHERE task_id = :tid AND user_id = :uid
                FOR UPDATE
            """),
            {"tid": task_id, "uid": current_user["id"]},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(404, "Task not found")

        if row.status not in ("pending", "queued"):
            raise HTTPException(400, f"Cannot cancel task in '{row.status}' status")

        payload = row.payload if isinstance(row.payload, dict) else {}
        if row.credits_reserved > 0:
            transaction_id = str(row.credit_transaction_id or payload.get("_credit_transaction_id") or "").strip()
            if transaction_id:
                await credit_service.refund(transaction_id)
            else:
                await db.execute(
                    text("""
                        UPDATE credit_accounts
                        SET balance = balance + :amount, updated_at = NOW()
                        WHERE user_id = :uid
                    """),
                    {"amount": row.credits_reserved, "uid": current_user["id"]},
                )
                await db.execute(
                    text("""
                        INSERT INTO credit_transactions
                            (user_id, amount, balance_after, tx_type, reference_id, description)
                        SELECT :uid, :amount, balance, 'refund', :ref, 'Task cancelled'
                        FROM credit_accounts WHERE user_id = :uid
                    """),
                    {"uid": current_user["id"], "amount": row.credits_reserved, "ref": task_id},
                )

        await db.execute(
            text("UPDATE tasks SET status = 'cancelled', updated_at = NOW() WHERE task_id = :tid"),
            {"tid": task_id},
        )

    return TaskCancelResponse(task_id=task_id, status="cancelled", message="Task cancelled")
