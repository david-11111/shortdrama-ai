from __future__ import annotations

import asyncio
import json

import httpx
from sqlalchemy import text

from lib.assertions import require
from lib.mp4 import inspect_mp4
from lib.project_fixture import AsyncSessionLocal, test_project
from lib.tasks import wait_task_result


BASE_URL = "http://localhost:8000"
CLIPS = ["/tmp/final_cut_chain_smoke/clip1.mp4", "/tmp/final_cut_chain_smoke/clip2.mp4"]
BGM = "/tmp/final_cut_chain_smoke/bgm.wav"
REQUIRED_BRAIN_AUDITS = [
    "context_coverage",
    "ledger_merge_audit",
    "creative_lowering_audit",
    "continuity_handoff_audit",
    "cost_control_audit",
    "final_delivery_audit",
    "feedback_loop_audit",
]


def rows(brain: dict, key: str) -> list[dict]:
    value = (brain.get("context") or {}).get(key)
    require(isinstance(value, list) and value, f"missing brain audit: {key}", brain.get("context"))
    return [item for item in value if isinstance(item, dict)]


def component(items: list[dict], name: str, coverage: str | None = None) -> dict:
    for item in items:
        if item.get("component") == name:
            require(not coverage or item.get("coverage") == coverage, f"bad coverage for {name}", item)
            return item
    raise AssertionError(f"component missing: {name}")


def workspace_files(project_id: str) -> dict[str, str]:
    shots = {
        "shots": [
            {
                "shot_index": 1,
                "scene": "episode-01-scene-01",
                "minute_start": 0,
                "minute_end": 1,
                "prompt": "Lead pauses at a rainy doorway, restrained expression, natural backlight.",
                "duration": 2.0,
                "camera": "Medium shot, slow push-in, stable motion.",
                "emotion": "Held breath, quiet tension.",
            },
            {
                "shot_index": 2,
                "scene": "episode-01-scene-01",
                "minute_start": 1,
                "minute_end": 2,
                "prompt": "Second lead appears from inside the doorway with warm side light.",
                "duration": 2.0,
                "camera": "Close-up into detail, slow push, short pause.",
                "emotion": "Low voice, controlled delivery.",
            },
        ]
    }
    return {
        "PROJECT.md": "\n".join(
            [
                "# Full Chain Verify",
                f"- project_id: {project_id}",
                "- target_duration_minutes: 40",
                "- current_scene: episode-01-scene-01",
                "- commercial_goal: deliverable short-drama preview with video, subtitles, BGM, and edit plan.",
            ]
        ),
        "story/characters.md": "- Lead: white coat, restrained, locked rainy-night look.\n- Second lead: black shirt, warm doorway light.",
        "story/episodes.md": "- episode-01: rainy-night reunion.\n- scene-01: doorway wait and appearance.\n- scene-02: explanation follows.",
        "scenes/episode-01-scene-01.md": "- current: rainy doorway.\n- next: explanation.\n- edit_strategy: slow-fast-slow, low BGM bed.",
        "shots/episode-01-scene-01.json": json.dumps(shots, ensure_ascii=False),
        "memory/decisions.md": "- source: project_brain_continue\n- reason: reuse locked assets before burning providers.",
        "memory/failures.md": "- source: media_task_writeback\n- note: avoid plastic lighting; require natural backlight and depth.",
        "memory/constraints.md": "\n".join(
            [
                "- seedream_batch_max: 4",
                "- seedance_batch_max: 1",
                "- reuse_assets_first: true",
                "- final_delivery_requires: video,bgm,subtitles,edit_plan",
                "- prompt_style: short concrete instructions.",
            ]
        ),
    }


async def seed_video_shots(ctx) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for idx, clip in enumerate(CLIPS, 1):
                await session.execute(
                    text(
                        """
                        INSERT INTO shot_rows (
                            project_id, user_id, shot_index, prompt, duration, status,
                            video_variants_json, selected_video
                        )
                        VALUES (
                            :project_id, :user_id, :shot_index, :prompt, 2.0, 'video_done',
                            CAST(:variants AS JSONB), :selected_video
                        )
                        """
                    ),
                    {
                        "project_id": ctx.project_id,
                        "user_id": ctx.user_id,
                        "shot_index": idx,
                        "prompt": "Rainy-night restrained character shot" if idx == 1 else "Warm doorway handoff shot",
                        "variants": json.dumps([{"url": clip}], ensure_ascii=False),
                        "selected_video": clip,
                    },
                )


def require_brain_before(brain: dict) -> None:
    for key in REQUIRED_BRAIN_AUDITS:
        rows(brain, key)
    covered = {item.get("path") for item in rows(brain, "context_coverage") if item.get("coverage") == "covered"}
    require("PROJECT.md" in covered, "PROJECT.md not covered", covered)
    require("shots/episode-01-scene-01.json" in covered, "shot plan not covered", covered)
    for name in ("small_step_keyframes", "small_step_videos", "credit_guard", "rate_concurrency_guard"):
        component(rows(brain, "cost_control_audit"), name, "covered")
    for name in ("scene_position", "minute_position", "next_scene"):
        component(rows(brain, "continuity_handoff_audit"), name)


