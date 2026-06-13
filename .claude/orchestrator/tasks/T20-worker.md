# T20 指令 — worker 终端

## 你的身份

你是 `worker` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

集成对象存储服务，让生成结果（视频/图片/音频）持久化存储并通过 CDN URL 返回给用户。

使用火山引擎 TOS（兼容 S3 协议），通过 boto3 操作。

## 分支

（如果 git 报错可忽略，直接在当前分支工作）

## 需要创建/修改的文件

### 1. `app/config.py` — 添加 OSS 配置

在 Settings 类中添加：

```python
    # 对象存储 (TOS / S3 兼容)
    oss_endpoint: str = "https://tos-cn-beijing.volces.com"
    oss_access_key: str = ""
    oss_secret_key: str = ""
    oss_bucket: str = "shortdrama-ai"
    oss_region: str = "cn-beijing"
    oss_cdn_domain: str = ""  # 如 "https://cdn.example.com"，为空则用 bucket 直链
```

### 2. `app/services/storage.py`（新建）

对象存储服务，封装上传/下载/生成签名 URL：

```python
"""
对象存储服务 — 兼容 S3 协议（火山引擎 TOS / AWS S3 / MinIO）。

功能:
- upload_file: 上传文件（bytes 或文件路径）
- upload_from_url: 从外部 URL 下载并上传到 OSS
- get_public_url: 获取公开访问 URL（CDN 或直链）
- generate_presigned_url: 生成临时签名 URL
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from io import BytesIO
from typing import Any

import boto3
import httpx
from botocore.config import Config as BotoConfig

from app.config import get_settings

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None:
            settings = get_settings()
            if not settings.oss_access_key or not settings.oss_secret_key:
                raise RuntimeError("OSS credentials not configured (OSS_ACCESS_KEY / OSS_SECRET_KEY)")
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.oss_endpoint,
                aws_access_key_id=settings.oss_access_key,
                aws_secret_access_key=settings.oss_secret_key,
                region_name=settings.oss_region,
                config=BotoConfig(signature_version="s3v4"),
            )
        return self._client

    @property
    def bucket(self) -> str:
        return get_settings().oss_bucket

    def upload_bytes(
        self,
        data: bytes,
        key: str | None = None,
        content_type: str = "application/octet-stream",
        folder: str = "uploads",
    ) -> str:
        """
        上传字节数据到 OSS。
        返回对象 key。
        """
        if not key:
            ext = self._guess_extension(content_type)
            key = f"{folder}/{uuid.uuid4().hex}{ext}"

        self.client.upload_fileobj(
            BytesIO(data),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("Uploaded %d bytes to %s/%s", len(data), self.bucket, key)
        return key

    def upload_from_url(
        self,
        url: str,
        folder: str = "results",
        content_type: str | None = None,
    ) -> dict[str, str]:
        """
        从外部 URL 下载内容并上传到 OSS。
        返回 {"key": "...", "url": "...", "size": N}
        """
        with httpx.Client(timeout=120, follow_redirects=True) as http:
            resp = http.get(url)
            resp.raise_for_status()

        data = resp.content
        ct = content_type or resp.headers.get("content-type", "application/octet-stream")
        ext = self._guess_extension(ct)
        # 用内容 hash 避免重复上传
        content_hash = hashlib.md5(data).hexdigest()[:12]
        key = f"{folder}/{content_hash}_{uuid.uuid4().hex[:8]}{ext}"

        self.client.upload_fileobj(
            BytesIO(data),
            self.bucket,
            key,
            ExtraArgs={"ContentType": ct},
        )
        logger.info("Uploaded from URL (%d bytes) to %s/%s", len(data), self.bucket, key)

        return {
            "key": key,
            "url": self.get_public_url(key),
            "size": len(data),
            "content_type": ct,
        }

    def get_public_url(self, key: str) -> str:
        """获取公开访问 URL"""
        settings = get_settings()
        if settings.oss_cdn_domain:
            domain = settings.oss_cdn_domain.rstrip("/")
            return f"{domain}/{key}"
        # 直接用 bucket 域名
        endpoint = settings.oss_endpoint.rstrip("/")
        return f"{endpoint}/{self.bucket}/{key}"

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """生成临时签名 URL（用于私有文件）"""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete(self, key: str) -> None:
        """删除对象"""
        self.client.delete_object(Bucket=self.bucket, Key=key)
        logger.info("Deleted %s/%s", self.bucket, key)

    @staticmethod
    def _guess_extension(content_type: str) -> str:
        ct_map = {
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "application/octet-stream": "",
        }
        for prefix, ext in ct_map.items():
            if prefix in content_type:
                return ext
        return ""


storage_service = StorageService()
```

