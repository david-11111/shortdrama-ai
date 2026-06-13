# T16 指令 — worker 终端

## 你的身份

你是 `worker` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

添加 Kling 视频生成服务 + 火山引擎 TTS 语音合成服务，并更新任务路由支持 provider 选择。

## 分支

（如果 git 报错可忽略，直接在当前分支工作）

## 需要创建/修改的文件

### 1. `app/config.py` — 添加 Kling + TTS 配置

在 Settings 类中添加：

```python
    # Kling (可灵) 视频生成
    kling_api_keys: str = ""
    kling_base_url: str = "https://api.klingai.com/v1"
    kling_access_key: str = ""
    kling_secret_key: str = ""

    # 火山引擎 TTS
    ark_tts_model: str = "volcano-tts-mega"

    @property
    def kling_api_key_list(self) -> list[str]:
        return [key.strip() for key in self.kling_api_keys.split(",") if key.strip()]
```

### 2. `app/services/kling.py`（新建）

Kling 视频生成 — 异步任务模式（提交 → 轮询 → 获取结果）：

```python
"""
Kling (可灵) 视频生成服务。

API 文档: https://docs.klingai.com
认证方式: API Key 或 Access Key + Secret Key (JWT)
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5
MAX_POLL_TIME = 600


def _raise_kling_error(response: httpx.Response, stage: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()[:500]
        raise RuntimeError(
            f"Kling {stage} failed with status={response.status_code}: {detail or exc!s}"
        ) from exc


def generate_video(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用 Kling API 生成视频。

    payload 期望字段:
      - prompt: str
      - duration: int (5/10)
      - mode: str ("std" / "pro")
      - image_url: str (可选，图生视频)

    返回:
      - url: str (视频下载地址)
      - duration: int
      - task_id: str
    """
    settings = get_settings()
    base_url = settings.kling_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 构建请求
    request_body = {
        "prompt": payload.get("prompt", ""),
        "duration": str(payload.get("duration", 5)),
        "mode": payload.get("mode", "std"),
    }

    # 图生视频
    if payload.get("image_url"):
        request_body["image"] = payload["image_url"]

    # 分辨率
    if payload.get("resolution"):
        aspect_map = {"1080p": "16:9", "720p": "16:9", "square": "1:1"}
        request_body["aspect_ratio"] = aspect_map.get(payload["resolution"], "16:9")

    timeout = httpx.Timeout(connect=30.0, read=30.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        # Step 1: 提交任务
        submit_resp = client.post(
            f"{base_url}/videos/generations",
            headers=headers,
            json=request_body,
        )
        _raise_kling_error(submit_resp, "submit")
        task_data = submit_resp.json()

        # 提取 task_id
        task_id = (
            task_data.get("data", {}).get("task_id")
            or task_data.get("task_id")
            or task_data.get("id")
        )
        if not task_id:
            raise RuntimeError(f"Kling submit response missing task_id: {task_data}")
        logger.info("Kling task submitted: %s", task_id)

        # Step 2: 轮询
        start_time = time.time()
        while time.time() - start_time < MAX_POLL_TIME:
            time.sleep(POLL_INTERVAL)
            poll_resp = client.get(
                f"{base_url}/videos/generations/{task_id}",
                headers=headers,
            )
            _raise_kling_error(poll_resp, f"poll task_id={task_id}")
            poll_data = poll_resp.json()

            # Kling 返回格式: {"data": {"task_status": "succeed", "task_result": {...}}}
            data = poll_data.get("data", poll_data)
            status = str(data.get("task_status", data.get("status", ""))).lower()

            if status in {"succeed", "succeeded", "completed"}:
                # 提取视频 URL
                result = data.get("task_result", data.get("result", data))
                videos = result.get("videos", [])
                if videos and isinstance(videos[0], dict):
                    video_url = videos[0].get("url", "")
                else:
                    video_url = result.get("video_url", result.get("url", ""))

                if not video_url:
                    raise RuntimeError(f"Kling completed without video url: {poll_data}")

                logger.info("Kling task completed: %s", task_id)
                return {
                    "url": video_url,
                    "duration": payload.get("duration", 5),
                    "task_id": task_id,
                    "status": "completed",
                    "provider": "kling",
                }

            if status in {"failed", "error", "cancelled"}:
                error_msg = data.get("task_status_msg", data.get("message", "Unknown error"))
                raise RuntimeError(f"Kling task {task_id} failed: {error_msg}")

            logger.debug("Kling polling task_id=%s status=%s", task_id, status)

    raise TimeoutError(f"Kling task {task_id} timed out after {MAX_POLL_TIME}s")
```

### 3. `app/services/tts.py`（新建）

火山引擎 TTS 语音合成：