def complete_plan(plan: dict) -> dict:
    plan["settings"]["bgm_path"] = BGM
    plan["settings"]["bgm_volume"] = 0.1
    plan["settings"]["burn_subtitles"] = True
    plan["settings"]["cover_title"] = "Rainy Night Verify"
    plan["clips"][0]["transition"] = "cut"
    plan["clips"][1]["transition"] = "fade"
    plan["clips"][1]["trim_end"] = 0.5
    plan["clips"][0]["subtitle"] = "Wait. I need to confirm one thing first."
    plan["clips"][1]["subtitle"] = "You finally came."
    return plan


def require_ready_brain(brain: dict) -> None:
    for name in ("video_complete", "bgm_ready", "subtitles_ready", "edit_plan_complete", "preview_export_ready"):
        component(rows(brain, "final_delivery_audit"), name, "covered")
    for name in ("workspace_decision_memory", "shot_row_status_writeback", "media_success_writeback", "final_edit_writeback"):
        component(rows(brain, "feedback_loop_audit"), name, "covered")


async def task_payload(task_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text("SELECT task_type, payload FROM tasks WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
        ).fetchone()
    require(row is not None, "preview task row missing", task_id)
    require(row.task_type == "director_export_preview", "wrong task type", row)
    payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
    require(payload.get("edit_plan_export"), "task missing executable export", payload)
    require(payload.get("clip_count") == 2, "wrong dispatched clip count", payload)
    return payload


async def main() -> None:
    async with test_project("Final Cut Chain Verify", prefix="final-cut-chain") as ctx:
        task_id = ""
        with httpx.Client(base_url=BASE_URL, headers=ctx.headers, timeout=30.0) as client:
            client.get("/health").raise_for_status()
            await seed_video_shots(ctx)
            client.post(f"/api/projects/{ctx.project_id}/workspace/init", json={"force": True}).raise_for_status()
            for path, content in workspace_files(ctx.project_id).items():
                client.post(
                    f"/api/projects/{ctx.project_id}/workspace/write",
                    json={"path": path, "content": content, "mode": "replace", "source": "full_chain_verify", "force": True},
                ).raise_for_status()

            brain_before = client.get(f"/api/projects/{ctx.project_id}/brain").json()
            require_brain_before(brain_before)

            plan = client.get(f"/api/projects/{ctx.project_id}/final-edit-plan").json().get("plan") or {}
            require(len(plan.get("clips") or []) == 2, "wrong clip count", plan)
            require(plan["clips"][0]["video_url"] == CLIPS[0], "clip 1 mismatch", plan)

            blocked = client.post("/api/director/export-preview", json={"project_id": ctx.project_id, "edit_plan": plan})
            require(blocked.status_code == 400, "incomplete plan was not blocked", blocked.text[:500])
            require("missing_bgm" in blocked.text, "missing_bgm was not reported", blocked.text[:500])

            plan = complete_plan(plan)
            client.put(f"/api/projects/{ctx.project_id}/final-edit-plan", json=plan).raise_for_status()
            require_ready_brain(client.get(f"/api/projects/{ctx.project_id}/brain").json())

            preview_resp = client.post("/api/director/export-preview", json={"project_id": ctx.project_id, "edit_plan": plan})
            preview_resp.raise_for_status()
            task_id = preview_resp.json()["task_id"]
            await task_payload(task_id)

            result = await wait_task_result(task_id)
            preview_url = result.get("preview_url") or result.get("final_url")
            require(preview_url, "missing preview url", result)
            require(result.get("export_kind") == "preview", "wrong export kind", result)
            require(int(result.get("clip_count") or 0) == 2, "wrong exported clip count", result)
            require(float(result.get("duration_sec") or 0) > 1.0, "preview too short", result)
            require(int(result.get("file_size") or 0) > 1000, "preview too small", result)

            video_resp = client.get(preview_url)
            video_resp.raise_for_status()
            require(video_resp.headers.get("content-type", "").startswith("video/mp4"), "preview is not mp4", video_resp.headers)
            require(len(video_resp.content) > 1000, "preview body too small")
            probe = inspect_mp4(video_resp.content)
            require(probe["has_ftyp"] and probe["has_moov"] and probe["has_mdat"], "invalid mp4 boxes", probe)
            require(probe["has_video_track"] and probe["has_audio_track"], "missing media tracks", probe)

            brain_after = client.get(f"/api/projects/{ctx.project_id}/brain").json()
            component(rows(brain_after, "feedback_loop_audit"), "final_edit_writeback", "covered")
            component(rows(brain_after, "final_delivery_audit"), "preview_export_ready", "covered")

        print(
            json.dumps(
                {
                    "ok": True,
                    "project_id": ctx.project_id,
                    "task_id": task_id,
                    "preview_url": preview_url,
                    "preview_bytes": len(video_resp.content),
                    "preview_probe": probe,
                    "blocked_incomplete_plan": True,
                    "clip_count": result.get("clip_count"),
                    "export_duration_sec": result.get("duration_sec"),
                    "export_file_size": result.get("file_size"),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