### 3. `app/tasks/_shared.py` — 添加结果持久化辅助函数

在文件末尾添加：

```python
def persist_result_to_oss(result: dict[str, Any], task_type: str) -> dict[str, Any]:
    """
    将任务结果中的外部 URL 持久化到 OSS。
    返回更新后的 result（url 替换为 OSS URL）。
    """
    from app.services.storage import storage_service

    try:
        settings = get_settings()
        if not settings.oss_access_key:
            # OSS 未配置，直接返回原始结果
            return result

        # 视频/图片：下载外部 URL 并上传到 OSS
        if result.get("url") and result["url"].startswith("http"):
            folder = f"results/{task_type}"
            uploaded = storage_service.upload_from_url(result["url"], folder=folder)
            result["original_url"] = result["url"]
            result["url"] = uploaded["url"]
            result["oss_key"] = uploaded["key"]
            result["file_size"] = uploaded["size"]

        # TTS 音频：base64 数据上传到 OSS
        if result.get("audio_base64"):
            import base64
            audio_data = base64.b64decode(result["audio_base64"])
            folder = f"results/{task_type}"
            key = storage_service.upload_bytes(
                audio_data,
                content_type="audio/mpeg",
                folder=folder,
            )
            result["url"] = storage_service.get_public_url(key)
            result["oss_key"] = key
            result["file_size"] = len(audio_data)
            del result["audio_base64"]  # 不再返回 base64

    except Exception as exc:
        LOGGER.warning("Failed to persist result to OSS: %s", exc)
        # OSS 失败不影响任务成功，保留原始结果

    return result
```

### 4. 修改各任务文件，在 `publish_complete` 前调用持久化

在 `app/tasks/video_tasks.py`、`image_tasks.py`、`text_tasks.py`、`tts_tasks.py` 中，在调用 `publish_complete` 之前添加：

```python
from app.tasks._shared import persist_result_to_oss

# 在 result = invoke_callable(...) 之后，publish_complete 之前：
result = persist_result_to_oss(result, "video")  # 或 "image" / "text" / "tts"
```

### 5. `requirements.txt` — 添加 boto3

```
boto3>=1.34
```

### 6. `.env.example` — 添加 OSS 配置

```env
# 对象存储
OSS_ENDPOINT=https://tos-cn-beijing.volces.com
OSS_ACCESS_KEY=your-access-key
OSS_SECRET_KEY=your-secret-key
OSS_BUCKET=shortdrama-ai
OSS_REGION=cn-beijing
OSS_CDN_DOMAIN=
```

## 注意事项

- OSS 未配置时（`oss_access_key` 为空），`persist_result_to_oss` 直接返回原始结果，不报错
- 上传失败不影响任务成功状态（try/except 包裹）
- 使用 MD5 前缀避免重复上传相同内容
- boto3 的 S3 兼容接口适用于火山引擎 TOS、阿里云 OSS、MinIO 等

## 验收标准

1. `app/services/storage.py` 能上传 bytes 和从 URL 下载上传
2. 各任务完成后自动将结果 URL 持久化到 OSS（如果配置了）
3. TTS 的 base64 音频数据被替换为 OSS URL
4. OSS 未配置时系统正常运行（graceful degradation）
5. `boto3` 已添加到 `requirements.txt`
6. `.env.example` 包含 OSS 配置项

## 完成后

告诉 orchestrator：T20 完成，列出创建/修改的文件清单。
