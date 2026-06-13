"""媒体处理类 Celery 任务 — 场景生成、图生视频、分镜板、配音、导出、封面、日报。

对应 checklist #19-32 的后台逻辑。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.celery_app import celery_app
from app.services.key_pool import key_pool
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
    resolve_callable,
)

LOGGER = logging.getLogger(__name__)
MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# #19 场景生成
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, queue="video", soft_time_limit=600, time_limit=900, acks_late=True)
def generate_scene_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(task_id, status="running", progress=10, stage_text="提交视频生成...",
                     retry_count=self.request.retries, celery_task_id=self.request.id)
    key_name: str | None = None
    try:
        prompt = payload.get("prompt", "")
        duration = int(payload.get("duration", 5))
        image_url = payload.get("image_url")

        key_name, api_key = key_pool.acquire("seedance")
        publish_progress(task_id, status="running", progress=30, stage_text="Seedance 生成中...",
                         retry_count=self.request.retries, celery_task_id=self.request.id)
        call = resolve_callable("app.services.seedance", ("generate_video", "generate"))
        gen_payload = {"prompt": prompt, "duration": duration}
        if image_url:
            gen_payload["image_url"] = image_url
        result = invoke_callable(call, gen_payload, api_key=api_key, task_id=task_id, user_id=user_id)
        result = persist_result_to_oss(result, "video")

        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if key_name:
            key_pool.report_error(key_name, str(exc))
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(task_id, status="retrying", progress=10,
                             stage_text=f"重试场景生成 ({self.request.retries + 1}/{MAX_RETRIES})",
                             retry_count=self.request.retries + 1, celery_task_id=self.request.id)
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(task_id, exc, retry_count=self.request.retries,
                       credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id)
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


# ---------------------------------------------------------------------------
# #21 图生视频
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, queue="video", soft_time_limit=600, time_limit=900, acks_late=True)
def image_to_video_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(task_id, status="running", progress=10, stage_text="图生视频准备中...",
                     retry_count=self.request.retries, celery_task_id=self.request.id)
    key_name: str | None = None
    try:
        image_url = payload.get("image_url", "")
        prompt = payload.get("prompt", "slow cinematic rotation with dynamic lighting")
        duration = int(payload.get("duration", 5))

        key_name, api_key = key_pool.acquire("seedance")
        publish_progress(task_id, status="running", progress=30, stage_text="Seedance 图生视频...",
                         retry_count=self.request.retries, celery_task_id=self.request.id)
        call = resolve_callable("app.services.seedance", ("generate_video", "generate"))
        result = invoke_callable(call, {
            "prompt": prompt, "duration": duration, "image_url": image_url,
        }, api_key=api_key, task_id=task_id, user_id=user_id)
        result = persist_result_to_oss(result, "video")

        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if key_name:
            key_pool.report_error(key_name, str(exc))
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(task_id, status="retrying", progress=10,
                             stage_text=f"重试图生视频 ({self.request.retries + 1}/{MAX_RETRIES})",
                             retry_count=self.request.retries + 1, celery_task_id=self.request.id)
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(task_id, exc, retry_count=self.request.retries,
                       credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id)
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


# ---------------------------------------------------------------------------
# #22 分镜板生成（多镜头串行 + 可选 TTS + 拼接）
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, queue="video", soft_time_limit=1800, time_limit=2400, acks_late=True)
def storyboard_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    clips = payload.get("clips", [])
    concat = payload.get("concat", True)
    total = len(clips)

    publish_progress(task_id, status="running", progress=5, stage_text=f"分镜板启动，共 {total} 段",
                     retry_count=self.request.retries, celery_task_id=self.request.id)
    try:
        clip_results: list[dict] = []
        for i, clip in enumerate(clips):
            step_progress = int(5 + (85 * i / max(total, 1)))
            publish_progress(task_id, status="running", progress=step_progress,
                             stage_text=f"生成镜头 {i+1}/{total}",
                             retry_count=self.request.retries, celery_task_id=self.request.id)

            prompt = clip.get("prompt", "")
            duration = int(clip.get("duration", 5))
            image_url = clip.get("image_url")

            key_name, api_key = key_pool.acquire("seedance")
            try:
                call = resolve_callable("app.services.seedance", ("generate_video", "generate"))
                gen_payload: dict[str, Any] = {"prompt": prompt, "duration": duration}
                if image_url:
                    gen_payload["image_url"] = image_url
                result = invoke_callable(call, gen_payload, api_key=api_key, task_id=task_id, user_id=user_id)
                result = persist_result_to_oss(result, "video")
                clip_results.append({"index": i, "result": result})
            finally:
                key_pool.release(key_name)

        maybe_charge(transaction_id)
        output = {"clips": clip_results, "total": total, "concat": concat}
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(task_id, status="retrying", progress=5,
                             stage_text=f"重试分镜板 ({self.request.retries + 1}/{MAX_RETRIES})",
                             retry_count=self.request.retries + 1, celery_task_id=self.request.id)
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(task_id, exc, retry_count=self.request.retries,
                       credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id)
        raise


# ---------------------------------------------------------------------------
# #25 配音生成
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, queue="text", soft_time_limit=120, time_limit=180, acks_late=True)
def voiceover_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(task_id, status="running", progress=20, stage_text="TTS 合成中...",
                     retry_count=self.request.retries, celery_task_id=self.request.id)
    key_name: str | None = None
    try:
        text = payload.get("text", "")
        voice = payload.get("voice", "")

        key_name, api_key = key_pool.acquire("doubao")
        call = resolve_callable("app.services.tts", ("generate_speech", "generate_tts", "generate"))
        result = invoke_callable(call, {"text": text, "voice": voice}, api_key=api_key, task_id=task_id, user_id=user_id)
        result = persist_result_to_oss(result, "tts")

        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if key_name:
            key_pool.report_error(key_name, str(exc))
        if retryable and self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(task_id, exc, retry_count=self.request.retries,
                       credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id)
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


# ---------------------------------------------------------------------------
# #29 封面生成
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, queue="image", soft_time_limit=120, time_limit=180, acks_late=True)
def generate_cover_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(task_id, status="running", progress=20, stage_text="生成封面...",
                     retry_count=self.request.retries, celery_task_id=self.request.id)
    try:
        video_url = payload.get("video_url", "")
        title = payload.get("title")

        key_name, api_key = key_pool.acquire("seedream")
        try:
            call = resolve_callable("app.services.seedream", ("generate_image", "call_seedream", "generate"))
            prompt = f"Video cover frame, cinematic, {title or 'dramatic scene'}"
            result = invoke_callable(call, {"prompt": prompt}, api_key=api_key, task_id=task_id, user_id=user_id)
            result = persist_result_to_oss(result, "image")
        finally:
            key_pool.release(key_name)

        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(task_id, exc, retry_count=self.request.retries,
                       credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id)
        raise


# ---------------------------------------------------------------------------
# #31 金价日报生成（多镜头 + TTS + 拼接）
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, queue="video", soft_time_limit=1800, time_limit=2400, acks_late=True)
def daily_report_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(task_id, status="running", progress=5, stage_text="金价日报启动...",
                     retry_count=self.request.retries, celery_task_id=self.request.id)
    try:
        prompts = payload.get("prompts", [])
        tts_script = payload.get("tts_script", "")
        total = len(prompts)

        clip_results: list[dict] = []
        for i, prompt in enumerate(prompts):
            step_progress = int(5 + (70 * i / max(total, 1)))
            publish_progress(task_id, status="running", progress=step_progress,
                             stage_text=f"生成画面 {i+1}/{total}",
                             retry_count=self.request.retries, celery_task_id=self.request.id)

            key_name, api_key = key_pool.acquire("seedance")
            try:
                call = resolve_callable("app.services.seedance", ("generate_video", "generate"))
                result = invoke_callable(call, {"prompt": prompt, "duration": 4},
                                         api_key=api_key, task_id=task_id, user_id=user_id)
                result = persist_result_to_oss(result, "video")
                clip_results.append(result)
            finally:
                key_pool.release(key_name)

        publish_progress(task_id, status="running", progress=80, stage_text="TTS 合成配音...",
                         retry_count=self.request.retries, celery_task_id=self.request.id)
        tts_result = None
        if tts_script:
            tts_key, tts_api_key = key_pool.acquire("doubao")
            try:
                tts_call = resolve_callable("app.services.tts", ("generate_speech", "generate_tts", "generate"))
                tts_result = invoke_callable(tts_call, {"text": tts_script},
                                             api_key=tts_api_key, task_id=task_id, user_id=user_id)
                tts_result = persist_result_to_oss(tts_result, "tts")
            finally:
                key_pool.release(tts_key)

        maybe_charge(transaction_id)
        output = {"clips": clip_results, "tts": tts_result, "tts_script": tts_script}
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(task_id, exc, retry_count=self.request.retries,
                       credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id)
        raise


# ---------------------------------------------------------------------------
# #24 导演一键生成（director_generate）
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, queue="default", soft_time_limit=900, time_limit=1200, acks_late=True)
def director_generate_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    """导演一键生成：chat → 参考图 → 视频，全链路串行。"""
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    publish_progress(task_id, status="running", progress=5, stage_text="导演编排中...",
                     retry_count=self.request.retries, celery_task_id=self.request.id)
    try:
        from app.services.director_chat_engine import run_director_chat

        message = payload.get("message", payload.get("idea", ""))
        project_id = payload.get("project_id", "")
        preset_key = payload.get("preset_key", "")

        chat_result = run_director_chat(
            message=message, project_id=project_id, preset_key=preset_key,
        )
        shots = chat_result.get("shots", [])

        publish_progress(task_id, status="running", progress=30, stage_text=f"生成 {len(shots)} 个镜头视频...",
                         retry_count=self.request.retries, celery_task_id=self.request.id)

        video_results: list[dict] = []
        for i, shot in enumerate(shots):
            step_progress = int(30 + (60 * i / max(len(shots), 1)))
            publish_progress(task_id, status="running", progress=step_progress,
                             stage_text=f"视频 {i+1}/{len(shots)}",
                             retry_count=self.request.retries, celery_task_id=self.request.id)

            key_name, api_key = key_pool.acquire("seedance")
            try:
                call = resolve_callable("app.services.seedance", ("generate_video", "generate"))
                vid_result = invoke_callable(call, {
                    "prompt": shot.get("prompt", ""),
                    "duration": shot.get("duration", 5),
                }, api_key=api_key, task_id=task_id, user_id=user_id)
                vid_result = persist_result_to_oss(vid_result, "video")
                video_results.append({"index": shot.get("index", i+1), "video": vid_result})
            except Exception as shot_exc:
                LOGGER.warning("Shot %d failed: %s", i, shot_exc)
                video_results.append({"index": shot.get("index", i+1), "error": str(shot_exc)})
            finally:
                key_pool.release(key_name)

        maybe_charge(transaction_id)
        output = {**chat_result, "video_results": video_results}
        publish_complete(task_id, output, celery_task_id=self.request.id)
        return output
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if retryable and self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))
        refunded = maybe_refund(transaction_id)
        publish_failed(task_id, exc, retry_count=self.request.retries,
                       credits_refunded=refunded, dead_letter=retryable, celery_task_id=self.request.id)
        raise
