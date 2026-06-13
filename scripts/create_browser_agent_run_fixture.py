from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import AsyncSessionLocal
from app.services.auth import create_access_token


BASE_URL = "http://localhost:8000"
BROWSER_IMAGE_DATA_URL = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 360'%3E"
    "%3Crect width='640' height='360' fill='%23161b22'/%3E"
    "%3Ccircle cx='450' cy='140' r='70' fill='%2358a6ff'/%3E"
    "%3Cpath d='M0 290L170 160l120 85 90-55 260 170H0z' fill='%233fb950'/%3E"
    "%3Ctext x='32' y='60' fill='%23f0f6fc' font-family='Arial' font-size='28'%3EAgent Run Keyframe%3C/text%3E"
    "%3C/svg%3E"
)


async def main() -> None:
    email = f"browser-agent-run-{uuid.uuid4().hex[:10]}@example.test"
    project_id = uuid.uuid4().hex[:16]
    name = "Browser Agent Run Verify"

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
                text("INSERT INTO credit_accounts (user_id, balance, lifetime_earned) VALUES (:uid, 1000, 1000)"),
                {"uid": user_id},
            )
            await session.execute(
                text("INSERT INTO projects (project_id, user_id, name) VALUES (:pid, :uid, :name)"),
                {"pid": project_id, "uid": user_id, "name": name},
            )

    token = create_access_token({"sub": str(user_id), "email": email, "tier": "pro"})
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=60.0) as client:
        client.get("/health").raise_for_status()
        client.post(f"/api/projects/{project_id}/workspace/init", json={"force": True}).raise_for_status()
        response = client.post(
            f"/api/projects/{project_id}/brain/continue",
            json={
                "mode": "step",
                "allowed_max_credits": 50,
                "instruction": "生成一个用于浏览器联调的短剧分镜，并保留可展示成果。",
            },
        )
        response.raise_for_status()
        run_id = response.json()["run_id"]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    UPDATE shot_rows
                    SET selected_image = COALESCE(selected_image, :image_url),
                        selected_video = COALESCE(selected_video, :video_url),
                        status = 'video_done',
                        updated_at = NOW()
                    WHERE project_id = :project_id
                      AND user_id = :user_id
                      AND shot_index = (
                        SELECT MIN(shot_index)
                        FROM shot_rows
                        WHERE project_id = :project_id AND user_id = :user_id
                      )
                    """
                ),
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "image_url": BROWSER_IMAGE_DATA_URL,
                    "video_url": "https://example.com/browser-agent-run-video.mp4",
                },
            )

    print(
        json.dumps(
            {
                "ok": True,
                "email": email,
                "user_id": user_id,
                "project_id": project_id,
                "run_id": run_id,
                "access_token": token,
                "url": f"http://localhost:3000/director/agent-run/{run_id}",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
