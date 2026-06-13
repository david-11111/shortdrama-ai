"""Webhook 配置路由 — 用户可配置任务完成回调"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookConfig(BaseModel):
    url: str
    events: list[str] = ["task.complete", "task.failed"]
    secret: str = ""


@router.get("")
async def list_webhooks(user=Depends(get_current_user)):
    """获取用户的 webhook 配置"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, url, events, active, created_at FROM webhooks WHERE user_id = :uid ORDER BY created_at DESC"),
            {"uid": user["id"]},
        )
        rows = result.mappings().fetchall()
    return {"webhooks": [dict(r) for r in rows]}


@router.post("")
async def create_webhook(config: WebhookConfig, user=Depends(get_current_user)):
    """创建 webhook"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO webhooks (user_id, url, events, secret, active)
                    VALUES (:uid, :url, :events, :secret, TRUE)
                """),
                {
                    "uid": user["id"],
                    "url": config.url,
                    "events": ",".join(config.events),
                    "secret": config.secret,
                },
            )
    return {"message": "Webhook created"}


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: int, user=Depends(get_current_user)):
    """删除 webhook"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                text("DELETE FROM webhooks WHERE id = :id AND user_id = :uid"),
                {"id": webhook_id, "uid": user["id"]},
            )
            if result.rowcount == 0:
                raise HTTPException(404, "Webhook not found")
    return {"message": "Webhook deleted"}
