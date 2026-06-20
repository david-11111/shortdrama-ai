from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from typing import Any

from app.celery_app import celery_app
from app.db import AsyncSessionLocal
from app.services.director_parsing import parse_shot_rows
from app.services.key_pool import key_pool
from app.services.final_video_storage import copy_final_video_to_local_store, object_storage_asset, upsert_final_video_asset
from app.services.post_generation_review import media_candidate, review_image_candidate, review_video_candidate
from app.services.provider_prompt_adapter import adapt_provider_payload
from app.services.production_entrypoint import assert_agent_run_entrypoint_for_task
from app.services.ref_resolver import build_image_generation_payload, build_video_generation_payload
from app.tasks._shared import (
    build_retry_delay,
    get_task_snapshot,
    invoke_callable,
    is_retryable_exception,
    maybe_charge,
    maybe_refund,
    persist_result_to_oss,
    publish_complete,
    publish_failed,
    publish_progress,
    result_url,
    resolve_callable,
    update_shot_error,
    update_shot_media,
)

LOGGER = logging.getLogger(__name__)
MAX_RETRIES = 3


@celery_app.task(bind=True, queue="default", soft_time_limit=1800, time_limit=2400, acks_late=True)
def video_production_run_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]
    publish_progress(
        task_id,
        status="running",
        progress=5,
        stage_text="Starting VideoProductionRunner",
        retry_count=self.request.retries,
        celery_task_id=self.request.id,
    )
    try:
        assert_agent_run_entrypoint_for_task(
            "video_production_run",
            payload,
            db_run_id=str((snapshot or {}).get("run_id") or "").strip() or None,
        )
        result = asyncio.run(_run_video_production(payload))
        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < 1:
            publish_progress(
                task_id,
                status="retrying",
                progress=8,
                stage_text="Retrying VideoProductionRunner",
                retry_count=self.request.retries + 1,
                celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id,
            exc,
            retry_count=self.request.retries,
            credits_refunded=refunded,
            dead_letter=retryable,
            celery_task_id=self.request.id,
        )
        raise


