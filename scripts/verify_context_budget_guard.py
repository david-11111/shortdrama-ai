from __future__ import annotations

import asyncio
import json

import httpx
from sqlalchemy import text

from lib.assertions import require
from lib.project_fixture import AsyncSessionLocal, test_project


BASE_URL = "http://localhost:8000"


def oversized_markdown(title: str, repeated: int) -> str:
    block = (
        "- scene: rainy street corner\n"
        "- character: restrained lead with consistent wardrobe and lighting\n"
        "- constraint: preserve continuity, avoid broad prompts, keep cost bounded\n"
        "- delivery: video, subtitles, BGM, edit strategy, preview readiness\n"
    )
    return f"# {title}\n\n" + block * repeated


async def main() -> None:
    files = {
        "PROJECT.md": oversized_markdown("Oversized Project Context", 500),
        "story/episodes.md": oversized_markdown("Oversized Episodes", 450),
        "memory/constraints.md": oversized_markdown("Oversized Constraints", 350),
    }
    async with test_project("Context Budget Verify", prefix="context-budget") as ctx:
        with httpx.Client(base_url=BASE_URL, headers=ctx.headers, timeout=60.0) as client:
            client.get("/health").raise_for_status()
            client.post(f"/api/projects/{ctx.project_id}/workspace/init", json={"force": True}).raise_for_status()
            for path, content in files.items():
                client.post(
                    f"/api/projects/{ctx.project_id}/workspace/write",
                    json={
                        "path": path,
                        "content": content,
                        "mode": "replace",
                        "source": "context_budget_verify",
                        "reason": "verify oversized context guard",
                        "force": True,
                    },
                ).raise_for_status()

            response = client.post(
                f"/api/projects/{ctx.project_id}/brain/continue",
                json={"mode": "preview", "allowed_max_credits": 10},
            )
            require(response.status_code < 500, "oversized context crashed", response.text[:1000])
            response.raise_for_status()
            payload = response.json()
            run_id = payload.get("run_id")
            require(run_id, "missing run_id", payload)
            require(payload.get("applied") is False, "preview applied changes", payload)

            events_resp = client.get(f"/api/projects/{ctx.project_id}/agent-events", params={"limit": 120, "run_id": run_id})
            events_resp.raise_for_status()
            events = events_resp.json().get("events") or events_resp.json().get("items") or []
            phases = {item.get("phase") for item in events}
            require("read_context" in phases, "context reader did not run", sorted(phases))
            require(any(item.get("event_type") == "decision" for item in events), "missing decision event")

        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    text("SELECT status FROM agent_runs WHERE id = CAST(:run_id AS UUID)"),
                    {"run_id": run_id},
                )
            ).fetchone()
        require(row is not None, "agent run missing", run_id)
        require(str(row.status or "") in {"completed", "blocked", "dispatching"}, "bad run status", row)
        print(
            json.dumps(
                {
                    "ok": True,
                    "project_id": ctx.project_id,
                    "run_id": run_id,
                    "status": str(row.status or ""),
                    "oversized_files": {path: len(content) for path, content in files.items()},
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
