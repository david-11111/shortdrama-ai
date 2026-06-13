from __future__ import annotations

import asyncio
import json

import httpx

from lib.assertions import require
from lib.project_fixture import test_project


BASE_URL = "http://localhost:8000"


def _access_token(headers: dict[str, str]) -> str:
    value = headers.get("Authorization", "")
    prefix = "Bearer "
    require(value.startswith(prefix), "missing bearer token", headers)
    return value[len(prefix):]


def _parse_sse_blocks(text: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for raw in text.replace("\r\n", "\n").split("\n\n"):
        if not raw.strip():
            continue
        event_name = ""
        event_id = ""
        data_lines: list[str] = []
        for line in raw.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("id:"):
                event_id = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        data = json.loads("\n".join(data_lines)) if data_lines else {}
        blocks.append({"event": event_name, "id": event_id, "data": data})
    return blocks


async def main() -> None:
    async with test_project("Agent Run SSE Verify", prefix="agent-run-sse") as ctx:
        token = _access_token(ctx.headers)
        with httpx.Client(base_url=BASE_URL, headers=ctx.headers, timeout=60.0) as client:
            client.get("/health").raise_for_status()
            client.post(f"/api/projects/{ctx.project_id}/workspace/init", json={"force": True}).raise_for_status()
            response = client.post(
                f"/api/projects/{ctx.project_id}/brain/continue",
                json={
                    "mode": "step",
                    "allowed_max_credits": 50,
                    "instruction": "生成一条 30 秒短剧的第一场分镜规划",
                },
            )
            response.raise_for_status()
            run_id = response.json().get("run_id")
            require(run_id, "missing run_id", response.json())

            stream_path = f"/api/agent-runs/{run_id}/stream?token={token}&history_limit=80"
            with client.stream("GET", stream_path) as stream:
                stream.raise_for_status()
                body = ""
                for chunk in stream.iter_text():
                    body += chunk
                    if "event: stream_done" in body:
                        break

            blocks = _parse_sse_blocks(body)
            event_names = [str(block["event"]) for block in blocks]
            execution_events = [block for block in blocks if block["event"] == "execution_event"]
            require("stream_ready" in event_names, "missing stream_ready", event_names)
            require("stream_done" in event_names, "missing stream_done", event_names)
            require(execution_events, "missing execution events", blocks)
            require(
                all((block["data"] or {}).get("visibility") != "debug" for block in execution_events if isinstance(block["data"], dict)),
                "debug event leaked into main SSE execution events",
                execution_events,
            )

            snapshot = client.get(f"/api/agent-runs/{run_id}/snapshot").json()
            require(snapshot.get("run", {}).get("run_id") == run_id, "snapshot run_id mismatch", snapshot.get("run"))
            require(snapshot.get("stream"), "snapshot stream empty", snapshot)

        print(
            json.dumps(
                {
                    "ok": True,
                    "project_id": ctx.project_id,
                    "run_id": run_id,
                    "sse_events": event_names,
                    "execution_event_count": len(execution_events),
                    "snapshot_stream_count": len(snapshot.get("stream") or []),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
