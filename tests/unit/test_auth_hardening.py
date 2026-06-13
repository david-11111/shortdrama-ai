from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_backend_register_schema_min_length_is_10():
    text = _read("app/schemas/auth.py")
    assert "Field(min_length=10" in text


def test_backend_auth_route_has_lockout_and_logout_blacklist_logic():
    text = _read("app/routes/auth.py")
    assert "MAX_FAILED_LOGIN_ATTEMPTS = 5" in text
    assert "LOGIN_LOCK_SECONDS = 15 * 60" in text
    assert "Password too weak" in text
    assert "@router.post(\"/logout\")" in text
    assert "await blacklist_token(" in text
    assert "user_id=int(current_user[\"id\"])" in text


def test_backend_middleware_checks_token_blacklist():
    text = _read("app/middleware/auth.py")
    assert "from app.security.token_blacklist import is_token_blacklisted" in text
    assert "if await is_token_blacklisted(token_jti):" in text
    assert "Token has been revoked" in text


def test_backend_ws_checks_token_blacklist_before_accept():
    text = _read("app/ws/task_updates.py")
    assert "from app.security.token_blacklist import is_token_blacklisted" in text
    assert "from app.services.auth import decode_token, get_token_jti" in text
    assert "if await is_token_blacklisted(token_jti):" in text
    assert "await websocket.accept()" in text


def test_frontend_user_type_matches_backend_user_id_number():
    text = _read("frontend/src/types/api.ts")
    assert "user_id: number" in text


def test_frontend_logout_calls_backend_endpoint():
    api_text = _read("frontend/src/api/auth.ts")
    store_text = _read("frontend/src/stores/auth.ts")

    assert "logout()" in api_text
    assert "'/auth/logout'" in api_text
    assert "await authApi.logout()" in store_text
    assert "await authStore.logout({ remote: false })" in _read("frontend/src/api/client.ts")