async def _run_video_production(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.video_production_runner import VideoProductionRunner

    async with AsyncSessionLocal() as session:
        runner = VideoProductionRunner(
            session,
            project_id=str(payload.get("project_id") or ""),
            user_id=int(payload.get("user_id") or 0),
            goal=str(payload.get("goal") or "生成一条15秒短剧预览"),
            episode=int(payload.get("episode") or 1),
            scene=int(payload.get("scene") or 1),
            target_duration_sec=int(payload.get("target_duration_sec") or 15),
            mode=str(payload.get("mode") or "step"),
            allow_local_placeholders=bool(payload.get("allow_local_placeholders", False)),
            provider_mode=str(payload.get("provider_mode") or "local"),
            image_provider=str(payload.get("image_provider") or "seedream"),
            video_provider=str(payload.get("video_provider") or "joy-echo"),
            wait_provider_timeout_sec=int(payload.get("wait_provider_timeout_sec") or 1800),
            max_image_tasks=int(payload.get("max_image_tasks") or 3),
            max_video_tasks=int(payload.get("max_video_tasks") or 3),
            user_tier=str(payload.get("user_tier") or "free"),
            agent_run_id=str(payload.get("agent_run_id") or ""),
            production_run_id=str(payload.get("production_run_id") or ""),
            intent_brief=payload.get("intent_brief") if isinstance(payload.get("intent_brief"), dict) else None,
            semantic_plan=payload.get("semantic_plan") if isinstance(payload.get("semantic_plan"), dict) else None,
            constraint_packet=payload.get("constraint_packet") if isinstance(payload.get("constraint_packet"), dict) else None,
            verification_plan=payload.get("verification_plan") if isinstance(payload.get("verification_plan"), dict) else None,
            human_routing=payload.get("human_routing") if isinstance(payload.get("human_routing"), dict) else None,
        )
        return await runner.run()


def _persist_workspace_result(project_id: str, result: dict[str, Any], *, source: str, reason: str) -> None:
    if not project_id or not isinstance(result, dict):
        return
    try:
        from app.services.project_workspace import persist_director_result_to_workspace

        workspace_result = persist_director_result_to_workspace(
            project_id,
            result,
            source=source,
            reason=reason,
        )
        if isinstance(workspace_result, dict):
            result["workspace_writes"] = workspace_result.get("writes", [])
    except Exception:
        LOGGER.warning("Failed to persist director result to workspace", exc_info=True)


def _sanitize_reference_description(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    # Remove instruction/marketing phrases that often trigger infographic or collage layouts.
    banned_patterns = [
        r"短视频",
        r"视频",
        r"剧本",
        r"分镜",
        r"展示",
        r"好处",
        r"教程",
        r"指南",
        r"海报",
        r"宣传",
        r"广告",
        r"封面",
        r"标题",
        r"文案",
        r"字幕",
        r"步骤",
        r"前后对比",
        r"before\s*and\s*after",
        r"before",
        r"after",
        r"benefits?",
        r"guide",
        r"tutorial",
        r"infographic",
        r"collage",
        r"英语",
        r"英文",
        r"English",
    ]
    for pattern in banned_patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[，,。.!！?？;；:：/\\|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]
@celery_app.task(bind=True, queue="text", soft_time_limit=300, time_limit=360, acks_late=True)
def director_chat_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(
        task_id, status="running", progress=10,
        stage_text="编译需求中...",
        retry_count=self.request.retries, celery_task_id=self.request.id,
    )
    try:
        messages = payload.get("messages", [])
        project_id = payload.get("project_id", "")

        from app.services.director_chat_engine import run_director_chat

        publish_progress(
            task_id, status="running", progress=30,
            stage_text="导演生成中...",
            retry_count=self.request.retries, celery_task_id=self.request.id,
        )
        def _progress_cb(progress: int, stage_text: str) -> None:
            publish_progress(
                task_id,
                status="running",
                progress=max(10, min(94, int(progress))),
                stage_text=stage_text,
                retry_count=self.request.retries,
                celery_task_id=self.request.id,
            )

        result = run_director_chat(
            message=messages[-1]["content"] if messages else payload.get("topic", ""),
            project_id=project_id,
            history=messages[:-1] if len(messages) > 1 else [],
            preset_key=payload.get("preset_key", ""),
            shots_in=payload.get("shots"),
            output_options=payload.get("output_options"),
            progress_cb=_progress_cb,
        )

        publish_progress(
            task_id, status="running", progress=95,
            stage_text="保存分镜...",
            retry_count=self.request.retries, celery_task_id=self.request.id,
        )
        if result.get("shot_rows") and project_id:
            asyncio.run(_save_shot_rows(project_id, result["shot_rows"], user_id))
            _persist_workspace_result(
                project_id,
                result,
                source="director_chat",
                reason="director chat generated production plan",
            )

        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id, status="retrying", progress=10,
                stage_text=f"Retrying director chat ({self.request.retries + 1}/{MAX_RETRIES})",
                retry_count=self.request.retries + 1, celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id, exc, retry_count=self.request.retries,
            credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id,
        )
        raise


@celery_app.task(bind=True, queue="text", soft_time_limit=180, time_limit=240, acks_late=True)
def director_script_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(
        task_id, status="running", progress=10,
        stage_text="Analyzing story requirements",
        retry_count=self.request.retries, celery_task_id=self.request.id,
    )
    key_name: str | None = None
    try:
        project_id = payload.get("project_id", "")
        topic = payload.get("topic", "")
        style = payload.get("style", "default")
        shot_count = payload.get("shot_count", 4)

        system_prompt = (
            f"You are a professional short-drama director. "
            f"Generate a {shot_count}-shot storyboard script in JSON array format. "
            f"Style: {style}. Each shot must have: shot_number, scene_description, "
            f"camera_angle, character_action, dialogue, duration_seconds."
        )
        doubao_payload: dict[str, Any] = {
            "system_prompt": system_prompt,
            "prompt": topic,
            "temperature": 0.8,
            "max_tokens": 4096,
            "intent_brief": payload.get("intent_brief") if isinstance(payload.get("intent_brief"), dict) else {},
            "semantic_plan": payload.get("semantic_plan") if isinstance(payload.get("semantic_plan"), dict) else {},
            "constraint_packet": payload.get("constraint_packet") if isinstance(payload.get("constraint_packet"), dict) else {},
            "verification_plan": payload.get("verification_plan") if isinstance(payload.get("verification_plan"), dict) else {},
            "human_routing": payload.get("human_routing") if isinstance(payload.get("human_routing"), dict) else {},
        }
        doubao_payload = adapt_provider_payload(doubao_payload, task_type="generate_story_plan", provider="doubao")

        key_name, api_key = key_pool.acquire("doubao")
        publish_progress(
            task_id, status="running", progress=30,
            stage_text="Generating script with doubao",
            retry_count=self.request.retries, celery_task_id=self.request.id,
        )
        call = resolve_callable("app.services.doubao", ("generate_text", "generate"))
        result = invoke_callable(call, doubao_payload, api_key=api_key, task_id=task_id, user_id=user_id)

        shot_rows = parse_shot_rows(result.get("text", ""), shot_count)

        publish_progress(
            task_id, status="running", progress=80,
            stage_text="Script generated, saving shots",
            retry_count=self.request.retries, celery_task_id=self.request.id,
        )
        asyncio.run(_save_shot_rows(project_id, shot_rows, user_id))

        maybe_charge(transaction_id)
        output = {
            "shot_rows": shot_rows,
            "project_id": project_id,
            "tokens_used": result.get("tokens_used", 0),
            "billing_usage": result.get("billing_usage"),
        }
        _persist_workspace_result(
            project_id,
            output,
            source="director_script",
            reason="director script generated storyboard",
        )
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if key_name and not isinstance(exc, TimeoutError):
            key_pool.report_error(key_name, str(exc))
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id, status="retrying", progress=10,
                stage_text=f"Retrying script generation ({self.request.retries + 1}/{MAX_RETRIES})",
                retry_count=self.request.retries + 1, celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id, exc, retry_count=self.request.retries,
            credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id,
        )
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


