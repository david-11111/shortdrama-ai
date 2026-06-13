from __future__ import annotations

import shutil
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services.auth import create_access_token
from app.services.project_workspace import project_workspace_root


@dataclass
class TestProject:
    email: str
    user_id: int
    project_id: str
    headers: dict[str, str]


@asynccontextmanager
async def test_project(name: str, *, prefix: str = "verify", balance: int = 1000) -> AsyncIterator[TestProject]:
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.test"
    project_id = uuid.uuid4().hex[:16]
    user_id: int | None = None
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                row = await session.execute(
                    text(
                        """
                        INSERT INTO users (email, password_hash, display_name, tier, status)
                        VALUES (:email, 'verify-only', :name, 'pro', 'active')
                        RETURNING id
                        """
                    ),
                    {"email": email, "name": name},
                )
                user_id = int(row.scalar_one())
                await session.execute(
                    text("INSERT INTO credit_accounts (user_id, balance, lifetime_earned) VALUES (:uid, :balance, :balance)"),
                    {"uid": user_id, "balance": balance},
                )
                await session.execute(
                    text("INSERT INTO projects (project_id, user_id, name) VALUES (:pid, :uid, :name)"),
                    {"pid": project_id, "uid": user_id, "name": name},
                )

        token = create_access_token({"sub": str(user_id), "email": email, "tier": "pro"})
        yield TestProject(email=email, user_id=user_id, project_id=project_id, headers={"Authorization": f"Bearer {token}"})
    finally:
        if user_id is not None:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    params = {"pid": project_id, "uid": user_id, "email": email}
                    for statement in (
                        "DELETE FROM final_video_blobs WHERE project_id = :pid",
                        "DELETE FROM final_video_assets WHERE project_id = :pid",
                        "DELETE FROM video_production_runs WHERE project_id = :pid",
                        "DELETE FROM agent_interrupts WHERE project_id = :pid",
                        "DELETE FROM agent_artifacts WHERE project_id = :pid",
                        "DELETE FROM agent_events WHERE project_id = :pid",
                        "DELETE FROM agent_steps WHERE run_id IN (SELECT id FROM agent_runs WHERE project_id = :pid)",
                        "DELETE FROM agent_runs WHERE project_id = :pid",
                        "DELETE FROM provider_usage_costs WHERE project_id = :pid",
                        "DELETE FROM tasks WHERE project_id = :pid",
                        "DELETE FROM shot_rows WHERE project_id = :pid",
                        "DELETE FROM final_edit_plans WHERE project_id = :pid",
                        "DELETE FROM projects WHERE project_id = :pid",
                        "DELETE FROM credit_transactions WHERE user_id = :uid",
                        "DELETE FROM credit_accounts WHERE user_id = :uid",
                        "DELETE FROM login_attempts WHERE email = :email",
                        "DELETE FROM users WHERE id = :uid",
                    ):
                        await session.execute(text(statement), params)
            shutil.rmtree(project_workspace_root(project_id), ignore_errors=True)
