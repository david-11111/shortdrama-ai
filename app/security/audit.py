"""
审计日志服务 — 写入 audit_log 表。

append-only：不提供删除接口。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def log_admin_action(
    user_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """
    记录管理员操作审计日志。

    action 示例: "user.disable", "credits.adjust", "dead_letter.resolve"
    """
    payload_json = json.dumps(payload or {})
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT INTO audit_log
                            (user_id, action, target_type, target_id, payload, ip, user_agent)
                        VALUES
                            (:user_id, :action, :target_type, :target_id,
                             :payload::jsonb, :ip, :user_agent)
                    """),
                    {
                        "user_id": user_id,
                        "action": action,
                        "target_type": target_type,
                        "target_id": str(target_id) if target_id is not None else None,
                        "payload": payload_json,
                        "ip": ip,
                        "user_agent": user_agent,
                    },
                )
    except Exception as exc:
        # 审计失败不应阻断业务，但必须记录
        logger.error("Audit log write failed: action=%s user_id=%s error=%s", action, user_id, exc)
