from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routes import agent_runs


def test_video_pool_provider_allows_wan() -> None:
    # 注：_normalize_video_pool_provider 返回规范名（注册表中的标准名）
    assert agent_runs._normalize_video_pool_provider("wan") == "wan2.1"


def test_video_pool_provider_allows_wan21_aliases() -> None:
    assert agent_runs._normalize_video_pool_provider("wan2.1") == "wan2.1"
    assert agent_runs._normalize_video_pool_provider("wan2_1") == "wan2.1"


def test_video_pool_provider_allows_ltx23() -> None:
    assert agent_runs._normalize_video_pool_provider("ltx2.3") == "ltx2.3"
    assert agent_runs._normalize_video_pool_provider("LTX2.3") == "ltx2.3"


def test_video_pool_provider_allows_joy_echo() -> None:
    assert agent_runs._normalize_video_pool_provider("joy-echo") == "joy-echo"
    assert agent_runs._normalize_video_pool_provider("JOY-ECHO") == "joy-echo"


def test_video_pool_provider_rejects_unknown_provider() -> None:
    with pytest.raises(HTTPException) as exc:
        agent_runs._normalize_video_pool_provider("unknown")

    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert "wan" in detail["allowed"]
