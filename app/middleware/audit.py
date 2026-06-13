"""
管理端审计中间件 — 自动记录所有 /admin 路由的写操作。
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.security.audit import log_admin_action

logger = logging.getLogger(__name__)


class AdminAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/admin"):
            return await call_next(request)
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)

        response = await call_next(request)

        if 200 <= response.status_code < 300:
            # admin 路由通过 require_admin 依赖，用户信息存在 request.state.user
            user_state = getattr(request.state, "user", None)
            user_id: int | None = user_state.get("id") if isinstance(user_state, dict) else None

            path_parts = request.url.path.strip("/").split("/")
            action = f"{request.method.lower()}.{'.'.join(path_parts[:2])}"
            target_id = path_parts[2] if len(path_parts) >= 3 else None

            await log_admin_action(
                user_id=user_id,
                action=action,
                target_type=path_parts[1] if len(path_parts) >= 2 else None,
                target_id=target_id,
                payload={"path": request.url.path},
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )

        return response
