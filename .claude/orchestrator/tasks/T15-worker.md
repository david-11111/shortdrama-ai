# T15 指令 — worker 终端

## 你的身份

你是 `worker` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 背景

当前 `app/services/seedance.py`、`seedream.py`、`doubao.py` 都是 stub 实现（返回假数据）。需要替换为真实的火山引擎 Ark API 调用。

三个服务都走火山引擎统一的 Ark 平台：
- Seedance（视频生成）— 异步任务模式：提交 → 轮询 → 获取结果
- Seedream（图片生成）— 同步/异步模式：提交 → 等待返回
- Doubao（文本生成）— 流式/非流式 Chat Completion

API 统一使用 `ARK_API_KEYS` 环境变量中的 key，通过 `Authorization: Bearer {api_key}` 鉴权。

## 任务目标

将三个 stub 服务替换为真实 API 调用实现。

## 分支

```bash
git checkout -b worker/phase5-real-api
```
（如果 git 报错可忽略，直接在当前分支工作）

## 需要修改的文件

### 1. `app/config.py` — 添加 Ark 平台配置

在 Settings 类中添加：

```python
    # 火山引擎 Ark 平台
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_video_model: str = "seedance-1-0"        # 视频生成模型 endpoint ID
    ark_image_model: str = "seedream-3-0"        # 图片生成模型 endpoint ID
    ark_text_model: str = "doubao-1-5-pro-32k"   # 文本生成模型 endpoint ID
```

### 2. `app/services/seedance.py` — 视频生成（异步任务）

Seedance 是异步任务模式：
1. POST 提交生成请求 → 返回 task_id
2. 轮询 GET task_id → 等待 status=succeeded
3. 返回视频 URL

```python
"""
Seedance 视频生成服务 — 火山引擎 Ark API。

接口文档参考: https://www.volcengine.com/docs/6791/seedance-api
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # 秒
MAX_POLL_TIME = 600  # 最大等待 10 分钟


def generate_video(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用 Seedance API 生成视频。

    payload 期望字段:
      - prompt: str (视频描述)
      - duration: int (5/8/10 秒)
      - resolution: str ("720p" / "1080p")
      - image_url: str (可选，图生视频的参考图)

    返回:
      - url: str (视频下载地址)
      - duration: int
      - task_id: str (Ark 平台任务 ID)
    """
    settings = get_settings()
    base_url = settings.ark_base_url
    model = settings.ark_video_model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 构建请求体
    request_body = {
        "model": model,
        "content": [
            {"type": "text", "text": payload.get("prompt", "")},
        ],
    }

    # 如果有参考图
    if payload.get("image_url"):
        request_body["content"].insert(0, {
            "type": "image_url",
            "image_url": {"url": payload["image_url"]},
        })

    # 参数
    request_body["parameters"] = {
        "duration": payload.get("duration", 5),
        "resolution": payload.get("resolution", "1080p"),
    }

    with httpx.Client(timeout=30) as client:
        # Step 1: 提交任务
        resp = client.post(
            f"{base_url}/async/video/generations",
            headers=headers,
            json=request_body,
        )
        resp.raise_for_status()
        task_data = resp.json()
        task_id = task_data["id"]
        logger.info("Seedance task submitted: %s", task_id)

        # Step 2: 轮询等待
        start_time = time.time()
        while time.time() - start_time < MAX_POLL_TIME:
            time.sleep(POLL_INTERVAL)

            poll_resp = client.get(
                f"{base_url}/async/video/generations/{task_id}",
                headers=headers,
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()
            status = poll_data.get("status", "")

            if status == "succeeded":
                video_url = poll_data.get("output", {}).get("video_url", "")
                logger.info("Seedance task completed: %s → %s", task_id, video_url[:80])
                return {
                    "url": video_url,
                    "duration": payload.get("duration", 5),
                    "task_id": task_id,
                    "status": "completed",
                }
            elif status == "failed":
                error_msg = poll_data.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Seedance generation failed: {error_msg}")

            # 发布进度（如果有 task_id kwarg）
            progress_pct = min(90, int((time.time() - start_time) / MAX_POLL_TIME * 90))
            logger.debug("Seedance polling %s: status=%s progress=%d%%", task_id, status, progress_pct)

        raise TimeoutError(f"Seedance task {task_id} timed out after {MAX_POLL_TIME}s")
```