@celery_app.task(bind=True, queue="text", soft_time_limit=300, time_limit=360, acks_late=True)
def director_final_cut_ai_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(
        task_id,
        status="running",
        progress=10,
        stage_text="读取剪辑方案...",
        retry_count=self.request.retries,
        celery_task_id=self.request.id,
    )
    try:
        project_id = str((payload or {}).get("project_id") or "").strip()
        recipe_id = str((payload or {}).get("recipe_id") or "").strip()
        instruction = str((payload or {}).get("instruction") or "")
        if not project_id:
            raise ValueError("project_id is required")
        if not recipe_id:
            raise ValueError("recipe_id is required")

        from app.services.final_cut_recipes import get_final_cut_recipe

        recipe = get_final_cut_recipe(recipe_id)
        if not recipe:
            raise ValueError("Final cut recipe not found")

        current_plan = asyncio.run(_load_current_final_edit_plan_for_task(project_id, int(user_id)))
        if not current_plan.get("clips"):
            raise ValueError("No produced clips found for final cut planning")

        publish_progress(
            task_id,
            status="running",
            progress=35,
            stage_text="AI 规划剪辑步骤...",
            retry_count=self.request.retries,
            celery_task_id=self.request.id,
        )
        result = _generate_final_cut_plan_with_doubao_for_task(recipe, current_plan, instruction)

        publish_progress(
            task_id,
            status="running",
            progress=85,
            stage_text="保存可执行剪辑方案...",
            retry_count=self.request.retries,
            celery_task_id=self.request.id,
        )
        asyncio.run(_save_final_edit_plan_for_task(project_id, int(user_id), result["plan"]))

        output = {
            "ok": True,
            "project_id": project_id,
            "recipe_id": recipe_id,
            "plan": result["plan"],
            "explanation": result.get("explanation", []),
            "warnings": result.get("warnings", []),
            "tokens_used": result.get("tokens_used", 0),
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("completion_tokens", 0),
            "model": result.get("model"),
            "billing_usage": result.get("billing_usage"),
        }
        maybe_charge(transaction_id)
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id,
                status="retrying",
                progress=15,
                stage_text=f"AI 剪辑规划重试中 ({self.request.retries + 1}/{MAX_RETRIES})",
                retry_count=self.request.retries + 1,
                celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id,
            exc,
            retry_count=self.request.retries,
            credits_refunded=refunded,
            dead_letter=retryable,
            celery_task_id=self.request.id,
        )
        raise


@celery_app.task(bind=True, queue="default", soft_time_limit=300, time_limit=360, acks_late=True)
def director_prepare_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(
        task_id, status="running", progress=10,
        stage_text="Loading shot rows",
        retry_count=self.request.retries, celery_task_id=self.request.id,
    )
    try:
        project_id = payload.get("project_id", "")
        shot_indices = payload.get("shot_indices")

        shot_rows = asyncio.run(_load_shot_rows(project_id, shot_indices))
        ready = []
        blocked = []

        for i, row in enumerate(shot_rows):
            try:
                resolved = build_image_generation_payload(row, strict=False)
                ready.append({"index": i, "resolved": resolved})
            except Exception as e:
                blocked.append({"index": i, "reason": str(e)})

        publish_progress(
            task_id, status="running", progress=90,
            stage_text="Preparation complete",
            retry_count=self.request.retries, celery_task_id=self.request.id,
        )
        output = {"ready_count": len(ready), "blocked_count": len(blocked), "details": ready + blocked}
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id, status="retrying", progress=10,
                stage_text=f"Retrying prepare ({self.request.retries + 1}/{MAX_RETRIES})",
                retry_count=self.request.retries + 1, celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id, exc, retry_count=self.request.retries,
            credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id,
        )
        raise


