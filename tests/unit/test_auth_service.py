"""
单元测试 — JWT 生成与验证（不依赖 DB）。
"""
import pytest
from datetime import timedelta

pytestmark = [pytest.mark.unit]


def test_access_token_decode_roundtrip():
    from app.services.auth import create_access_token, decode_token
    token = create_access_token({"sub": "42"})
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_refresh_token_type():
    from app.services.auth import create_refresh_token, decode_token
    token = create_refresh_token({"sub": "42"})
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_expired_token_raises():
    from app.services.auth import create_access_token, decode_token
    from jose import JWTError
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(JWTError):
        decode_token(token)


def test_password_hash_verify():
    from app.services.auth import hash_password, verify_password
    hashed = hash_password("MySecret123!")
    assert verify_password("MySecret123!", hashed)
    assert not verify_password("WrongPass", hashed)
