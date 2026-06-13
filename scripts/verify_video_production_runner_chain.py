from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil

import httpx
from sqlalchemy import text

from lib.assertions import require
from lib.project_fixture import AsyncSessionLocal, test_project
from lib.tasks import wait_task_result


BASE_URL = "http://localhost:8000"
REQUIRED_STAGES = {
    "read_context",
    "plan_story",
    "lock_assets",
    "plan_shots",
    "generate_keyframes",
    "generate_videos",
    "generate_voice",
    "select_bgm",
    "generate_subtitles",
    "build_edit_strategy",
    "ffmpeg_export",
    "quality_check",
    "writeback",
}
REQUIRED_FFMPEG_PHASES = {
    "validate_plan",
    "normalize_clips",
    "concat_clips",
    "mix_audio",
    "burn_subtitles",
    "export_mp4",
    "probe_output",
}


async def production_row(ctx, production_run_id: str, agent_run_id: str, final_task_id: str):
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                text(
                    """
                    SELECT
                      v.status AS production_status,
                      v.final_video_url,
                      v.final_delivery_report_json,
                      v.edit_strategy_json,
                      a.status AS agent_status,
                      a.production_ledger,
                      (SELECT COUNT(*) FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id) AS shots,
                      (SELECT COUNT(*) FROM agent_events WHERE run_id = CAST(:agent_run_id AS UUID)) AS events,
                      (SELECT COUNT(*) FROM final_video_assets WHERE task_id = CAST(:final_task_id AS UUID)) AS assets,
                      (SELECT storage_mode FROM final_video_assets WHERE task_id = CAST(:final_task_id AS UUID)) AS asset_storage_mode,
                      (SELECT file_size FROM final_video_assets WHERE task_id = CAST(:final_task_id AS UUID)) AS asset_file_size,
                      (SELECT COUNT(*) FROM final_video_blobs WHERE task_id = CAST(:final_task_id AS UUID)) AS blobs,
                      (SELECT file_size FROM final_video_blobs WHERE task_id = CAST(:final_task_id AS UUID)) AS file_size,
                      (SELECT data FROM final_video_blobs WHERE task_id = CAST(:final_task_id AS UUID)) AS blob_data
                    FROM video_production_runs v
                    JOIN agent_runs a ON a.id = v.agent_run_id
                    WHERE v.id = CAST(:production_run_id AS UUID)
                    """
                ),
                {
                    "project_id": ctx.project_id,
                    "user_id": ctx.user_id,
                    "production_run_id": production_run_id,
                    "agent_run_id": agent_run_id,
                    "final_task_id": final_task_id,
                },
            )
        ).fetchone()


def require_events(events: list[dict]) -> None:
    phases = {item.get("phase") for item in events}
    missing_stages = REQUIRED_STAGES - phases
    missing_ffmpeg = REQUIRED_FFMPEG_PHASES - phases
    require(not missing_stages, "missing production stages", {"missing": sorted(missing_stages), "phases": sorted(phases)})
    require(not missing_ffmpeg, "missing ffmpeg phases", {"missing": sorted(missing_ffmpeg), "phases": sorted(phases)})
    require(
        any(item.get("event_type") == "artifact" and item.get("meta", {}).get("artifact_type") == "final_video" for item in events),
        "missing final video artifact event",
    )


def require_persisted_result(row) -> None:
    require(row.production_status == "completed", "production not completed", row)
    require(row.agent_status == "completed", "agent not completed", row)
    require(int(row.shots or 0) == 3, "shot count mismatch", row)
    require(int(row.events or 0) >= 30, "too few events", row)
    require(int(row.assets or 0) == 1 or int(row.blobs or 0) == 1, "final video asset missing", row)
    require(int(row.asset_file_size or row.file_size or 0) > 1000, "final video too small", row)
    require(row.final_delivery_report_json["passed"] is True, "delivery report failed", row.final_delivery_report_json)
    require(row.edit_strategy_json["rhythm"], "edit rhythm missing", row.edit_strategy_json)
    require(row.production_ledger["final_video_url"] == row.final_video_url, "ledger url mismatch", row.production_ledger)

    if row.blob_data is not None:
        blob = bytes(row.blob_data)
        require(b"ftyp" in blob[:64], "missing mp4 ftyp")
        require(b"moov" in blob, "missing mp4 moov")
        require(b"mdat" in blob, "missing mp4 mdat")
    probe = row.final_delivery_report_json["probe"]
    require(probe["has_video"] is True, "probe missing video", probe)
    require(probe["has_audio"] is True, "probe missing audio", probe)
    require(probe["duration_sec"] >= 9, "duration too short", probe)


async def main() -> None:
    async with test_project("Video Production Verify", prefix="video-production") as ctx:
        try:
            with httpx.Client(base_url=BASE_URL, headers=ctx.headers, timeout=90.0) as client:
                client.get("/health").raise_for_status()
                response = client.post(
                    f"/api/projects/{ctx.project_id}/production/start",
                    json={
                        "goal": "Create a 15-second premium short-drama preview.",
                        "episode": 1,
                        "scene": 1,
                        "target_duration_sec": 15,
                        "mode": "step",
                        "allow_local_placeholders": True,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                require(payload.get("status") == "queued", "runner not queued", payload)

                result = await wait_task_result(payload["task_id"])
                require(result.get("ok") is True, "runner failed", result)
                require(result.get("final_video_url"), "missing final video url", result)
                require(result.get("final_delivery_report", {}).get("passed") is True, "delivery failed", result)
                require(result.get("edit_strategy", {}).get("rhythm"), "missing edit rhythm", result)
                video_resp = client.get(result["final_video_url"])
                video_resp.raise_for_status()
                require(video_resp.headers.get("content-type", "").startswith("video/mp4"), "final video endpoint is not mp4", video_resp.headers)
                require(len(video_resp.content) > 1000, "final video endpoint returned too little data", len(video_resp.content))

                events_resp = client.get(
                    f"/api/projects/{ctx.project_id}/agent-events",
                    params={"run_id": payload["agent_run_id"], "limit": 200},
                )
                events_resp.raise_for_status()
                require_events(events_resp.json().get("events") or events_resp.json().get("items") or [])

            row = await production_row(ctx, payload["production_run_id"], payload["agent_run_id"], result["final_task_id"])
            require(row is not None, "production row missing")
            require_persisted_result(row)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "project_id": ctx.project_id,
                        "production_run_id": payload["production_run_id"],
                        "agent_run_id": payload["agent_run_id"],
                        "final_task_id": result["final_task_id"],
                        "final_video_url": result["final_video_url"],
                        "duration_sec": result["final_delivery_report"]["probe"]["duration_sec"],
                        "event_count": int(row.events or 0),
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            shutil.rmtree(Path("storage") / "video_production" / ctx.project_id, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