@celery_app.task(bind=True, queue="default", soft_time_limit=3000, time_limit=3600, acks_late=True)
def director_produce_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(
        task_id, status="running", progress=5,
        stage_text="Starting production pipeline",
        retry_count=self.request.retries, celery_task_id=self.request.id,
    )
    try:
        project_id = payload.get("project_id", "")
        shot_indices = payload.get("shot_indices")
        skip_images = payload.get("skip_images", False)
        provider = payload.get("provider", "joy-echo")
        anchor_locks = payload.get("anchor_locks") if isinstance(payload.get("anchor_locks"), dict) else {}
        semantic_control = {
            key: payload.get(key)
            for key in ("intent_brief", "semantic_plan", "constraint_packet", "verification_plan", "human_routing")
            if isinstance(payload.get(key), dict)
        }

        shot_rows = asyncio.run(_load_shot_rows(project_id, shot_indices))
        total = len(shot_rows)
        if total == 0:
            raise ValueError("No shot rows to produce")

        completed = 0
        failed = 0
        results: list[dict[str, Any]] = []

        for i, row in enumerate(shot_rows):
            step_progress = int(5 + (90 * i / max(total, 1)))
            try:
                row_payload = dict(row)
                if anchor_locks:
                    row_payload.update({
                        "lock_character": bool(anchor_locks.get("lock_character", False)),
                        "lock_scene": bool(anchor_locks.get("lock_scene", False)),
                        "lock_costume": bool(anchor_locks.get("lock_costume", False)),
                        "lock_prop": bool(anchor_locks.get("lock_prop", False)),
                    })
                resolved_img = build_image_generation_payload(row_payload, strict=False)
                resolved_img.update(semantic_control)
                resolved_img = adapt_provider_payload(resolved_img, task_type="image_gen", provider="seedream")
                resolved_vid = build_video_generation_payload(row_payload, strict=False)
                resolved_vid.update(semantic_control)

                if not skip_images:
                    publish_progress(
                        task_id, status="running", progress=step_progress,
                        stage_text=f"Generating image {i + 1}/{total}",
                        retry_count=self.request.retries, celery_task_id=self.request.id,
                    )
                    img_key_name, img_api_key = key_pool.acquire("seedream")
                    try:
                        img_call = resolve_callable(
                            "app.services.seedream",
                            ("generate_image", "call_seedream", "submit_image_generation", "generate"),
                        )
                        img_result = invoke_callable(
                            img_call, resolved_img, api_key=img_api_key, task_id=task_id, user_id=user_id,
                        )
                        img_result = persist_result_to_oss(img_result, "image")
                        img_url = result_url(img_result)
                        img_review = review_image_candidate(row_payload, img_url)
                        asyncio.run(update_shot_media(
                            project_id,
                            int(row["shot_index"]),
                            user_id,
                            image_url=img_url,
                            image_candidate=media_candidate(img_url, img_review),
                            status="image_done",
                        ))
                    finally:
                        key_pool.release(img_key_name)
                else:
                    img_result = None

                publish_progress(
                    task_id, status="running", progress=step_progress + 5,
                    stage_text=f"Generating video {i + 1}/{total}",
                    retry_count=self.request.retries, celery_task_id=self.request.id,
                )
                vid_payload = dict(resolved_vid)
                vid_payload["provider"] = provider
                if vid_payload.get("image") and not vid_payload.get("image_url"):
                    vid_payload["image_url"] = vid_payload["image"]
                if img_result and img_result.get("url"):
                    vid_payload["image_url"] = img_result["url"]
                    vid_payload.setdefault("ref_images", []).append(img_result["url"])
                vid_payload = adapt_provider_payload(vid_payload, task_type="video_gen", provider=provider)

                if provider in {
                    "joy-echo",
                    "joy_echo",
                    "joyai-echo",
                    "joyai_echo",
                }:
                    from app.services.joy_echo_official import generate_joy_echo_official_video

                    vid_result = generate_joy_echo_official_video(vid_payload, provider=provider)
                elif provider in {
                    "ltx2.3",
                    "ltx",
                    "wan",
                    "wan2.1",
                    "wan2_1",
                    "comfyui",
                }:
                    from app.services.comfy_video import generate_comfy_video

                    vid_result = generate_comfy_video(vid_payload, provider=provider)
                else:
                    service_map = {"seedance": ("app.services.seedance", "seedance"), "kling": ("app.services.kling", "kling")}
                    module_name, pool_service = service_map.get(provider, ("app.services.kling", "kling"))
                    vid_key_name, vid_api_key = key_pool.acquire(pool_service)
                    try:
                        vid_call = resolve_callable(module_name, ("generate_video", "generate"))
                        vid_result = invoke_callable(
                            vid_call, vid_payload, api_key=vid_api_key, task_id=task_id, user_id=user_id,
                        )
                    finally:
                        key_pool.release(vid_key_name)
                vid_result = persist_result_to_oss(vid_result, "video")
                vid_url = result_url(vid_result)
                vid_review_payload = {**row_payload, "selected_image": vid_payload.get("image_url") or row_payload.get("selected_image")}
                vid_review = review_video_candidate(vid_review_payload, vid_url)
                asyncio.run(update_shot_media(
                    project_id,
                    int(row["shot_index"]),
                    user_id,
                    video_url=vid_url,
                    video_candidate=media_candidate(vid_url, vid_review),
                    status="video_done",
                ))

                results.append({"index": row["shot_index"], "image": img_result, "video": vid_result})
                completed += 1
            except Exception as shot_exc:
                LOGGER.warning("Shot %d failed: %s", i, shot_exc)
                asyncio.run(update_shot_error(project_id, int(row["shot_index"]), user_id, str(shot_exc)))
                results.append({"index": row["shot_index"], "error": str(shot_exc)})
                failed += 1

        if completed == 0 and failed:
            raise RuntimeError("All production shots failed")

        maybe_charge(transaction_id)
        output = {"completed": completed, "failed": failed, "results": results}
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id, status="retrying", progress=5,
                stage_text=f"Retrying production ({self.request.retries + 1}/{MAX_RETRIES})",
                retry_count=self.request.retries + 1, celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id, exc, retry_count=self.request.retries,
            credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id,
        )
        raise


@celery_app.task(bind=True, queue="default", soft_time_limit=1800, time_limit=2400, acks_late=True)
def director_export_final_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    return _run_director_export_video_task(
        self,
        task_id,
        user_id,
        payload,
        transaction_id=transaction_id,
        preview=False,
    )


@celery_app.task(bind=True, queue="default", soft_time_limit=900, time_limit=1200, acks_late=True)
def director_export_preview_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    return _run_director_export_video_task(
        self,
        task_id,
        user_id,
        payload,
        transaction_id=transaction_id,
        preview=True,
    )


