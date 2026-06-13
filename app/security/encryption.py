"""
对称加密工具 — Fernet（AES-128-CBC + HMAC-SHA256）。

用于数据库中存储敏感字段（如第三方 API Key）。
加密密钥从环境变量 FIELD_ENCRYPTION_KEY 读取（base64url 编码的 32 字节）。
"""
from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    key = os.environ.get("FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("FIELD_ENCRYPTION_KEY environment variable is not set")
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """加密字符串，返回 base64 密文"""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """解密，失败抛 InvalidToken"""
    return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def generate_key() -> str:
    """生成新的 Fernet 密钥（base64url，44 字符）"""
    return Fernet.generate_key().decode("ascii")
