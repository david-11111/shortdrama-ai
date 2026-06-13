"""
P8-SEC-1/SEC-2 签名验签单元测试 fixture。

提供：
- 微信 V3 签名验证（有效/无效）
- 微信 V3 AES-GCM 解密（有效/无效）
- 支付宝 RSA2 验签（有效/无效）

所有密钥均为测试专用，不用于生产。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.security.signing import (
    decrypt_wechat_v3_resource,
    verify_alipay_rsa2_signature,
    verify_wechat_v3_signature,
    _build_alipay_sign_string,
)


# ─── 测试密钥生成（模块级，只生成一次）────────────────────────────────────────────

def _gen_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_key, pub_pem


_WECHAT_PRIVATE_KEY, _WECHAT_PLATFORM_CERT_PEM = _gen_rsa_keypair()
_ALIPAY_PRIVATE_KEY, _ALIPAY_PUBLIC_KEY_PEM = _gen_rsa_keypair()
_WECHAT_API_V3_KEY = "test_api_v3_key_32bytes_padding!"  # 32 字节


def _sign_wechat(timestamp: str, nonce: str, body: bytes) -> str:
    message = f"{timestamp}\n{nonce}\n{body.decode()}\n".encode()
    sig = _WECHAT_PRIVATE_KEY.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def _encrypt_wechat_resource(plaintext: dict, nonce: str, associated_data: str) -> str:
    key = _WECHAT_API_V3_KEY.encode()
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce.encode(), json.dumps(plaintext).encode(), associated_data.encode())
    return base64.b64encode(ct).decode()


def _sign_alipay(params: dict) -> str:
    sign_string = _build_alipay_sign_string(params)
    sig = _ALIPAY_PRIVATE_KEY.sign(sign_string.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


# ─── 微信 V3 签名验证 ─────────────────────────────────────────────────────────────

class TestWechatV3Signature:

    def test_valid_signature(self):
        timestamp, nonce, body = "1620000000", "abc123", b'{"event_type":"TRANSACTION.SUCCESS"}'
        sig = _sign_wechat(timestamp, nonce, body)
        assert verify_wechat_v3_signature(timestamp, nonce, body, sig, _WECHAT_PLATFORM_CERT_PEM)

    def test_tampered_body_rejected(self):
        timestamp, nonce = "1620000000", "abc123"
        body = b'{"event_type":"TRANSACTION.SUCCESS"}'
        sig = _sign_wechat(timestamp, nonce, body)
        tampered = b'{"event_type":"REFUND.SUCCESS"}'
        assert not verify_wechat_v3_signature(timestamp, nonce, tampered, sig, _WECHAT_PLATFORM_CERT_PEM)

    def test_wrong_timestamp_rejected(self):
        timestamp, nonce, body = "1620000000", "abc123", b'{"event_type":"TRANSACTION.SUCCESS"}'
        sig = _sign_wechat(timestamp, nonce, body)
        assert not verify_wechat_v3_signature("9999999999", nonce, body, sig, _WECHAT_PLATFORM_CERT_PEM)

    def test_invalid_base64_signature_rejected(self):
        timestamp, nonce, body = "1620000000", "abc123", b'{"event_type":"TRANSACTION.SUCCESS"}'
        assert not verify_wechat_v3_signature(timestamp, nonce, body, "not_base64!!!", _WECHAT_PLATFORM_CERT_PEM)


# ─── 微信 V3 AES-GCM 解密 ────────────────────────────────────────────────────────

class TestWechatV3Decrypt:

    def test_valid_decryption(self):
        nonce = "test_nonce_12"
        associated_data = "transaction"
        plaintext = {"out_trade_no": "ORD001", "transaction_id": "wx_001"}
        ciphertext_b64 = _encrypt_wechat_resource(plaintext, nonce, associated_data)

        result = decrypt_wechat_v3_resource(ciphertext_b64, nonce, associated_data, _WECHAT_API_V3_KEY)
        assert result == plaintext

    def test_wrong_key_rejected(self):
        nonce = "test_nonce_12"
        associated_data = "transaction"
        plaintext = {"out_trade_no": "ORD001"}
        ciphertext_b64 = _encrypt_wechat_resource(plaintext, nonce, associated_data)

        result = decrypt_wechat_v3_resource(ciphertext_b64, nonce, associated_data, "wrong_key_32bytes_padding_here!!")
        assert result is None

    def test_tampered_ciphertext_rejected(self):
        nonce = "test_nonce_12"
        associated_data = "transaction"
        plaintext = {"out_trade_no": "ORD001"}
        ciphertext_b64 = _encrypt_wechat_resource(plaintext, nonce, associated_data)

        # 篡改密文
        ct_bytes = bytearray(base64.b64decode(ciphertext_b64))
        ct_bytes[0] ^= 0xFF
        tampered = base64.b64encode(bytes(ct_bytes)).decode()

        result = decrypt_wechat_v3_resource(tampered, nonce, associated_data, _WECHAT_API_V3_KEY)
        assert result is None


# ─── 支付宝 RSA2 验签 ─────────────────────────────────────────────────────────────

class TestAlipayRSA2:

    def _make_params(self, extra: dict | None = None) -> dict:
        params = {
            "app_id": "2021001",
            "method": "alipay.trade.page.pay",
            "out_trade_no": "ORD_ALI_001",
            "trade_no": "ali_trade_001",
            "trade_status": "TRADE_SUCCESS",
            "sign_type": "RSA2",
        }
        if extra:
            params.update(extra)
        params["sign"] = _sign_alipay(params)
        return params

    def test_valid_signature(self):
        params = self._make_params()
        assert verify_alipay_rsa2_signature(params, _ALIPAY_PUBLIC_KEY_PEM)

    def test_tampered_param_rejected(self):
        params = self._make_params()
        params["out_trade_no"] = "ORD_TAMPERED"
        assert not verify_alipay_rsa2_signature(params, _ALIPAY_PUBLIC_KEY_PEM)

    def test_missing_sign_rejected(self):
        params = self._make_params()
        del params["sign"]
        assert not verify_alipay_rsa2_signature(params, _ALIPAY_PUBLIC_KEY_PEM)

    def test_wrong_sign_type_rejected(self):
        params = self._make_params()
        params["sign_type"] = "RSA"
        assert not verify_alipay_rsa2_signature(params, _ALIPAY_PUBLIC_KEY_PEM)

    def test_wrong_public_key_rejected(self):
        params = self._make_params()
        _, wrong_pub_pem = _gen_rsa_keypair()
        assert not verify_alipay_rsa2_signature(params, wrong_pub_pem)


# ─── 签名字符串构建 ───────────────────────────────────────────────────────────────

class TestBuildAlipaySignString:

    def test_excludes_sign_and_sign_type(self):
        params = {"a": "1", "b": "2", "sign": "xxx", "sign_type": "RSA2"}
        result = _build_alipay_sign_string(params)
        assert "sign" not in result.split("&")[0].split("=")[0]
        assert result == "a=1&b=2"

    def test_sorted_alphabetically(self):
        params = {"z": "last", "a": "first", "m": "mid"}
        result = _build_alipay_sign_string(params)
        assert result == "a=first&m=mid&z=last"

    def test_empty_values_excluded(self):
        params = {"a": "1", "b": "", "c": "3"}
        result = _build_alipay_sign_string(params)
        assert "b=" not in result
        assert result == "a=1&c=3"