```python
"""
火山引擎 TTS 语音合成服务。

使用 Ark API 的语音合成端点。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _raise_tts_error(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()[:500]
        raise RuntimeError(
            f"TTS request failed with status={response.status_code}: {detail or exc!s}"
        ) from exc


def generate_speech(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用火山引擎 TTS API 生成语音。

    payload 期望字段:
      - text: str (要合成的文本，最大 1000 字)
      - voice: str (音色 ID，如 "zh_female_shuangkuai")
      - speed: float (语速 0.5-2.0，默认 1.0)
      - volume: float (音量 0.5-2.0，默认 1.0)

    返回:
      - url: str (音频下载地址)
      - duration: float (音频时长秒)
      - characters: int (合成字符数)
    """
    settings = get_settings()
    base_url = settings.ark_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    text = payload.get("text", "")
    if not text:
        raise ValueError("TTS text cannot be empty")
    if len(text) > 5000:
        raise ValueError(f"TTS text too long: {len(text)} chars (max 5000)")

    request_body = {
        "model": settings.ark_tts_model,
        "input": text,
        "voice": payload.get("voice", "zh_female_shuangkuai"),
        "response_format": "mp3",
        "speed": payload.get("speed", 1.0),
    }

    timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/audio/speech",
            headers=headers,
            json=request_body,
        )
        _raise_tts_error(response)

        # TTS 可能直接返回音频二进制，也可能返回 JSON 含 URL
        content_type = response.headers.get("content-type", "")

        if "audio" in content_type or "octet-stream" in content_type:
            # 直接返回音频数据 — 需要上传到存储
            # 暂时返回 base64 或提示需要对象存储
            import base64
            audio_b64 = base64.b64encode(response.content).decode()
            duration_estimate = len(text) * 0.3  # 粗略估算
            logger.info("TTS generated audio: %d bytes, ~%.1fs", len(response.content), duration_estimate)
            return {
                "audio_base64": audio_b64,
                "format": "mp3",
                "duration": duration_estimate,
                "characters": len(text),
                "status": "completed",
            }
        else:
            # JSON 响应含 URL
            data = response.json()
            audio_url = data.get("url") or data.get("audio_url") or ""
            duration = data.get("duration", len(text) * 0.3)
            logger.info("TTS generated: %s", audio_url[:80] if audio_url else "inline")
            return {
                "url": audio_url,
                "format": "mp3",
                "duration": duration,
                "characters": len(text),
                "status": "completed",
            }
```

### 4. `app/tasks/tts_tasks.py`（新建）

TTS Celery 任务，模式和 image_tasks 类似：

```python
from __future__ import annotations

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
    publish_complete,
    publish_failed,
    publish_progress,
    resolve_callable,
)

MAX_RETRIES = 3


@celery_app.task(bind=True, queue="text", soft_time_limit=120, time_limit=240, acks_late=True)
def generate_tts_task(
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
        stage_text="Preparing TTS task",
        retry_count=self.request.retries,
        celery_task_id=self.request.id,
    )
    key_name: str | None = None

    try:
        # TTS 使用 doubao 的 key（同属火山引擎）
        key_name, api_key = key_pool.acquire("doubao")
        publish_progress(
            task_id,
            status="running",
            progress=15,
            stage_text="Generating speech",
            retry_count=self.request.retries,
            celery_task_id=self.request.id,
        )
        call = resolve_callable(
            "app.services.tts",
            ("generate_speech", "generate_tts", "generate"),
        )
        result = invoke_callable(call, payload, api_key=api_key, task_id=task_id, user_id=user_id)
        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if key_name and retryable:
            key_pool.report_error(key_name, str(exc))
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id,
                status="retrying",
                progress=15,
                stage_text=f"Retrying TTS ({self.request.retries + 1}/{MAX_RETRIES})",
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
    finally:
        if key_name:
            key_pool.release(key_name)
```

### 5. `app/services/key_pool.py` — 添加 Kling 服务限制

```python
SERVICE_LIMITS = {
    "seedance": 2,
    "seedream": 5,
    "doubao": 10,
    "kling": 2,
}
```

同时在 `_service_keys` 方法中添加 kling 映射：

```python
attr_map = {
    "seedance": ("seedance_api_keys", "ark_api_key_list"),
    "seedream": ("seedream_api_keys", "ark_api_key_list"),
    "doubao": ("doubao_api_keys", "ark_api_key_list"),
    "kling": ("kling_api_key_list",),  # Kling 独立 key，不 fallback 到 ark
}
```

### 6. `app/tasks/video_tasks.py` — 支持 provider 路由

修改 `generate_video_task`，根据 payload 中的 `provider` 字段选择不同服务：

```python
# 在 try 块中，替换固定的 resolve_callable 调用：
provider = payload.get("provider", "seedance")
service_map = {
    "seedance": ("app.services.seedance", "seedance"),
    "kling": ("app.services.kling", "kling"),
}
module_name, pool_service = service_map.get(provider, ("app.services.seedance", "seedance"))

key_name, api_key = key_pool.acquire(pool_service)
# ...
call = resolve_callable(module_name, ("generate_video", "generate"))
```

### 7. `app/celery_app.py` — 注册 TTS 任务

在 imports 中添加：

```python
imports=(
    "app.tasks.video_tasks",
    "app.tasks.image_tasks",
    "app.tasks.text_tasks",
    "app.tasks.tts_tasks",    # 新增
    "app.tasks.admin_tasks",
),
```

在 task_routes 中添加：

```python
"app.tasks.tts_tasks.*": {"queue": "text"},  # TTS 复用 text 队列
```

### 8. `app/services/credits.py` — 添加 TTS 定价

在 DEFAULT_PRICING 中添加：

```python
"tts_synthesis": 1,  # 每次 TTS 合成 1 积分
```

## 验收标准

1. `app/services/kling.py` 能提交视频任务并轮询（结构完整，等 key 即可用）
2. `app/services/tts.py` 能调用火山引擎 TTS 并返回音频
3. `app/tasks/tts_tasks.py` 完整实现 charge/refund/retry 流程
4. `video_tasks.py` 支持 `provider` 参数路由到 seedance 或 kling
5. Key Pool 的 SERVICE_LIMITS 包含 `"kling": 2`
6. Celery 注册了 tts_tasks
7. 函数签名保持一致（`generate_video/generate_speech`）

## 完成后

告诉 orchestrator：T16 完成，列出创建/修改的文件清单。
