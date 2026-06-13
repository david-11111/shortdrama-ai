from __future__ import annotations

import asyncio
import json

import httpx
from sqlalchemy import text

from lib.assertions import require
from lib.project_fixture import AsyncSessionLocal, test_project


BASE_URL = "http://localhost:8000"
REQUIRED_PHASES = {
    "read_context",
    "merge_memory",
    "map_techniques",
    "check_continuity",
    "cost_guard",
    "delivery_audit",
    "dispatch_instruction",
    "writeback_review",
}


async def main() -> None:
    async with test_project("Agent Runtime Step Verify", prefix="agent-runtime-step") as ctx:
        with httpx.Client(base_url=BASE_URL, headers=ctx.headers, timeout=60.0) as client:
            client.get("/health").raise_for_status()
            client.post(f"/api/projects/{ctx.project_id}/workspace/init", json={"force": True}).raise_for_status()
            resp = client.post(
                f"/api/projects/{ctx.project_id}/brain/continue",
                json={"mode": "step", "allowed_max_credits": 50},
            )
            resp.raise_for_status()
            payload = resp.json()
            run_id = payload.get("run_id")
            require(run_id, "missing run_id", payload)
            require(payload.get("applied") is True, "step mode did not apply", payload)

            events_resp = client.get(f"/api/projects/{ctx.project_id}/agent-events", params={"limit": 80, "run_id": run_id})
            events_resp.raise_for_status()
            events = events_resp.json().get("events") or events_resp.json().get("items") or []
            phases = {item.get("phase") for item in events}
            missing = REQUIRED_PHASES - phases
            require(not missing, "missing phases", {"missing": sorted(missing), "phases": sorted(phases)})
            require(any(item.get("type") == "execution_event" for item in events), "missing execution event")
            require(any(item.get("event_type") == "decision" for item in events), "missing decision event")

            runs_resp = client.get(f"/api/projects/{ctx.project_id}/agent-runs", params={"limit": 10})
            runs_resp.raise_for_status()
            runs = runs_resp.json().get("runs") or []
            require(any(item.get("run_id") == run_id for item in runs), "run missing from list API", runs)

        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM agent_runs WHERE id = CAST(:run_id AS UUID)) AS runs,
                          (SELECT status FROM agent_runs WHERE id = CAST(:run_id AS UUID)) AS status,
                          (SELECT COUNT(*) FROM agent_steps WHERE run_id = CAST(:run_id AS UUID)) AS steps,
                          (SELECT COUNT(*) FROM agent_events WHERE run_id = CAST(:run_id AS UUID)) AS events,
                          (SELECT COUNT(*) FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id) AS shots,
                          (SELECT COUNT(*) FROM tasks WHERE run_id = CAST(:run_id AS UUID)) AS tasks
                        """
                    ),
                    {"run_id": run_id, "project_id": ctx.project_id, "user_id": ctx.user_id},
                )
            ).fetchone()

        require(int(row.runs or 0) == 1, "agent run not persisted", row)
        require(str(row.status or "") in {"completed", "dispatching", "blocked"}, "bad run status", row)
        require(int(row.steps or 0) >= 8, "too few steps", row)
        require(int(row.events or 0) >= 9, "too few events", row)
        require(int(row.shots or 0) > 0, "no shots created", row)
        print(
            json.dumps(
                {
                    "ok": True,
                    "project_id": ctx.project_id,
                    "run_id": run_id,
                    "status": str(row.status or ""),
                    "shot_count": int(row.shots or 0),
                    "task_count": int(row.tasks or 0),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
