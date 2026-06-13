"""
对象存储服务 — 兼容 S3 协议（火山引擎 TOS / AWS S3 / MinIO）。

功能:
- upload_bytes: 上传字节数据
- upload_from_url: 从外部 URL 下载并上传到 OSS
- get_public_url: 获取公开访问 URL（CDN 或直链）
- generate_presigned_url: 生成临时签名 URL
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import uuid
from io import BytesIO
from typing import Any

import httpx

from app.config import get_settings
from app.services.media_proxy import validate_public_media_url

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
            try:
                import boto3
                from botocore.config import Config as BotoConfig
            except ImportError as exc:
                raise RuntimeError("OSS support requires boto3 and botocore to be installed") from exc
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
        """上传字节数据到 OSS，返回对象 key。"""
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

    def upload_file(
        self,
        path: str,
        key: str | None = None,
        content_type: str = "application/octet-stream",
        folder: str = "uploads",
    ) -> str:
        """Upload a local file to object storage without loading it into memory."""
        if not key:
            ext = self._guess_extension(content_type)
            key = f"{folder}/{uuid.uuid4().hex}{ext}"
        file_size = os.path.getsize(path)
        with open(path, "rb") as fileobj:
            self.client.upload_fileobj(
                fileobj,
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
        logger.info("Uploaded file %s (%d bytes) to %s/%s", path, file_size, self.bucket, key)
        return key

    def upload_from_url(
        self,
        url: str,
        folder: str = "results",
        content_type: str | None = None,
        max_size: int = 500 * 1024 * 1024,  # 500MB limit
    ) -> dict[str, Any]:
        """从外部 URL 下载内容并上传到 OSS，返回 {"key", "url", "size", "content_type"}。"""
        validate_public_media_url(url)
        temp_path = ""
        total = 0
        digest = hashlib.md5()
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                temp_path = tmp.name
                with httpx.Client(timeout=120, follow_redirects=True) as http:
                    with http.stream("GET", url) as resp:
                        validate_public_media_url(str(resp.url))
                        resp.raise_for_status()
                        ct = content_type or resp.headers.get("content-type", "application/octet-stream")

                        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                            total += len(chunk)
                            if total > max_size:
                                raise RuntimeError(f"File too large (>{max_size // 1024 // 1024}MB)")
                            digest.update(chunk)
                            tmp.write(chunk)
        except Exception:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise

        ext = self._guess_extension(ct)
        content_hash = digest.hexdigest()[:12]
        key = f"{folder}/{content_hash}_{uuid.uuid4().hex[:8]}{ext}"

        try:
            with open(temp_path, "rb") as fileobj:
                self.client.upload_fileobj(
                    fileobj,
                    self.bucket,
                    key,
                    ExtraArgs={"ContentType": ct},
                )
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        logger.info("Uploaded from URL (%d bytes) to %s/%s", total, self.bucket, key)

        return {
            "key": key,
            "url": self.get_public_url(key),
            "size": total,
            "content_type": ct,
        }

    def get_public_url(self, key: str) -> str:
        """获取公开访问 URL"""
        settings = get_settings()
        if settings.oss_cdn_domain:
            domain = settings.oss_cdn_domain.rstrip("/")
            return f"{domain}/{key}"
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
