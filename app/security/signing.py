"""
微信支付 V3 + 支付宝 RSA2 签名验签。

依赖: cryptography（已通过 python-jose[cryptography] 引入）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any
from urllib.parse import unquote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 微信支付 V3
# ---------------------------------------------------------------------------

def verify_wechat_v3_signature(
    timestamp: str,
    nonce: str,
    body: bytes,
    signature_b64: str,
    platform_cert_pem: str,
) -> bool:
    """
    验证微信支付 V3 回调签名。

    消息格式: "{timestamp}\n{nonce}\n{body_str}\n"
    算法: RSA-SHA256（使用微信平台证书公钥）
    """
    message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n".encode("utf-8")
    try:
        sig_bytes = base64.b64decode(signature_b64)
        cert = serialization.load_pem_public_key(platform_cert_pem.encode())
        cert.verify(sig_bytes, message, padding.PKCS1v15(), hashes.SHA256())  # type: ignore[arg-type]
        return True
    except (InvalidSignature, Exception) as exc:
        logger.warning("WeChat V3 signature verification failed: %s", exc)
        return False


def decrypt_wechat_v3_resource(
    ciphertext_b64: str,
    nonce: str,
    associated_data: str,
    api_v3_key: str,
) -> dict[str, Any] | None:
    """
    解密微信支付 V3 回调 resource.ciphertext（AES-256-GCM）。

    api_v3_key: 32 字节 UTF-8 字符串
    """
    try:
        key = api_v3_key.encode("utf-8")
        if len(key) not in (16, 24, 32):
            logger.error("WeChat V3 API key must be 16, 24, or 32 bytes; got %d bytes", len(key))
            return None
        ciphertext = base64.b64decode(ciphertext_b64)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(
            nonce.encode("utf-8"),
            ciphertext,
            associated_data.encode("utf-8"),
        )
        return json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        logger.error("WeChat V3 resource decryption failed: %s", exc)
        return None


def parse_wechat_v3_callback(
    headers: dict[str, str],
    body: bytes,
    api_v3_key: str,
    platform_cert_pem: str | None = None,
) -> dict[str, Any] | None:
    """
    完整的微信 V3 回调处理：验签 + 解密。

    platform_cert_pem 为 None 时跳过签名验证（仅用于开发/测试）。
    生产环境必须传入平台证书。
    """
    timestamp = headers.get("wechatpay-timestamp", "")
    nonce = headers.get("wechatpay-nonce", "")
    signature = headers.get("wechatpay-signature", "")

    if platform_cert_pem:
        if not timestamp or not nonce or not signature:
            logger.warning("WeChat callback missing required headers")
            return None
        if not verify_wechat_v3_signature(timestamp, nonce, body, signature, platform_cert_pem):
            return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("WeChat callback body is not valid JSON")
        return None

    if data.get("event_type") != "TRANSACTION.SUCCESS":
        return None

    resource = data.get("resource", {})
    plaintext = decrypt_wechat_v3_resource(
        ciphertext_b64=resource.get("ciphertext", ""),
        nonce=resource.get("nonce", ""),
        associated_data=resource.get("associated_data", ""),
        api_v3_key=api_v3_key,
    )
    return plaintext


# ---------------------------------------------------------------------------
# 支付宝 RSA2
# ---------------------------------------------------------------------------

def _build_alipay_sign_string(params: dict[str, str]) -> str:
    """按支付宝规则构建待签名字符串（排除 sign/sign_type，按 key 字母序）"""
    filtered = {k: v for k, v in params.items() if k not in ("sign", "sign_type") and v != ""}
    sorted_pairs = sorted(filtered.items())
    return "&".join(f"{k}={v}" for k, v in sorted_pairs)


def verify_alipay_rsa2_signature(
    params: dict[str, str],
    alipay_public_key_pem: str,
) -> bool:
    """
    验证支付宝 RSA2（SHA256withRSA）回调签名。

    params: 支付宝回调的全部表单参数（含 sign）
    alipay_public_key_pem: 支付宝公钥（PEM 格式）
    """
    sign_b64 = params.get("sign", "")
    sign_type = params.get("sign_type", "RSA2")

    if sign_type != "RSA2":
        logger.warning("Alipay unsupported sign_type: %s", sign_type)
        return False

    sign_string = _build_alipay_sign_string(params)

    try:
        sig_bytes = base64.b64decode(sign_b64)
        public_key = serialization.load_pem_public_key(alipay_public_key_pem.encode())
        public_key.verify(sig_bytes, sign_string.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())  # type: ignore[arg-type]
        return True
    except (InvalidSignature, Exception) as exc:
        logger.warning("Alipay RSA2 signature verification failed: %s", exc)
        return False
