from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.config import FFMPEG, get_settings
from app.middleware.credits import reserve_credits
from app.services.agent_runtime import ensure_run_budget
from app.services.agent_runtime import (
    create_agent_run,
    create_agent_step,
    publish_agent_event,
    record_agent_artifact,
    update_agent_run,
)
from app.services.capacity_guard import check_capacity_sync as check_provider_capacity
from app.services.cost_guard import assert_cost_guard
from app.services.credits import credit_service
from app.services.edit_strategy import build_edit_strategy
from app.services.final_delivery import build_final_delivery_report
from app.services.final_edit import export_payload_from_plan, normalize_edit_plan
from app.services.final_video_storage import copy_final_video_to_local_store, object_storage_asset, upsert_final_video_asset
from app.services.provider_prompt_adapter import adapt_provider_payload
from app.services.storage import storage_service
from app.services.video_edit import export_final_video

logger = logging.getLogger(__name__)


def _is_text_only(provider_name: str) -> bool:
    """查视频 provider 是否纯文本输入（延迟 import 打破循环）。"""
    from app.services.video_provider import get_config
    cfg = get_config(provider_name)
    return cfg.text_only if cfg else False


class ProviderDeferredError(RuntimeError):
    def __init__(self, message: str, *, stage: str, failed_tasks: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.stage = stage
        self.failed_tasks = failed_tasks


PRODUCTION_STAGES = [
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
]


class VideoProductionRunner:
    def __init__(
        self,
        db: AsyncSession,
        *,
        project_id: str,
        user_id: int,
        goal: str,
        episode: int = 1,
        scene: int = 1,
        target_duration_sec: int = 15,
        mode: str = "step",
        allow_local_placeholders: bool = False,
        provider_mode: str = "local",
        image_provider: str = "seedream",
        video_provider: str = "joy-echo",
        wait_provider_timeout_sec: int = 1800,
        max_image_tasks: int = 3,
        max_video_tasks: int = 3,
        user_tier: str = "free",
        agent_run_id: str = "",
        production_run_id: str = "",
        intent_brief: dict[str, Any] | None = None,
        semantic_plan: dict[str, Any] | None = None,
        constraint_packet: dict[str, Any] | None = None,
        verification_plan: dict[str, Any] | None = None,
        human_routing: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.project_id = project_id
        self.user_id = user_id
        self.goal = goal or "生成一条短剧预览"
        self.episode = max(1, int(episode or 1))
        self.scene = max(1, int(scene or 1))
        self.target_duration_sec = max(5, int(target_duration_sec or 15))
        self.mode = mode or "step"
        self.allow_local_placeholders = bool(allow_local_placeholders)
        self.provider_mode = _normalize_provider_mode(provider_mode)
        self.image_provider = str(image_provider or "seedream").strip().lower()
        self.video_provider = str(video_provider or "joy-echo").strip().lower()
        self.wait_provider_timeout_sec = max(30, int(wait_provider_timeout_sec or 1800))
        self.max_image_tasks = max(1, int(max_image_tasks or 15))
        self.max_video_tasks = max(1, int(max_video_tasks or 10))
        self.user_tier = str(user_tier or "free").strip().lower()
        self.agent_run_id = agent_run_id
        self.production_run_id = production_run_id
        self.semantic_control = {
            "intent_brief": intent_brief or {},
            "semantic_plan": semantic_plan or {},
            "constraint_packet": constraint_packet or {},
            "verification_plan": verification_plan or {},
            "human_routing": human_routing or {},
        }
        self.plan: dict[str, Any] = {}
        self.quality_report: dict[str, Any] = {}
        self.edit_strategy: dict[str, Any] = {}
        self.final_delivery_report: dict[str, Any] = {}
        self.final_task_id = ""
        self.final_video_url = ""

    async def run(self) -> dict[str, Any]:
        if not self.agent_run_id:
            self.agent_run_id = await create_agent_run(
                self.db,
                project_id=self.project_id,
                user_id=self.user_id,
                trigger_type="user_click",
                goal=self.goal,
                mode=self.mode,
                estimated_max_credits=0,
                allowed_max_credits=0,
                production_ledger={
                    "target_duration_sec": self.target_duration_sec,
                    "current_episode": self.episode,
                    "current_scene": self.scene,
                },
                meta={"runner": "VideoProductionRunner", "provider_mode": self.provider_mode},
            )
        if not self.production_run_id:
            self.production_run_id = await self._create_production_run()
        await self.db.commit()
        try:
            await self._stage(1, "read_context", self._read_context)
            await self._stage(2, "plan_story", self._plan_story)
            await self._stage(3, "lock_assets", self._lock_assets)
            await self._stage(4, "plan_shots", self._plan_shots)
            await self._stage(5, "generate_keyframes", self._generate_keyframes)
            await self._stage(6, "generate_videos", self._generate_videos)
            await self._stage(7, "generate_voice", self._generate_voice)
            await self._stage(8, "select_bgm", self._select_bgm)
            await self._stage(9, "generate_subtitles", self._generate_subtitles)
            await self._stage(10, "build_edit_strategy", self._build_edit_strategy)
            await self._stage(11, "ffmpeg_export", self._ffmpeg_export)
            await self._stage(12, "quality_check", self._quality_check)
            await self._stage(13, "writeback", self._writeback)
            status = "completed" if self.final_delivery_report.get("passed") else "blocked"
            await self._update_production_run(status=status, current_stage="writeback")
            await update_agent_run(
                self.db,
                run_id=self.agent_run_id,
                status=status,
                current_phase="writeback",
                summary="Video production run finished.",
                final_decision="final video ready" if status == "completed" else "final delivery blocked",
            )
            await self.db.commit()
            return self._response(status)
        except ProviderDeferredError as exc:
            await self._update_production_run(status="provider_waiting", current_stage=exc.stage)
            await update_agent_run(
                self.db,
                run_id=self.agent_run_id,
                status="dispatching",
                current_phase=exc.stage,
                summary=str(exc),
                final_decision="provider_waiting",
            )
            await publish_agent_event(
                self.db,
                run_id=self.agent_run_id,
                project_id=self.project_id,
                user_id=self.user_id,
                source="provider",
                event_type="risk",
                phase=exc.stage,
                title="Provider 暂时不可用，已进入等待恢复",
                detail=str(exc),
                status="deferred",
                progress=75,
                meta={"failed_tasks": exc.failed_tasks, "recommended_action": "retry_failed_videos"},
            )
            await self.db.commit()
            return self._response("provider_waiting")
        except Exception as exc:
            await self._update_production_run(status="failed", current_stage="failed")
            await update_agent_run(
                self.db,
                run_id=self.agent_run_id,
                status="failed",
                current_phase="failed",
                summary=f"Video production failed: {exc}",
                final_decision="failed",
            )
            await publish_agent_event(
                self.db,
                run_id=self.agent_run_id,
                project_id=self.project_id,
                user_id=self.user_id,
                source="brain",
                event_type="error",
                phase="failed",
                title="视频生产失败",
                detail=str(exc),
                status="failed",
                progress=100,
                meta={"error": str(exc), "recommended_action": "inspect_stage_and_retry"},
            )
            await self.db.commit()
            raise

    async def _stage(self, index: int, phase: str, func) -> None:
        await self._update_production_run(status="running", current_stage=phase)
        await update_agent_run(self.db, run_id=self.agent_run_id, status="running", current_phase=phase)
        step_id = await create_agent_step(
            self.db,
            run_id=self.agent_run_id,
            step_index=index,
            phase=phase,
            title=_stage_title(phase),
            status="running",
            input_summary=f"production_run={self.production_run_id}",
            decision_summary="开始执行阶段",
            output_summary="",
            meta={"production_run_id": self.production_run_id},
        )
        await publish_agent_event(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            step_id=step_id,
            source="brain" if phase not in {"ffmpeg_export", "writeback"} else "ffmpeg",
            event_type="tool_call" if phase == "ffmpeg_export" else "decision",
            phase=phase,
            title=_stage_title(phase),
            detail="开始执行",
            status="running",
            progress=min(98, index * 7),
            meta={"production_run_id": self.production_run_id},
        )
        output = await func()
        await create_agent_step(
            self.db,
            run_id=self.agent_run_id,
            step_index=index,
            phase=phase,
            title=_stage_title(phase),
            status="done",
            input_summary=f"production_run={self.production_run_id}",
            decision_summary="阶段完成",
            output_summary=_summary(output),
            meta={"production_run_id": self.production_run_id, "output": output},
        )
        await publish_agent_event(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            step_id=step_id,
            source="ledger" if phase == "writeback" else "brain",
            event_type="writeback" if phase == "writeback" else "tool_result",
            phase=phase,
            title=f"{_stage_title(phase)}完成",
            detail=_summary(output),
            status="done",
            progress=min(99, index * 7 + 4),
            meta={"production_run_id": self.production_run_id, "output": output},
        )
        await self.db.commit()

    async def _read_context(self) -> dict[str, Any]:
        rows = await self._load_shots()
        return {"existing_shot_count": len(rows), "target_duration_sec": self.target_duration_sec}

    async def _plan_story(self) -> dict[str, Any]:
        self.plan.update({
            "goal": self.goal,
            "episode": self.episode,
            "scene": self.scene,
            "target_duration_sec": self.target_duration_sec,
            "story": {
                "theme": self.goal,
                "structure": "opening-conflict-landing",
            },
        })
        await self._update_production_run(plan_json=self.plan)
        return self.plan["story"]

    async def _lock_assets(self) -> dict[str, Any]:
        ledger = {
            "locked_characters": [],
            "locked_locations": [],
            "locked_costumes": [],
            "locked_props": [],
            "reusable_assets": [],
            "rule": "existing assets first; generate only missing essentials",
        }
        self.plan["asset_ledger"] = ledger
        await self._update_production_run(plan_json=self.plan)
        return ledger

    async def _plan_shots(self) -> dict[str, Any]:
        rows = await self._load_shots()
        if not rows:
            raise RuntimeError("No storyboard shots found; run story planning before video production.")
        self.plan["shots"] = rows
        await self._update_production_run(plan_json=self.plan)
        return {"shot_count": len(rows), "duration_sec": sum(float(row.get("duration") or 0) for row in rows)}

    async def _generate_keyframes(self) -> dict[str, Any]:
        rows = await self._load_shots()
        missing = [row for row in rows if not str(row.get("selected_image") or "").strip()]
        if self.provider_mode == "real" and missing:
            queued = 0
            completed = 0
            credits_reserved = 0
            while missing:
                targets = missing[: self.max_image_tasks]
                dispatch = await self._dispatch_media_tasks(
                    targets,
                    task_type="image_gen",
                    operation="image_gen",
                    provider=self.image_provider,
                    queue="image",
                    celery_task="app.tasks.image_tasks.generate_image_task",
                    status_value="generating_image",
                    progress=38,
                )
                wait = await self._wait_for_child_tasks(dispatch["task_ids"], stage="generate_keyframes")
                queued += len(dispatch["task_ids"])
                completed += int(wait.get("done") or 0)
                credits_reserved += int(dispatch.get("credits_reserved") or 0)
                refreshed = await self._load_shots()
                remaining = [row for row in refreshed if not str(row.get("selected_image") or "").strip()]
                if len(remaining) >= len(missing):
                    raise RuntimeError(f"Keyframe generation finished but {len(remaining)} shot(s) still miss selected_image")
                missing = remaining
            return {
                "provider_mode": "real",
                "provider": self.image_provider,
                "queued": queued,
                "completed": completed,
                "credits_reserved": credits_reserved,
            }
        updated = 0
        for row in missing:
            if row.get("selected_image"):
                continue
            await self.db.execute(
                text(
                    """
                    UPDATE shot_rows
                    SET selected_image = COALESCE(NULLIF(selected_image, ''), :selected_image),
                        status = CASE WHEN selected_video IS NULL OR selected_video = '' THEN 'image_done' ELSE status END,
                        updated_at = NOW()
                    WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
                    """
                ),
                {
                    "project_id": self.project_id,
                    "user_id": self.user_id,
                    "shot_index": row["shot_index"],
                    "selected_image": f"local://planned-keyframe/{self.project_id}/{row['shot_index']}",
                },
            )
            updated += 1
        return {"provider_mode": self.provider_mode, "selected_image_written": updated}

    async def _generate_videos(self) -> dict[str, Any]:
        rows = await self._load_shots()
        missing = [row for row in rows if not str(row.get("selected_video") or "").strip()]
        if self.provider_mode == "real" and missing:
            missing_images = [row for row in missing if not str(row.get("selected_image") or "").strip()]
            if missing_images:
                raise RuntimeError(f"Cannot generate videos before keyframes: {len(missing_images)} shot(s) miss selected_image")
            queued = 0
            completed = 0
            credits_reserved = 0
            while missing:
                targets = missing[: self.max_video_tasks]
                dispatch = await self._dispatch_media_tasks(
                    targets,
                    task_type="video_gen",
                    operation=("video_gen_15s" if _is_text_only(self.video_provider) else "video_gen_5s"),
                    provider=self.video_provider,
                    queue="video",
                    celery_task="app.tasks.video_tasks.generate_video_task",
                    status_value="generating_video",
                    progress=48,
                )
                wait = await self._wait_for_child_tasks(dispatch["task_ids"], stage="generate_videos")
                queued += len(dispatch["task_ids"])
                completed += int(wait.get("done") or 0)
                credits_reserved += int(dispatch.get("credits_reserved") or 0)
                refreshed = await self._load_shots()
                remaining = [row for row in refreshed if not str(row.get("selected_video") or "").strip()]
                if len(remaining) >= len(missing):
                    raise RuntimeError(f"Video generation finished but {len(remaining)} shot(s) still miss selected_video")
                missing = remaining
            return {
                "provider_mode": "real",
                "provider": self.video_provider,
                "queued": queued,
                "completed": completed,
                "credits_reserved": credits_reserved,
            }
        if missing and not self.allow_local_placeholders:
            raise RuntimeError("No selected_video for some shots; enable local placeholders or run provider video generation first.")
        generated = []
        for row in missing:
            clip_path = await self._make_placeholder_clip(row)
            await self.db.execute(
                text(
                    """
                    UPDATE shot_rows
                    SET selected_video = :selected_video,
                        video_variants_json = COALESCE(video_variants_json, '[]'::jsonb) || CAST(:variant AS JSONB),
                        status = 'video_done',
                        updated_at = NOW()
                    WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
                    """
                ),
                {
                    "project_id": self.project_id,
                    "user_id": self.user_id,
                    "shot_index": row["shot_index"],
                    "selected_video": clip_path,
                    "variant": json.dumps([{"url": clip_path, "source": "local_placeholder"}], ensure_ascii=False),
                },
            )
            generated.append({"shot_index": row["shot_index"], "video_url": clip_path})
        return {"provider_mode": self.provider_mode, "generated_placeholder_videos": generated, "reused_existing": len(rows) - len(missing)}

    async def _generate_voice(self) -> dict[str, Any]:
        rows = await self._load_shots()
        dialogue_shots = [r for r in rows if str(r.get("prompt") or "").strip()]
        if not dialogue_shots:
            voice_plan = {"source": "clip_audio", "status": "no_dialogue", "dialogue_count": 0}
            self.plan["voice_plan"] = voice_plan
            await self._update_production_run(plan_json=self.plan)
            return voice_plan
        # 派发 TTS 任务——每个有台词的镜头生成一段配音
        tts_payloads = []
        for row in dialogue_shots:
            text = str(row.get("prompt") or "").strip()
            if not text:
                continue
            tts_payloads.append({
                "shot_index": row["shot_index"],
                "text": text[:500],  # TTS 单次限制
                "voice": "zh_female_shuangkuai",
                "speed": 1.0,
                "volume": 1.0,
            })
        if not tts_payloads:
            voice_plan = {"source": "clip_audio", "status": "no_dialogue", "dialogue_count": 0}
            self.plan["voice_plan"] = voice_plan
            await self._update_production_run(plan_json=self.plan)
            return voice_plan
        dispatch = await self._dispatch_media_tasks(
            dialogue_shots,
            task_type="tts_gen",
            operation="tts_synthesis",
            provider="doubao",
            queue="text",
            celery_task="app.tasks.tts_tasks.generate_tts_task",
            status_value="generating_voice",
            progress=54,
        )
        wait = await self._wait_for_child_tasks(dispatch["task_ids"], stage="generate_voice")
        # 为每个镜头记录 tts_audio_url（如果有结果）
        voice_urls = await self._load_tts_results(dispatch["task_ids"])
        voice_plan = {
            "source": "tts_generated",
            "status": "generated",
            "dialogue_count": len(tts_payloads),
            "generated_count": len(voice_urls),
            "task_ids": dispatch["task_ids"],
        }
        self.plan["voice_plan"] = voice_plan
        self.plan["voice_urls"] = voice_urls
        await self._update_production_run(plan_json=self.plan)
        return voice_plan

    async def _load_tts_results(self, task_ids: list[str]) -> list[dict[str, Any]]:
        if not task_ids:
            return []
        result = await self.db.execute(
            text(
                """
                SELECT task_id::text, (payload->>'shot_index')::int AS shot_index, result
                FROM tasks
                WHERE task_id IN :task_ids AND status = 'done' AND result IS NOT NULL
                """
            ).bindparams(bindparam("task_ids", expanding=True)),
            {"task_ids": task_ids},
        )
        rows = result.mappings().all()
        urls = []
        for row in rows:
            r = dict(row)
            res = r.get("result")
            if isinstance(res, dict) and res.get("audio_url"):
                urls.append({"shot_index": r["shot_index"], "audio_url": res["audio_url"], "task_id": r["task_id"]})
        return urls

    async def _select_bgm(self) -> dict[str, Any]:
        bgm_plan = {"source": "none", "mood": "cinematic", "volume": 0.15, "reason": "minimum loop keeps original/silent track"}
        self.plan["bgm_plan"] = bgm_plan
        await self._update_production_run(plan_json=self.plan)
        return bgm_plan

    async def _generate_subtitles(self) -> dict[str, Any]:
        rows = await self._load_shots()
        cursor = 0.0
        subtitles = []
        for row in rows:
            duration = float(row.get("duration") or 5.0)
            subtitles.append({
                "start": round(cursor, 3),
                "end": round(cursor + duration, 3),
                "text": str(row.get("prompt") or self.goal)[:42],
            })
            cursor += duration
        self.plan["subtitles"] = subtitles
        await self._update_production_run(plan_json=self.plan)
        return {"subtitle_count": len(subtitles), "duration_sec": round(cursor, 3)}

    async def _build_edit_strategy(self) -> dict[str, Any]:
        rows = await self._load_shots()
        self.edit_strategy = build_edit_strategy(goal=self.goal, shot_rows=rows, target_duration_sec=self.target_duration_sec)
        plan = _edit_plan_from_strategy(rows, self.edit_strategy)
        self.plan["edit_strategy"] = self.edit_strategy
        self.plan["final_edit_plan"] = plan
        await self.db.execute(
            text(
                """
                INSERT INTO final_edit_plans (project_id, user_id, plan_json)
                VALUES (:project_id, :user_id, CAST(:plan_json AS JSONB))
                ON CONFLICT (project_id, user_id)
                DO UPDATE SET plan_json = EXCLUDED.plan_json, updated_at = NOW()
                """
            ),
            {"project_id": self.project_id, "user_id": self.user_id, "plan_json": json.dumps(plan, ensure_ascii=False)},
        )
        await self._update_production_run(plan_json=self.plan, edit_strategy_json=self.edit_strategy)
        await record_agent_artifact(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            artifact_type="edit_strategy",
            summary=f"rhythm={self.edit_strategy.get('rhythm')}; techniques={len(self.edit_strategy.get('techniques') or [])}",
            meta=self.edit_strategy,
        )
        return {"rhythm": self.edit_strategy.get("rhythm"), "technique_count": len(self.edit_strategy.get("techniques") or [])}

    async def _ffmpeg_export(self) -> dict[str, Any]:
        plan = normalize_edit_plan(self.plan["final_edit_plan"])
        export_payload = export_payload_from_plan(plan)
        sources = [
            {
                "source": clip["video_url"],
                "trim_start": clip.get("trim_start", 0),
                "trim_end": clip.get("trim_end", 0),
            }
            for clip in export_payload["clips"]
        ]
        self.final_task_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                """
                INSERT INTO tasks (task_id, user_id, project_id, run_id, task_type, status, priority, payload, credits_reserved)
                VALUES (:task_id, :user_id, :project_id, CAST(:run_id AS UUID), 'video_production_export', 'running', 3, CAST(:payload AS JSONB), 0)
                """
            ),
            {
                "task_id": self.final_task_id,
                "user_id": self.user_id,
                "project_id": self.project_id,
                "run_id": self.agent_run_id,
                "payload": json.dumps({"production_run_id": self.production_run_id, "edit_plan_export": export_payload}, ensure_ascii=False),
            },
        )
        await self._ffmpeg_event("validate_plan", "验证剪辑方案", {"clip_count": len(sources), "subtitle_count": len(export_payload.get("subtitles") or [])}, 76)
        await self._ffmpeg_event("normalize_clips", "标准化视频片段", {"clip_count": len(sources)}, 80)
        await self._ffmpeg_event("concat_clips", "拼接镜头", {"transitions": export_payload.get("transitions") or []}, 84)
        await self._ffmpeg_event("mix_audio", "混合音频/BGM", {"bgm_path": export_payload.get("bgm_path"), "bgm_volume": export_payload.get("bgm_volume")}, 87)
        await self._ffmpeg_event("burn_subtitles", "烧录字幕", {"subtitles": export_payload.get("subtitles") or []}, 90)
        with tempfile.TemporaryDirectory(prefix=f"video_production_{self.final_task_id}_") as tmp_dir:
            final_path = os.path.join(tmp_dir, "final.mp4")
            export_info = export_final_video(
                sources,
                final_path,
                transitions=export_payload.get("transitions"),
                subtitles=export_payload.get("subtitles"),
                bgm_path=export_payload.get("bgm_path"),
                bgm_volume=export_payload.get("bgm_volume") or 0.15,
                preview=True,
            )
            try:
                oss_key = storage_service.upload_file(
                    final_path,
                    content_type="video/mp4",
                    folder=f"results/video_production/{self.project_id}",
                )
                asset_info = object_storage_asset(
                    file_url=storage_service.get_public_url(oss_key),
                    oss_key=oss_key,
                    file_size=int(export_info.get("file_size") or os.path.getsize(final_path)),
                )
            except Exception:
                asset_info = copy_final_video_to_local_store(
                    source_path=final_path,
                    project_id=self.project_id,
                    task_id=self.final_task_id,
                )
            self.final_video_url = str(asset_info["file_url"])
            await upsert_final_video_asset(
                self.db,
                task_id=self.final_task_id,
                project_id=self.project_id,
                user_id=self.user_id,
                asset=asset_info,
                metadata={"export_info": export_info, "production_run_id": self.production_run_id},
            )
            self.final_delivery_report = build_final_delivery_report(
                path=final_path,
                final_video_url=self.final_video_url,
                target_duration_sec=self.target_duration_sec,
                clip_count=int(export_info.get("clip_count") or 0),
                planned_clip_count=len(sources),
                subtitles=export_payload.get("subtitles"),
                audio_required=True,
            )
        await self._ffmpeg_event("export_mp4", "导出 MP4", {"final_video_url": self.final_video_url, **export_info}, 94)
        await self._ffmpeg_event("probe_output", "探测成片", self.final_delivery_report.get("probe") or {}, 96)
        await self.db.execute(
            text(
                """
                UPDATE tasks
                SET status = 'done', progress = 100, stage_text = 'Video production export complete',
                    result = CAST(:result AS JSONB), completed_at = NOW(), updated_at = NOW()
                WHERE task_id = CAST(:task_id AS UUID)
                """
            ),
            {
                "task_id": self.final_task_id,
                "result": json.dumps({
                    "final_url": self.final_video_url,
                    "duration_sec": export_info.get("duration_sec"),
                    "file_size": export_info.get("file_size"),
                }, ensure_ascii=False),
            },
        )
        await record_agent_artifact(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            task_id=self.final_task_id,
            artifact_type="final_video",
            uri=self.final_video_url,
            summary=f"duration={export_info.get('duration_sec')}s; clips={export_info.get('clip_count')}",
            meta={"delivery_report": self.final_delivery_report, "export_info": export_info},
        )
        await self._update_production_run(
            final_task_id=self.final_task_id,
            final_video_url=self.final_video_url,
            final_delivery_report_json=self.final_delivery_report,
        )
        return {"final_video_url": self.final_video_url, "delivery_passed": self.final_delivery_report.get("passed")}

    async def _quality_check(self) -> dict[str, Any]:
        self.quality_report = {
            "stage": "final",
            "passed": bool(self.final_delivery_report.get("passed")),
            "score": int(self.final_delivery_report.get("score") or 0),
            "issues": self.final_delivery_report.get("issues") or [],
            "retryable": bool(self.final_delivery_report.get("retryable")),
            "recommended_action": self.final_delivery_report.get("recommended_action"),
        }
        await self._update_production_run(quality_report_json=self.quality_report)
        return self.quality_report

    async def _writeback(self) -> dict[str, Any]:
        ledger = {
            "target_duration_sec": self.target_duration_sec,
            "generated_duration_sec": (self.final_delivery_report.get("probe") or {}).get("duration_sec", 0),
            "approved_duration_sec": (self.final_delivery_report.get("probe") or {}).get("duration_sec", 0) if self.final_delivery_report.get("passed") else 0,
            "current_episode": self.episode,
            "current_scene": self.scene,
            "current_minute": 0,
            "completed_scenes": [f"episode-{self.episode:02d}-scene-{self.scene:02d}"] if self.final_delivery_report.get("passed") else [],
            "active_scene": f"episode-{self.episode:02d}-scene-{self.scene:02d}",
            "next_scene": f"episode-{self.episode:02d}-scene-{self.scene + 1:02d}",
            "locked_assets": self.plan.get("asset_ledger", {}),
            "open_risks": self.final_delivery_report.get("issues") or [],
            "final_video_url": self.final_video_url,
        }
        await self.db.execute(
            text(
                """
                UPDATE agent_runs
                SET production_ledger = CAST(:ledger AS JSONB), updated_at = NOW()
                WHERE id = CAST(:run_id AS UUID)
                """
            ),
            {"run_id": self.agent_run_id, "ledger": json.dumps(ledger, ensure_ascii=False, default=str)},
        )
        return {"ledger_written": True, "final_video_url": self.final_video_url}

    async def _ffmpeg_event(self, phase: str, title: str, meta: dict[str, Any], progress: int) -> None:
        await publish_agent_event(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            task_id=self.final_task_id or None,
            source="ffmpeg",
            event_type="tool_call" if phase not in {"export_mp4", "probe_output"} else "tool_result",
            phase=phase,
            title=title,
            detail=_summary(meta),
            status="running" if phase not in {"export_mp4", "probe_output"} else "done",
            progress=progress,
            meta=meta,
        )

    # ------------------------------------------------------------------
    # Provider connectivity preflight
    # ------------------------------------------------------------------
    _PROVIDER_HEALTH_URLS: dict[str, str | None] = {}

    @classmethod
    def _provider_health_urls(cls) -> dict[str, str | None]:
        if cls._PROVIDER_HEALTH_URLS:
            return cls._PROVIDER_HEALTH_URLS
        settings = get_settings()
        base = settings.ark_base_url.rstrip("/")
        urls: dict[str, str | None] = {
            "seedance": f"{base}/models",
            "seedream": f"{base}/models",
            "doubao": f"{base}/models",
            "joy-echo": None,
            "ltx2.3": f"{settings.ltx_api_base_url.rstrip('/')}/health" if settings.ltx_api_base_url else None,
            "ltx": f"{settings.ltx_api_base_url.rstrip('/')}/health" if settings.ltx_api_base_url else None,
            "wan": f"{settings.inference_api_base_url.rstrip('/')}/v1/health" if settings.inference_api_base_url else None,
            "wan2.1": f"{settings.inference_api_base_url.rstrip('/')}/v1/health" if settings.inference_api_base_url else None,
        }
        cls._PROVIDER_HEALTH_URLS = urls
        return urls

    async def _check_provider_connectivity(self, provider: str, task_type: str) -> None:
        """Probe provider endpoint before dispatching tasks.

        Raises RuntimeError if provider is unreachable or returns 5xx.
        Non-critical providers (not in URL map) are skipped silently.
        """
        urls = self._provider_health_urls()
        url = urls.get(provider)
        if not url:
            # Unknown provider or not configured — skip check
            logger.debug("check_provider_connectivity: no URL for provider=%s, skipping", provider)
            return

        settings = get_settings()
        headers: dict[str, str] = {}
        if "ark" in url or "volces" in url:
            headers["Authorization"] = f"Bearer {settings.ark_api_key}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Use HEAD for lightweight check; fall back to GET for providers
                # that don't support HEAD on their health endpoint
                try:
                    resp = await client.head(url, headers=headers)
                except httpx.HTTPError:
                    resp = await client.get(url, headers=headers)
                if resp.status_code >= 500:
                    raise RuntimeError(f"Provider {provider} returned HTTP {resp.status_code} on {url}")
                if resp.status_code == 401 or resp.status_code == 403:
                    raise RuntimeError(f"Provider {provider} rejected API key (HTTP {resp.status_code})")
        except httpx.TimeoutException:
            raise RuntimeError(f"Provider {provider} connectivity check timed out after 5s")
        except httpx.ConnectError:
            raise RuntimeError(f"Provider {provider} is unreachable at {url}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise RuntimeError(f"Provider {provider} rejected API key (HTTP {exc.response.status_code})")
            raise RuntimeError(f"Provider {provider} HTTP error: {exc}")
        logger.debug("check_provider_connectivity: %s OK (%s)", provider, url)

    async def _dispatch_media_tasks(
        self,
        rows: list[dict[str, Any]],
        *,
        task_type: str,
        operation: str,
        provider: str,
        queue: str,
        celery_task: str,
        status_value: str,
        progress: int,
    ) -> dict[str, Any]:
        if not rows:
            return {"task_ids": [], "credits_reserved": 0}
        reusable = await self._existing_child_tasks(rows, task_type=task_type)
        reusable_task_ids = [item["task_id"] for item in reusable]
        reusable_shots = {int(item["shot_index"]) for item in reusable if item.get("shot_index") is not None}
        rows_to_dispatch = [row for row in rows if int(row.get("shot_index") or 0) not in reusable_shots]
        if not rows_to_dispatch:
            return {"task_ids": reusable_task_ids, "credits_reserved": 0}

        # --- Provider connectivity preflight ---
        await self._check_provider_connectivity(provider, task_type)

        # --- Key pool capacity preflight ---
        try:
            capacity = await asyncio.to_thread(check_provider_capacity, provider)
            available = capacity.available_slots
            if available <= 0:
                await publish_agent_event(
                    self.db,
                    run_id=self.agent_run_id,
                    project_id=self.project_id,
                    user_id=self.user_id,
                    source="brain",
                    event_type="risk",
                    phase="dispatch_preflight",
                    title=f"Provider {provider} 无可用容量",
                    detail=f"available_slots={available}, cooldown_keys={capacity.cooldown_keys}",
                    status="deferred",
                    progress=progress,
                    meta={"provider": provider, "available_slots": available, "cooldown": capacity.cooldown_keys},
                )
                raise ProviderDeferredError(
                    f"Provider {provider} has no capacity",
                    stage=f"dispatch_{task_type}",
                    failed_tasks=[{"shot_index": r.get("shot_index")} for r in rows_to_dispatch],
                )
            # Cap dispatch to available capacity
            if len(rows_to_dispatch) > available:
                logger.warning(
                    "dispatch_media_tasks: capping from %d to %d (provider %s capacity)",
                    len(rows_to_dispatch), available, provider,
                )
                rows_to_dispatch = rows_to_dispatch[:available]
        except ProviderDeferredError:
            raise
        except Exception as exc:
            logger.warning("dispatch_media_tasks: capacity check failed for %s: %s", provider, exc)
            # Non-fatal — proceed without capacity cap
        # --- End preflight ---

        unit_price = await credit_service.get_price(operation)
        total_credits = int(unit_price) * len(rows_to_dispatch)
        if not await ensure_run_budget(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            next_cost=total_credits,
            label=f"queue {len(rows)} {provider} {task_type} task(s)",
        ):
            raise RuntimeError(f"Run budget blocked {task_type}")
        await assert_cost_guard(self.db, user_id=self.user_id, credits_to_reserve=total_credits)
        transaction_ids: list[str] = []
        try:
            for _row in rows_to_dispatch:
                transaction_ids.append(await reserve_credits(self.user_id, operation, 1))
        except Exception:
            for transaction_id in transaction_ids:
                await credit_service.refund(transaction_id)
            raise

        priority = {"free": 5, "pro": 3, "enterprise": 1}.get(self.user_tier, 5)
        task_ids: list[str] = []
        payloads: list[dict[str, Any]] = []
        try:
            for index, row in enumerate(rows_to_dispatch):
                child_id = str(uuid.uuid4())
                task_ids.append(child_id)
                shot_row = {**row, "project_id": self.project_id, "user_id": self.user_id}
                payload: dict[str, Any] = {
                    "provider": provider,
                    "project_id": self.project_id,
                    "run_id": self.agent_run_id,
                    "shot_index": row["shot_index"],
                    "prompt": row.get("prompt") or "",
                    "duration": row.get("duration") or 5,
                    "shot_row": shot_row,
                }
                payload.update({key: value for key, value in self.semantic_control.items() if value})
                if task_type == "video_gen":
                    if not _is_text_only(provider):
                        payload["image_url"] = row.get("selected_image") or ""
                    if provider in {"joy-echo", "joy_echo", "joyai-echo", "joyai_echo"}:
                        payload["duration"] = max(30, int(payload.get("duration") or 30))
                        payload.update({"width": 1280, "height": 736, "timeout_seconds": 7200})
                    elif provider in {"ltx2.3", "wan", "wan2.1", "wan2_1"}:
                        payload.update({"width": 960, "height": 544, "steps": 10, "timeout_seconds": 3600})
                payload = adapt_provider_payload(payload, task_type=task_type, provider=provider)
                payloads.append(payload)
                db_payload = {**payload, "_credit_transaction_id": transaction_ids[index]}
                await self.db.execute(
                    text(
                        """
                        INSERT INTO tasks (
                            task_id, user_id, project_id, run_id, task_type,
                            status, priority, payload, credits_reserved, credit_transaction_id
                        )
                        VALUES (
                            :task_id, :user_id, :project_id, CAST(:run_id AS UUID), :task_type,
                            'queued', :priority, CAST(:payload AS JSONB), :credits, :credit_transaction_id
                        )
                        """
                    ),
                    {
                        "task_id": child_id,
                        "user_id": self.user_id,
                        "project_id": self.project_id,
                        "run_id": self.agent_run_id,
                        "task_type": task_type,
                        "priority": priority,
                        "payload": json.dumps(db_payload, ensure_ascii=False, default=str),
                        "credits": unit_price,
                        "credit_transaction_id": transaction_ids[index],
                    },
                )
                await self.db.execute(
                    text(
                        """
                        UPDATE shot_rows
                        SET status = :status, updated_at = NOW()
                        WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
                        """
                    ),
                    {
                        "status": status_value,
                        "project_id": self.project_id,
                        "user_id": self.user_id,
                        "shot_index": row["shot_index"],
                    },
                )
            await publish_agent_event(
                self.db,
                run_id=self.agent_run_id,
                project_id=self.project_id,
                user_id=self.user_id,
                source="brain",
                event_type="decision",
                phase="dispatch_instruction",
                title=f"决定派发 {provider} {task_type}",
                detail=f"queued={len(task_ids)}；credits_reserved={total_credits}",
                status="running",
                progress=progress,
                meta={
                    "provider_mode": "real",
                    "provider": provider,
                    "task_type": task_type,
                    "operation": operation,
                    "child_task_ids": task_ids,
                    "shot_indices": [row.get("shot_index") for row in rows_to_dispatch],
                    "reused_child_task_ids": reusable_task_ids,
                    "credits_reserved": total_credits,
                },
            )
            await update_agent_run(
                self.db,
                run_id=self.agent_run_id,
                status="dispatching",
                current_phase="dispatching",
                summary=f"{task_type} provider tasks dispatching.",
                final_decision=f"queued {len(task_ids)} {provider} {task_type} task(s)",
                reserved_credits_delta=total_credits,
            )
            await self.db.flush()  # 先 flush 不 commit，让 DB 能看到当前事务内的数据
        except Exception:
            await self.db.rollback()
            for transaction_id in transaction_ids:
                await credit_service.refund(transaction_id)
            raise

        # 先发 Celery 任务，再 commit DB——防止 Redis broker 不可用时已扣费但任务丢失
        for index, child_id in enumerate(task_ids):
            celery_app.send_task(
                celery_task,
                args=[child_id, str(self.user_id), payloads[index]],
                kwargs={"transaction_id": transaction_ids[index]},
                queue=queue,
                priority=priority,
            )
        # 所有 task 发送成功后才 commit——如果 send_task 抛异常，DB 事务自动回滚
        await self.db.commit()
        await publish_agent_event(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            source="queue",
            event_type="tool_call",
            phase="queued",
            title=f"已派发 {provider} {task_type}",
            detail=f"queue={queue}；tasks={len(task_ids)}",
            status="queued",
            progress=progress + 4,
            meta={
                "provider": provider,
                "task_type": task_type,
                "queue": queue,
                "child_task_ids": task_ids,
                "transaction_count": len(transaction_ids),
            },
        )
        await self.db.commit()
        return {"task_ids": [*reusable_task_ids, *task_ids], "credits_reserved": total_credits}

    async def _existing_child_tasks(self, rows: list[dict[str, Any]], *, task_type: str) -> list[dict[str, Any]]:
        shot_indices = [int(row.get("shot_index") or 0) for row in rows if int(row.get("shot_index") or 0) > 0]
        if not shot_indices:
            return []
        result = await self.db.execute(
            text(
                """
                SELECT DISTINCT ON ((payload->>'shot_index')::int)
                       task_id::text AS task_id,
                       (payload->>'shot_index')::int AS shot_index,
                       status,
                       created_at
                FROM tasks
                WHERE run_id = CAST(:run_id AS UUID)
                  AND user_id = :user_id
                  AND task_type = :task_type
                  AND payload->>'shot_index' IS NOT NULL
                  AND (payload->>'shot_index')::int IN :shot_indices
                  AND status NOT IN ('failed', 'dead_letter', 'cancelled')
                ORDER BY (payload->>'shot_index')::int, created_at DESC
                """
            ).bindparams(bindparam("shot_indices", expanding=True)),
            {
                "run_id": self.agent_run_id,
                "user_id": self.user_id,
                "task_type": task_type,
                "shot_indices": shot_indices,
            },
        )
        return [dict(row) for row in result.mappings().all()]

    async def _wait_for_child_tasks(self, task_ids: list[str], *, stage: str) -> dict[str, Any]:
        if not task_ids:
            return {"done": 0, "failed": 0}
        deadline = time.monotonic() + self.wait_provider_timeout_sec
        last_status_key = ""
        while time.monotonic() < deadline:
            result = await self.db.execute(
                text(
                    """
                    SELECT task_id::text AS task_id, task_type, status, progress, error_message, result,
                           payload, credit_transaction_id::text AS credit_transaction_id,
                           priority, created_at, updated_at
                    FROM tasks
                    WHERE task_id IN :task_ids
                    ORDER BY created_at ASC
                    """
                ).bindparams(bindparam("task_ids", expanding=True)),
                {"task_ids": task_ids},
            )
            rows = [dict(row) for row in result.mappings().all()]
            statuses = {str(row.get("task_id")): str(row.get("status") or "") for row in rows}
            status_key = json.dumps(statuses, sort_keys=True, ensure_ascii=False)
            if status_key != last_status_key:
                await publish_agent_event(
                    self.db,
                    run_id=self.agent_run_id,
                    project_id=self.project_id,
                    user_id=self.user_id,
                    source="worker",
                    event_type="tool_result",
                    phase=stage,
                    title="等待 provider 子任务回写",
                    detail=f"statuses={statuses}",
                    status="running",
                    progress=60 if stage == "generate_keyframes" else 68,
                    meta={"child_task_statuses": statuses, "child_task_count": len(task_ids)},
                )
                await self.db.commit()
                last_status_key = status_key
            failed = [row for row in rows if str(row.get("status") or "") in {"failed", "dead_letter", "cancelled"}]
            if failed:
                if _provider_failures_are_deferred(failed):
                    await publish_agent_event(
                        self.db,
                        run_id=self.agent_run_id,
                        project_id=self.project_id,
                        user_id=self.user_id,
                        source="provider",
                        event_type="risk",
                        phase=stage,
                        title="provider 资源暂时饱和",
                        detail=_summary({"failed": len(failed), "error": failed[0].get("error_message")}),
                        status="deferred",
                        progress=75,
                        meta={"failed_tasks": failed, "recovery": "retry_failed_videos"},
                    )
                    await self.db.commit()
                    raise ProviderDeferredError(
                        f"{stage} deferred because provider is temporarily saturated",
                        stage=stage,
                        failed_tasks=failed,
                    )
                await publish_agent_event(
                    self.db,
                    run_id=self.agent_run_id,
                    project_id=self.project_id,
                    user_id=self.user_id,
                    source="worker",
                    event_type="error",
                    phase=stage,
                    title="provider 子任务失败",
                    detail=_summary({"failed": len(failed), "error": failed[0].get("error_message")}),
                    status="failed",
                    progress=100,
                    meta={"failed_tasks": failed},
                )
                await self.db.commit()
                raise RuntimeError(f"{stage} child task failed: {failed[0].get('error_message')}")
            done = [row for row in rows if str(row.get("status") or "") == "done"]
            if len(done) == len(task_ids):
                return {"done": len(done), "failed": 0}
            await self._recover_stale_queued_child_tasks(rows, stage=stage)
            await self.db.commit()
            await asyncio.sleep(5)
        await publish_agent_event(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            source="worker",
            event_type="risk",
            phase=stage,
            title="provider 子任务等待超时",
            detail=f"timeout_sec={self.wait_provider_timeout_sec}",
            status="blocked",
            progress=100,
            meta={"child_task_ids": task_ids, "timeout_sec": self.wait_provider_timeout_sec},
        )
        await self.db.commit()
        raise TimeoutError(f"{stage} child tasks timed out after {self.wait_provider_timeout_sec}s")

    async def _recover_stale_queued_child_tasks(self, rows: list[dict[str, Any]], *, stage: str) -> None:
        stale_rows = [row for row in rows if self._is_stale_queued_child(row)]
        if not stale_rows:
            return
        recovered: list[str] = []
        for row in stale_rows:
            task_type = str(row.get("task_type") or "")
            celery_task, queue = _celery_route_for_child_task(task_type)
            if not celery_task or not queue:
                continue
            task_id = str(row.get("task_id") or "")
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            transaction_id = str(row.get("credit_transaction_id") or payload.get("_credit_transaction_id") or "").strip() or None
            priority = int(row.get("priority") or 5)
            celery_app.send_task(
                celery_task,
                args=[task_id, str(self.user_id), payload],
                kwargs={"transaction_id": transaction_id},
                queue=queue,
                priority=priority,
            )
            await self.db.execute(
                text(
                    """
                    UPDATE tasks
                    SET updated_at = NOW(),
                        stage_text = COALESCE(NULLIF(stage_text, ''), 'Requeued by production runner')
                    WHERE task_id = CAST(:task_id AS UUID)
                      AND status = 'queued'
                    """
                ),
                {"task_id": task_id},
            )
            recovered.append(task_id)
        if not recovered:
            return
        await publish_agent_event(
            self.db,
            run_id=self.agent_run_id,
            project_id=self.project_id,
            user_id=self.user_id,
            source="runner",
            event_type="tool_call",
            phase=stage,
            title="恢复未消费的 provider 子任务",
            detail=f"requeued={len(recovered)}",
            status="running",
            progress=62 if stage == "generate_keyframes" else 70,
            meta={"requeued_task_ids": recovered, "stage": stage},
        )

    @staticmethod
    def _is_stale_queued_child(row: dict[str, Any]) -> bool:
        if str(row.get("status") or "") != "queued":
            return False
        updated_at = row.get("updated_at") or row.get("created_at")
        if not hasattr(updated_at, "timestamp"):
            return False
        return (time.time() - float(updated_at.timestamp())) >= 30

    async def _create_production_run(self) -> str:
        result = await self.db.execute(
            text(
                """
                INSERT INTO video_production_runs (
                    project_id, user_id, agent_run_id, episode, scene,
                    target_duration_sec, status, current_stage, goal
                )
                VALUES (
                    :project_id, :user_id, CAST(:agent_run_id AS UUID), :episode, :scene,
                    :target_duration_sec, 'created', 'created', :goal
                )
                RETURNING id
                """
            ),
            {
                "project_id": self.project_id,
                "user_id": self.user_id,
                "agent_run_id": self.agent_run_id,
                "episode": self.episode,
                "scene": self.scene,
                "target_duration_sec": self.target_duration_sec,
                "goal": self.goal,
            },
        )
        return str(result.scalar_one())

    async def _update_production_run(self, **updates: Any) -> None:
        if not updates:
            return
        assignments = ["updated_at = NOW()"]
        params: dict[str, Any] = {"id": self.production_run_id}
        json_fields = {"plan_json", "quality_report_json", "edit_strategy_json", "final_delivery_report_json"}
        for field, value in updates.items():
            if value is None:
                continue
            if field in json_fields:
                assignments.append(f"{field} = CAST(:{field} AS JSONB)")
                params[field] = json.dumps(value, ensure_ascii=False, default=str)
            elif field == "final_task_id":
                assignments.append("final_task_id = CAST(:final_task_id AS UUID)")
                params[field] = value
            else:
                assignments.append(f"{field} = :{field}")
                params[field] = value
        await self.db.execute(text(f"UPDATE video_production_runs SET {', '.join(assignments)} WHERE id = CAST(:id AS UUID)"), params)

    async def _load_shots(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            text(
                """
                SELECT shot_index, prompt, duration, status, selected_image, selected_video,
                       video_variants_json, image_candidates_json
                FROM shot_rows
                WHERE project_id = :project_id AND user_id = :user_id
                ORDER BY shot_index ASC
                """
            ),
            {"project_id": self.project_id, "user_id": self.user_id},
        )
        return [dict(row) for row in result.mappings().all()]

    async def _create_default_shots(self) -> list[dict[str, Any]]:
        raise RuntimeError("Default template shot creation is disabled; run story planning before video production.")

    async def _make_placeholder_clip(self, row: dict[str, Any]) -> str:
        storage_dir = Path("storage") / "video_production" / self.project_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        shot_index = int(row.get("shot_index") or 1)
        duration = max(1.0, float(row.get("duration") or 5.0))
        output = storage_dir / f"production_run_{self.production_run_id}_shot_{shot_index}.mp4"
        color = ["0x1f2937", "0x374151", "0x111827"][shot_index % 3]
        cmd = [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=720x1280:d={duration}",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return str(output)

    def _response(self, status: str) -> dict[str, Any]:
        return {
            "ok": status == "completed",
            "status": status,
            "production_run_id": self.production_run_id,
            "agent_run_id": self.agent_run_id,
            "project_id": self.project_id,
            "final_task_id": self.final_task_id,
            "final_video_url": self.final_video_url,
            "quality_report": self.quality_report,
            "final_delivery_report": self.final_delivery_report,
            "edit_strategy": self.edit_strategy,
        }


def _provider_label(provider: str, task_type: str) -> str:
    text_value = f"{provider} {task_type}".lower()
    if "seedream" in text_value or "image" in text_value:
        return "Seedream ??"
    if "joy-echo" in text_value or "joy_echo" in text_value or "joyai-echo" in text_value or "joyai_echo" in text_value:
        return "Joy-Echo"
    if "ltx2.3" in text_value or "ltx" in text_value or "wan" in text_value:
        return "LTX 2.3"
    if "seedance" in text_value:
        return "Seedance"
    if "kling" in text_value:
        return "Kling"
    if "video" in text_value:
        return "LTX 2.3"
    return provider or task_type


def _celery_route_for_child_task(task_type: str) -> tuple[str, str]:
    routes = {
        "image_gen": ("app.tasks.image_tasks.generate_image_task", "image"),
        "video_gen": ("app.tasks.video_tasks.generate_video_task", "video"),
        "tts_gen": ("app.tasks.tts_tasks.generate_tts_task", "text"),
    }
    return routes.get(str(task_type or ""), ("", ""))


def _provider_failures_are_deferred(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    for row in rows:
        message = str(row.get("error_message") or "").lower()
        if not any(token in message for token in ("saturated", "backpressure", "too many requests", "429", "rate limit")):
            return False
    return True


def _edit_plan_from_strategy(rows: list[dict[str, Any]], strategy: dict[str, Any]) -> dict[str, Any]:
    subtitle_by_shot = {
        int(item.get("shot_index") or 0): item
        for item in strategy.get("subtitles", [])
        if isinstance(item, dict)
    }
    transition_by_pair = {
        (int(item.get("from") or 0), int(item.get("to") or 0)): item
        for item in strategy.get("transitions", [])
        if isinstance(item, dict)
    }
    clips = []
    for order, row in enumerate(rows, 1):
        shot_index = int(row.get("shot_index") or order)
        next_index = int(rows[order].get("shot_index") or order + 1) if order < len(rows) else 0
        transition = transition_by_pair.get((shot_index, next_index), {}).get("type") or "fade"
        clips.append({
            "shot_index": shot_index,
            "order": order,
            "enabled": True,
            "video_url": str(row.get("selected_video") or ""),
            "prompt": str(row.get("prompt") or ""),
            "duration": float(row.get("duration") or 5.0),
            "trim_start": 0.0,
            "trim_end": 0.0,
            "transition": transition,
            "subtitle": str(subtitle_by_shot.get(shot_index, {}).get("text") or row.get("prompt") or ""),
        })
    bgm_plan = strategy.get("bgm_plan") if isinstance(strategy.get("bgm_plan"), dict) else {}
    return {
        "version": 1,
        "settings": {
            "transition": "fade",
            "burn_subtitles": True,
            "subtitle_source": "strategy",
            "bgm_path": "" if bgm_plan.get("source") == "none" else str(bgm_plan.get("path") or ""),
            "bgm_volume": float(bgm_plan.get("volume") or 0.15),
            "cover_title": str(strategy.get("goal") or ""),
            "recipe_id": "agent_minimum_loop",
            "edit_strategy": strategy,
        },
        "clips": clips,
    }


def _split_duration(total: int, count: int) -> list[float]:
    base = max(1, int(total or 15)) / max(1, count)
    return [round(base, 3) for _ in range(count)]


def _normalize_provider_mode(value: str | None) -> str:
    mode = str(value or "local").strip().lower()
    if mode in {"real", "provider", "providers"}:
        return "real"
    return "local"


def _stage_title(phase: str) -> str:
    labels = {
        "read_context": "读取上下文",
        "plan_story": "规划剧情",
        "lock_assets": "锁定资产",
        "plan_shots": "规划分镜",
        "generate_keyframes": "生成/确认关键帧",
        "generate_videos": "生成/确认视频",
        "generate_voice": "规划配音",
        "select_bgm": "选择 BGM",
        "generate_subtitles": "生成字幕",
        "build_edit_strategy": "生成剪辑策略",
        "ffmpeg_export": "FFmpeg 导出",
        "quality_check": "成片质检",
        "writeback": "回写账本",
    }
    return labels.get(phase, phase)


def _summary(value: Any) -> str:
    if isinstance(value, dict):
        return "；".join(f"{key}={value[key]}" for key in list(value.keys())[:4])
    return str(value)
