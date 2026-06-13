import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from jose import JWTError

from app.redis_client import redis_client
from app.db import AsyncSessionLocal
from app.security.token_blacklist import is_token_blacklisted
from app.services.auth import decode_token, get_token_jti
from sqlalchemy import text


async def ws_task_updates(websocket: WebSocket, token: str = ""):
    """
    WebSocket 端点 — 带 Token 验证。
    连接: WS /ws/tasks?token=<jwt>
    """
    # 验证 Token
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token type")
            return
        token_jti = get_token_jti(token, payload)
        if await is_token_blacklisted(token_jti):
            await websocket.close(code=4001, reason="Token has been revoked")
            return
        user_id = int(payload["sub"])
    except (JWTError, Exception):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()

    subscribed_tasks: set[str] = set()
    subscribed_projects: set[str] = set()
    pubsub = redis_client.pubsub()

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                msg = json.loads(data)

                if msg.get("type") == "subscribe":
                    task_ids = msg.get("task_ids", [])
                    for tid in task_ids:
                        if tid not in subscribed_tasks:
                            await pubsub.subscribe(f"task:{tid}:progress")
                            subscribed_tasks.add(tid)

                elif msg.get("type") == "unsubscribe":
                    task_ids = msg.get("task_ids", [])
                    for tid in task_ids:
                        if tid in subscribed_tasks:
                            await pubsub.unsubscribe(f"task:{tid}:progress")
                            subscribed_tasks.discard(tid)

                elif msg.get("type") == "subscribe_project":
                    project_ids = msg.get("project_ids", [])
                    for project_id in project_ids:
                        pid = str(project_id or "").strip()
                        if not pid or pid in subscribed_projects:
                            continue
                        if await _can_access_project(pid, user_id):
                            await pubsub.subscribe(f"project:{pid}:events")
                            subscribed_projects.add(pid)

                elif msg.get("type") == "unsubscribe_project":
                    project_ids = msg.get("project_ids", [])
                    for project_id in project_ids:
                        pid = str(project_id or "").strip()
                        if pid in subscribed_projects:
                            await pubsub.unsubscribe(f"project:{pid}:events")
                            subscribed_projects.discard(pid)

                elif msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

            except asyncio.TimeoutError:
                pass

            # Avoid calling get_message before any channel is subscribed.
            if subscribed_tasks or subscribed_projects:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                    if message and message["type"] == "message":
                        await websocket.send_text(message["data"])
                except RuntimeError:
                    # Redis pubsub may transiently reset; continue loop and wait for next subscribe cycle.
                    pass

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()


async def _can_access_project(project_id: str, user_id: int) -> bool:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT 1 FROM projects WHERE project_id = :project_id AND user_id = :user_id LIMIT 1"),
                {"project_id": project_id, "user_id": user_id},
            )
            return result.scalar() is not None
    except Exception:
        return False