def _run_director_export_video_task(
    task,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    *,
    transaction_id: str | None,
    preview: bool,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    export_label = "preview" if preview else "final"
    publish_progress(
        task_id, status="running", progress=8,
        stage_text=f"Collecting produced video clips for {export_label}",
        retry_count=task.request.retries, celery_task_id=task.request.id,
    )
    try:
        project_id = str(payload.get("project_id") or "").strip()
        shot_indices = payload.get("shot_indices")
        transitions = payload.get("transitions")
        subtitles = payload.get("subtitles")
        bgm_path = payload.get("bgm_path")
        bgm_volume = payload.get("bgm_volume", 0.15)
        if not project_id:
            raise ValueError("project_id is required")

        edit_export = payload.get("edit_plan_export") if isinstance(payload.get("edit_plan_export"), dict) else None
        if edit_export:
            rows = [
                {
                    "shot_index": clip.get("shot_index"),
                    "selected_video": clip.get("video_url"),
                    "trim_start": clip.get("trim_start", 0),
                    "trim_end": clip.get("trim_end", 0),
                    "transition": clip.get("transition", "fade"),
                    "subtitle": clip.get("subtitle") or clip.get("prompt") or "",
                    "duration": clip.get("duration"),
                }
                for clip in edit_export.get("clips", [])
                if clip.get("video_url")
            ]
            transitions = edit_export.get("transitions")
            subtitles = edit_export.get("subtitles")
            bgm_path = edit_export.get("bgm_path")
            bgm_volume = edit_export.get("bgm_volume", bgm_volume)
        else:
            rows = asyncio.run(_load_export_video_sources(project_id, int(user_id), shot_indices))
        if not rows:
            raise ValueError("No produced videos found for export")

        sources = [
            {
                "source": row["selected_video"],
                "trim_start": row.get("trim_start", 0),
                "trim_end": row.get("trim_end", 0),
            }
            for row in rows
        ]
        publish_progress(
            task_id, status="running", progress=25,
            stage_text=f"Preparing {len(sources)} clips for FFmpeg",
            retry_count=task.request.retries, celery_task_id=task.request.id,
        )

        from app.services.storage import storage_service
        from app.services.video_edit import export_final_video

        delivery_report: dict[str, Any] = {}
        with tempfile.TemporaryDirectory(prefix=f"director_export_{task_id}_") as tmp_dir:
            final_path = os.path.join(tmp_dir, "preview.mp4" if preview else "final.mp4")
            export_info = export_final_video(
                sources,
                final_path,
                transitions=transitions,
                subtitles=subtitles,
                bgm_path=bgm_path,
                bgm_volume=bgm_volume,
                preview=preview,
            )

            publish_progress(
                task_id, status="running", progress=88,
                stage_text=f"Uploading {export_label} video",
                retry_count=task.request.retries, celery_task_id=task.request.id,
            )
            try:
                key = storage_service.upload_file(
                    final_path,
                    content_type="video/mp4",
                    folder=f"results/director_{export_label}/{project_id}",
                )
                final_url = storage_service.get_public_url(key)
                storage_mode = "oss"
                asset_info = object_storage_asset(
                    file_url=final_url,
                    oss_key=key,
                    file_size=int(export_info["file_size"]),
                )
            except Exception as upload_exc:
                key = None
                asset_info = copy_final_video_to_local_store(
                    source_path=final_path,
                    project_id=project_id,
                    task_id=task_id,
                )
                final_url = str(asset_info["file_url"])
                storage_mode = str(asset_info["storage_mode"])
                publish_progress(
                    task_id, status="running", progress=94,
                    stage_text=f"OSS upload unavailable; stored {export_label} video as local file ({upload_exc})",
                    retry_count=task.request.retries, celery_task_id=task.request.id,
                )

            from app.services.final_delivery import build_final_delivery_report

            delivery_report = build_final_delivery_report(
                path=final_path,
                final_video_url=final_url,
                target_duration_sec=int(payload.get("target_duration_sec") or 0),
                clip_count=len(sources),
                planned_clip_count=int(payload.get("clip_count") or len(sources)),
                subtitles=subtitles,
                audio_required=not preview,
            )

        maybe_charge(transaction_id)
        output = {
            "project_id": project_id,
            "final_url": final_url,
            "preview_url": final_url if preview else None,
            "oss_key": key,
            "storage_mode": storage_mode,
            "export_kind": export_label,
            "clip_count": len(sources),
            "shots": [{"shot_index": row["shot_index"], "video_url": row["selected_video"]} for row in rows],
            "file_size": export_info["file_size"],
            "duration_sec": export_info["duration_sec"],
            "delivery_report": delivery_report,
            "final_video_asset": asset_info,
        }
        asyncio.run(_record_director_export_result(
            project_id=project_id,
            user_id=int(user_id),
            task_id=task_id,
            output=output,
            preview=preview,
            payload=payload,
        ))
        publish_complete(task_id, output, celery_task_id=task.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and task.request.retries < 1:
            publish_progress(
                task_id, status="retrying", progress=10,
                stage_text=f"Retrying {export_label} export ({task.request.retries + 1}/1)",
                retry_count=task.request.retries + 1, celery_task_id=task.request.id,
            )
            raise task.retry(exc=exc, countdown=build_retry_delay(task.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id, exc, retry_count=task.request.retries,
            credits_refunded=refunded, dead_letter=retryable, celery_task_id=task.request.id,
        )
        raise


@celery_app.task(bind=True, queue="image", soft_time_limit=300, time_limit=360, acks_late=True)
def director_reference_images_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(
        task_id, status="running", progress=10,
        stage_text="Generating reference views",
        retry_count=self.request.retries, celery_task_id=self.request.id,
    )
    key_name: str | None = None
    try:
        project_id = payload.get("project_id", "")
        character_description = payload.get("character_description", "")
        sanitized_description = _sanitize_reference_description(character_description)
        identity_description = sanitized_description or str(character_description or "").strip()
        views = payload.get("views", ["front", "side", "expression_smile", "full_body"])
        asset_type = payload.get("asset_type", "character")

        key_name, api_key = key_pool.acquire("seedream")
        generated_views: dict[str, Any] = {}
        billing_usage: list[dict[str, Any]] = []
        total_views = len(views)

        view_prompt_map = {
            "front": "front-facing headshot portrait, centered composition, direct eye contact",
            "side": "side profile portrait, 90-degree profile angle, same identity",
            "expression_smile": "close-up portrait with natural smile expression, same identity",
            "full_body": "full-body portrait, standing pose, entire figure visible",
        }
        view_size_map = {
            "full_body": (1536, 2400),
        }
        negative_prompt = (
            "collage, grid, split screen, contact sheet, multiple panels, comic layout, infographic, "
            "text, caption, watermark, logo, duplicated face, multiple persons"
        )

        for i, view in enumerate(views):
            step_progress = int(10 + (70 * i / max(total_views, 1)))
            publish_progress(
                task_id, status="running", progress=step_progress,
                stage_text=f"Generating {view} view ({i + 1}/{total_views})",
                retry_count=self.request.retries, celery_task_id=self.request.id,
            )
            width, height = view_size_map.get(view, (2048, 2048))
            view_prompt = view_prompt_map.get(view, f"{view} portrait, same identity")
            img_payload: dict[str, Any] = {
                "prompt": (
                    f"{identity_description}. {view_prompt}. "
                    "ultra-realistic cinematic portrait photo, single image only, one person only, "
                    "clean plain white studio background, no text, no title, no labels, no panel layout, "
                    "consistent facial identity across views."
                ),
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
            }
            call = resolve_callable(
                "app.services.seedream",
                ("generate_image", "call_seedream", "submit_image_generation", "generate"),
            )
            img_result = invoke_callable(call, img_payload, api_key=api_key, task_id=task_id, user_id=user_id)
            img_result = persist_result_to_oss(img_result, "image")
            generated_views[view] = img_result.get("url", "")
            if isinstance(img_result.get("billing_usage"), dict):
                billing_usage.append(img_result["billing_usage"])

        publish_progress(
            task_id, status="running", progress=85,
            stage_text="Saving asset pack",
            retry_count=self.request.retries, celery_task_id=self.request.id,
        )
        primary_view = "front" if "front" in generated_views else views[0]
        pack_metadata = {
            "pack": True,
            "primary": primary_view,
            "views": generated_views,
            "asset_type": asset_type,
            "asset_kind": asset_type,
            "entity_type": asset_type,
            "lineage_role": "source",
            "generation_method": "seedream_reference_pack",
            "locked_traits": ["face", "hair", "body_shape"] if asset_type == "character" else [],
        }
        asset_id = asyncio.run(_save_asset_pack(project_id, user_id, pack_metadata))

        maybe_charge(transaction_id)
        output = {"asset_id": asset_id, "views": generated_views, "billing_usage": billing_usage}
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if key_name and not isinstance(exc, TimeoutError):
            key_pool.report_error(key_name, str(exc))
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id, status="retrying", progress=10,
                stage_text=f"Retrying reference images ({self.request.retries + 1}/{MAX_RETRIES})",
                retry_count=self.request.retries + 1, celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id, exc, retry_count=self.request.retries,
            credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id,
        )
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_memory_context(project_id: str) -> str:
    try:
        rows = asyncio.run(_query_memory(project_id))
        return "\n".join(rows) if rows else ""
    except Exception as exc:
        LOGGER.warning("Failed to load memory context for project %s: %s", project_id, exc)
        return ""


async def _query_memory(project_id: str) -> list[str]:
    from sqlalchemy import text as sql_text
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sql_text("SELECT content FROM project_memory WHERE project_id = :pid ORDER BY created_at DESC LIMIT 20"),
            {"pid": project_id},
        )
        return [row[0] for row in result.fetchall()]


async def _load_current_final_edit_plan_for_task(project_id: str, user_id: int) -> dict[str, Any]:
    from sqlalchemy import text as sql_text
    from app.services.final_edit import build_default_edit_plan, merge_plan_with_shots

    async with AsyncSessionLocal() as session:
        owner = await session.execute(
            sql_text("SELECT 1 FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
            {"project_id": project_id, "user_id": user_id},
        )
        if not owner.fetchone():
            raise ValueError("Project not found")

        shot_result = await session.execute(
            sql_text(
                """
                SELECT shot_index, prompt, duration, status, selected_video
                FROM shot_rows
                WHERE project_id = :project_id AND user_id = :user_id
                ORDER BY shot_index ASC
                """
            ),
            {"project_id": project_id, "user_id": user_id},
        )
        shot_rows = [dict(row) for row in shot_result.mappings().fetchall()]
        plan_result = await session.execute(
            sql_text(
                """
                SELECT plan_json
                FROM final_edit_plans
                WHERE project_id = :project_id AND user_id = :user_id
                """
            ),
            {"project_id": project_id, "user_id": user_id},
        )
        row = plan_result.fetchone()
        if not row:
            return build_default_edit_plan(shot_rows)
        return merge_plan_with_shots(row.plan_json, shot_rows)


async def _save_final_edit_plan_for_task(project_id: str, user_id: int, plan: dict[str, Any]) -> None:
    from sqlalchemy import text as sql_text
    from app.services.final_edit import normalize_edit_plan

    normalized = normalize_edit_plan(plan)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                sql_text(
                    """
                    INSERT INTO final_edit_plans (project_id, user_id, plan_json)
                    VALUES (:project_id, :user_id, CAST(:plan_json AS JSONB))
                    ON CONFLICT (project_id, user_id)
                    DO UPDATE SET plan_json = EXCLUDED.plan_json, updated_at = NOW()
                    """
                ),
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "plan_json": json.dumps(normalized, ensure_ascii=False),
                },
            )


