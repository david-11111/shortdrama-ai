"""
API Key HMAC-SHA256 + 盐，替代裸 SHA256。

新 key: HMAC-SHA256(salt, raw_key)
历史 key: 保留原 sha256 hash，hmac_salt 列为 NULL 表示旧格式
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def _get_hmac_secret() -> bytes:
    secret = os.environ.get("API_KEY_HMAC_SECRET", "")
    if not secret:
        raise RuntimeError("API_KEY_HMAC_SECRET environment variable is not set")
    return secret.encode("utf-8")


def generate_salt() -> str:
    """生成 32 字节随机盐（hex 编码，64 字符）"""
    return secrets.token_hex(32)


def compute_hmac_hash(raw_key: str, salt: str) -> str:
    """HMAC-SHA256(secret + salt, raw_key) → hex digest"""
    secret = _get_hmac_secret()
    key_material = secret + salt.encode("utf-8")
    return hmac.new(key_material, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_legacy_hash(raw_key: str) -> str:
    """裸 SHA256（仅用于验证历史 key）"""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str, salt: str | None) -> bool:
    """
    验证 API Key。
    salt 为 None 表示历史 key，使用裸 SHA256 比对。
    salt 不为 None 表示新格式，使用 HMAC 比对。
    """
    if salt is None:
        candidate = compute_legacy_hash(raw_key)
    else:
        candidate = compute_hmac_hash(raw_key, salt)
    return hmac.compare_digest(candidate, stored_hash)