### 3. `app/services/seedream.py` — 图片生成

Seedream 通常是同步返回或短时异步：

```python
"""
Seedream 图片生成服务 — 火山引擎 Ark API。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def generate_image(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用 Seedream API 生成图片。

    payload 期望字段:
      - prompt: str (图片描述)
      - width: int (默认 1024)
      - height: int (默认 1024)
      - style: str (可选风格)
      - negative_prompt: str (可选负面提示)

    返回:
      - url: str (图片下载地址)
      - width: int
      - height: int
    """
    settings = get_settings()
    base_url = settings.ark_base_url
    model = settings.ark_image_model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    request_body = {
        "model": model,
        "prompt": payload.get("prompt", ""),
        "size": f"{payload.get('width', 1024)}x{payload.get('height', 1024)}",
        "n": 1,
    }

    if payload.get("negative_prompt"):
        request_body["negative_prompt"] = payload["negative_prompt"]

    if payload.get("style"):
        request_body["style"] = payload["style"]

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            f"{base_url}/images/generations",
            headers=headers,
            json=request_body,
        )
        resp.raise_for_status()
        data = resp.json()

    # 解析结果
    images = data.get("data", [])
    if not images:
        raise RuntimeError("Seedream returned no images")

    image_url = images[0].get("url", "")
    logger.info("Seedream image generated: %s", image_url[:80])

    return {
        "url": image_url,
        "width": payload.get("width", 1024),
        "height": payload.get("height", 1024),
        "status": "completed",
    }
```

### 4. `app/services/doubao.py` — 文本生成（Chat Completion）

Doubao 走标准 OpenAI 兼容的 Chat Completion 接口：

```python
"""
豆包 (Doubao) 文本生成服务 — 火山引擎 Ark API。

兼容 OpenAI Chat Completion 格式。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def generate_text(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用豆包 Chat Completion API。

    payload 期望字段:
      - prompt: str (用户输入)
      - system_prompt: str (可选系统提示)
      - temperature: float (默认 0.7)
      - max_tokens: int (默认 2048)

    返回:
      - text: str (生成的文本)
      - tokens_used: int (总 token 消耗)
      - model: str
    """
    settings = get_settings()
    base_url = settings.ark_base_url
    model = settings.ark_text_model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = []
    if payload.get("system_prompt"):
        messages.append({"role": "system", "content": payload["system_prompt"]})
    messages.append({"role": "user", "content": payload.get("prompt", "")})

    request_body = {
        "model": model,
        "messages": messages,
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", 2048),
    }

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=request_body,
        )
        resp.raise_for_status()
        data = resp.json()

    choice = data.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    usage = data.get("usage", {})
    total_tokens = usage.get("total_tokens", 0)

    logger.info("Doubao generated %d tokens", total_tokens)

    return {
        "text": content,
        "tokens_used": total_tokens,
        "model": model,
        "status": "completed",
    }
```

### 5. `requirements.txt` — 添加 httpx

确保 `httpx` 在依赖列表中（用于同步 HTTP 调用，比 requests 更现代）：

```
httpx>=0.27
```

## 注意事项

- 所有 HTTP 调用必须设置合理的 timeout
- 错误信息要包含足够上下文（task_id、status code、error message）
- `raise_for_status()` 会抛 `httpx.HTTPStatusError`，这会被 worker 的 `is_retryable_exception` 正确识别（包含 429、500 等关键词）
- 不要修改函数签名（`generate_video(api_key, payload, **kwargs)`），因为 worker 的 `resolve_callable` + `invoke_callable` 依赖这个签名
- Ark API 的具体端点路径可能需要根据实际文档微调，先按通用模式实现

## 验收标准

1. `app/services/seedance.py` 能提交视频生成任务并轮询结果
2. `app/services/seedream.py` 能调用图片生成并返回 URL
3. `app/services/doubao.py` 能调用 Chat Completion 并返回文本
4. 所有服务在 API 返回错误时抛出有意义的异常
5. `httpx` 已添加到 `requirements.txt`
6. 函数签名保持不变（`generate_video/generate_image/generate_text`）

## 完成后

告诉 orchestrator：T15 完成，列出修改的文件清单。