def _generate_final_cut_plan_with_doubao_for_task(
    recipe: dict[str, Any],
    current_plan: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    from app.services.final_cut_ai import generate_final_cut_plan

    key_name: str | None = None
    try:
        key_name, api_key = key_pool.acquire("doubao")
        return generate_final_cut_plan(
            api_key,
            recipe=recipe,
            current_plan=current_plan,
            user_instruction=instruction,
        )
    except Exception as exc:
        if key_name:
            key_pool.report_error(key_name, str(exc))
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


async def _save_shot_rows(project_id: str, shot_rows: list[dict[str, Any]], user_id: str) -> None:
    from sqlalchemy import text as sql_text
    user_pk = int(user_id) if str(user_id).isdigit() else 0
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for row in shot_rows:
                shot_index = int(row.get("shot_index", row.get("shot_number", 0)))
                prompt = row.get("prompt", "")
                if not prompt:
                    parts = [p for p in [
                        row.get("scene_description"),
                        f"Camera: {row['camera_angle']}" if row.get("camera_angle") else None,
                        f"Action: {row['character_action']}" if row.get("character_action") else None,
                        f"Dialogue: {row['dialogue']}" if row.get("dialogue") else None,
                    ] if p]
                    prompt = " | ".join(parts) if parts else row.get("raw_text", "")
                duration = float(row.get("duration", row.get("duration_seconds", 5.0)))
                await session.execute(
                    sql_text(
                        """
                        INSERT INTO shot_rows (project_id, user_id, shot_index, prompt, duration)
                        VALUES (:project_id, :user_id, :shot_index, :prompt, :duration)
                        ON CONFLICT (project_id, shot_index) DO UPDATE
                        SET prompt = EXCLUDED.prompt,
                            duration = EXCLUDED.duration,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "project_id": project_id,
                        "user_id": user_pk,
                        "shot_index": shot_index,
                        "prompt": prompt,
                        "duration": duration,
                    },
                )


async def _load_shot_rows(project_id: str, shot_indices: list[int] | None = None) -> list[dict[str, Any]]:
    from sqlalchemy import bindparam, text as sql_text
    async with AsyncSessionLocal() as session:
        if shot_indices:
            result = await session.execute(
                sql_text(
                    "SELECT shot_index, prompt, duration, status, selected_image, selected_video, "
                    "character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json "
                    "FROM shot_rows WHERE project_id = :pid AND shot_index IN :indices "
                    "ORDER BY shot_index"
                ).bindparams(bindparam("indices", expanding=True)),
                {"pid": project_id, "indices": shot_indices},
            )
        else:
            result = await session.execute(
                sql_text(
                    "SELECT shot_index, prompt, duration, status, selected_image, selected_video, "
                    "character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json "
                    "FROM shot_rows WHERE project_id = :pid ORDER BY shot_index"
                ),
                {"pid": project_id},
            )
        return [
            {
                "project_id": project_id,
                "shot_index": r["shot_index"],
                "prompt": r["prompt"],
                "duration": r["duration"],
                "status": r["status"],
                "selected_image": r["selected_image"],
                "selected_video": r["selected_video"],
                "character_refs": r["character_refs_json"] or [],
                "scene_refs": r["scene_refs_json"] or [],
                "prop_refs": r["prop_refs_json"] or [],
                "costume_refs": r["costume_refs_json"] or [],
                "style_refs": r["style_refs_json"] or [],
            }
            for r in result.mappings().fetchall()
        ]


async def _load_export_video_sources(
    project_id: str,
    user_id: int,
    shot_indices: list[int] | None = None,
) -> list[dict[str, Any]]:
    from sqlalchemy import bindparam, text as sql_text

    async with AsyncSessionLocal() as session:
        query = sql_text(
            """
            SELECT shot_index, selected_video
            FROM shot_rows
            WHERE project_id = :pid
              AND user_id = :uid
              AND selected_video IS NOT NULL
              AND selected_video <> ''
            ORDER BY shot_index
            """
        )
        params: dict[str, Any] = {"pid": project_id, "uid": user_id}
        if shot_indices:
            query = sql_text(
                """
                SELECT shot_index, selected_video
                FROM shot_rows
                WHERE project_id = :pid
                  AND user_id = :uid
                  AND shot_index IN :indices
                  AND selected_video IS NOT NULL
                  AND selected_video <> ''
                ORDER BY shot_index
                """
            ).bindparams(bindparam("indices", expanding=True))
            params["indices"] = shot_indices

        result = await session.execute(query, params)
        return [dict(row) for row in result.mappings().fetchall()]


async def _record_director_export_result(
    *,
    project_id: str,
    user_id: int,
    task_id: str,
    output: dict[str, Any],
    preview: bool,
    payload: dict[str, Any],
) -> None:
    from sqlalchemy import text as sql_text

    export_key = "preview_export" if preview else "final_export"
    report_key = "preview_delivery_report" if preview else "final_delivery_report"
    export_record = {
        "task_id": task_id,
        "url": output.get("preview_url") or output.get("final_url") or "",
        "storage_mode": output.get("storage_mode") or "",
        "oss_key": output.get("oss_key"),
        "clip_count": output.get("clip_count") or 0,
        "file_size": output.get("file_size") or 0,
        "duration_sec": output.get("duration_sec") or 0,
        "status": "done",
    }
    delivery_report = output.get("delivery_report") if isinstance(output.get("delivery_report"), dict) else {}
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                sql_text(
                    """
                    SELECT plan_json
                    FROM final_edit_plans
                    WHERE project_id = :project_id AND user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"project_id": project_id, "user_id": user_id},
            )
            row = result.mappings().first()
            plan = row.get("plan_json") if row and isinstance(row.get("plan_json"), dict) else {}
            if not plan and isinstance(payload.get("edit_plan"), dict):
                plan = dict(payload["edit_plan"])
            settings = plan.get("settings") if isinstance(plan.get("settings"), dict) else {}
            plan["settings"] = {
                **settings,
                export_key: export_record,
                report_key: delivery_report,
            }
            await session.execute(
                sql_text(
                    """
                    INSERT INTO final_edit_plans (project_id, user_id, plan_json)
                    VALUES (:project_id, :user_id, CAST(:plan_json AS JSONB))
                    ON CONFLICT (project_id, user_id)
                    DO UPDATE SET plan_json = EXCLUDED.plan_json, updated_at = NOW()
                    """
                ),
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "plan_json": json.dumps(plan, ensure_ascii=False, default=str),
                },
            )
            asset = output.get("final_video_asset")
            if isinstance(asset, dict):
                await upsert_final_video_asset(
                    session,
                    task_id=task_id,
                    project_id=project_id,
                    user_id=user_id,
                    asset=asset,
                    metadata={
                        "export_kind": output.get("export_kind"),
                        "duration_sec": output.get("duration_sec"),
                        "clip_count": output.get("clip_count"),
                    },
                )
            if not preview:
                await session.execute(
                    sql_text(
                        """
                        UPDATE video_production_runs
                        SET final_task_id = CAST(:task_id AS UUID),
                            final_video_url = :final_url,
                            final_delivery_report_json = CAST(:report AS JSONB),
                            current_stage = 'quality_check',
                            status = :status,
                            updated_at = NOW()
                        WHERE id = (
                            SELECT id
                            FROM video_production_runs
                            WHERE project_id = :project_id AND user_id = :user_id
                            ORDER BY updated_at DESC
                            LIMIT 1
                        )
                        """
                    ),
                    {
                        "task_id": task_id,
                        "final_url": output.get("final_url") or "",
                        "report": json.dumps(delivery_report, ensure_ascii=False, default=str),
                        "status": "completed" if delivery_report.get("passed") else "blocked",
                        "project_id": project_id,
                        "user_id": user_id,
                    },
                )


async def _save_asset_pack(project_id: str, user_id: str, metadata: dict[str, Any]) -> str:
    import uuid
    from sqlalchemy import text as sql_text
    asset_id = str(uuid.uuid4()).replace("-", "")[:32]
    user_pk = int(user_id) if str(user_id).isdigit() else 0
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                sql_text(
                    """
                    INSERT INTO assets (asset_id, project_id, user_id, asset_type, file_url, metadata_json)
                    VALUES (:asset_id, :project_id, :user_id, :asset_type, :file_url, CAST(:metadata_json AS JSONB))
                    """
                ),
                {
                    "asset_id": asset_id,
                    "project_id": project_id,
                    "user_id": user_pk,
                    "asset_type": metadata.get("asset_type", "character"),
                    "file_url": _primary_asset_pack_url(metadata),
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                },
            )
    return asset_id


def _primary_asset_pack_url(metadata: dict[str, Any]) -> str:
    views = metadata.get("views")
    if not isinstance(views, dict):
        return ""
    primary = str(metadata.get("primary") or "")
    if primary and isinstance(views.get(primary), str):
        return views[primary]
    for value in views.values():
        if isinstance(value, str) and value:
            return value
    return ""
