from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routes import agent_runs


def test_video_pool_provider_allows_wan() -> None:
    assert agent_runs._normalize_video_pool_provider("wan") == "wan"


def test_video_pool_provider_allows_wan21_aliases() -> None:
    assert agent_runs._normalize_video_pool_provider("wan2.1") == "wan2.1"
    assert agent_runs._normalize_video_pool_provider("wan2_1") == "wan2_1"


def test_video_pool_provider_allows_ltx23() -> None:
    assert agent_runs._normalize_video_pool_provider("ltx2.3") == "ltx2.3"
    assert agent_runs._normalize_video_pool_provider("LTX2.3") == "ltx2.3"


def test_video_pool_provider_rejects_unknown_provider() -> None:
    with pytest.raises(HTTPException) as exc:
        agent_runs._normalize_video_pool_provider("unknown")

    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert "wan" in detail["allowed"]
