from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[], Awaitable[dict[str, Any]]]


def build_main_chain_handlers(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    user_tier: str,
    run_id: str,
    run_mode: str,
) -> dict[str, Handler]:
    from app.routes import workbench

    async def generate_keyframes() -> dict[str, Any]:
        before = await workbench._brain_for_gateway_handler(db, project_id=project_id, user_id=user_id)
        return await workbench._continue_generate_keyframes(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
        )

    async def generate_videos() -> dict[str, Any]:
        before = await workbench._brain_for_gateway_handler(db, project_id=project_id, user_id=user_id)
        return await workbench._continue_generate_videos(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
        )

    async def plan_final_edit() -> dict[str, Any]:
        before = await workbench._brain_for_gateway_handler(db, project_id=project_id, user_id=user_id)
        return await workbench._continue_plan_final_edit(
            db,
            project_id=project_id,
            user_id=user_id,
            before=before,
            run_id=run_id,
        )

    return {
        "generate_keyframes": generate_keyframes,
        "generate_videos": generate_videos,
        "plan_final_edit": plan_final_edit,
    }
