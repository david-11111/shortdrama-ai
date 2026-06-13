from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_BASE_URL = "http://localhost:8000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start a visible local-placeholder video production run.")
    parser.add_argument("--base-url", default=os.getenv("SAAS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--user-email", default=os.getenv("SAAS_RUN_USER_EMAIL", ""))
    parser.add_argument(
        "--goal",
        default=(
            "Create a 15-second premium short-drama demo: the lead makes a key decision "
            "on a rainy night, restrained but emotionally tense."
        ),
    )
    parser.add_argument("--execute", action="store_true", help="Actually create the project and start the run.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not args.user_email:
        raise RuntimeError("missing --user-email or SAAS_RUN_USER_EMAIL")

    project_id = uuid.uuid4().hex[:16]
    body = {
        "goal": args.goal,
        "episode": 1,
        "scene": 1,
        "target_duration_sec": 15,
        "mode": "step",
        "provider_mode": "local",
        "allow_local_placeholders": True,
    }
    if not args.execute:
        print(
            json.dumps(
                {"dry_run": True, "project_id": project_id, "user_email": args.user_email, "request": body},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    import httpx
    from sqlalchemy import text

    from app.db import AsyncSessionLocal
    from app.services.auth import create_access_token

    async with AsyncSessionLocal() as session:
        async with session.begin():
            user_row = await session.execute(
                text("SELECT id, email, tier FROM users WHERE email = :email LIMIT 1"),
                {"email": args.user_email},
            )
            user = user_row.mappings().first()
            if not user:
                raise RuntimeError(f"user not found: {args.user_email}")
            user_id = int(user["id"])
            await session.execute(
                text(
                    """
                    INSERT INTO projects (project_id, user_id, name)
                    VALUES (:project_id, :user_id, :name)
                    """
                ),
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "name": "Agent visible local video demo",
                },
            )

    token = create_access_token({"sub": str(user_id), "email": args.user_email, "tier": str(user["tier"] or "free")})
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=30.0) as client:
        response = client.post(f"/api/projects/{project_id}/production/start", json=body)
        response.raise_for_status()
        result = response.json()

    print(
        json.dumps(
            {
                "project_id": project_id,
                "user_id": user_id,
                "project_name": "Agent visible local video demo",
                "produce_url": f"/director/produce?project_id={project_id}",
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
