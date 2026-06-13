from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.routes.media import router


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_ltx_file_proxy_downloads_with_server_side_bearer_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.routes.media.get_settings",
        lambda: SimpleNamespace(
            ltx_api_base_url="https://ltx.example.test",
            ltx_api_key="ltx-secret",
            inference_api_base_url="",
            inference_api_key="",
        ),
    )

    def fake_download(url: str, api_key: str) -> tuple[bytes, str]:
        captured["url"] = url
        captured["api_key"] = api_key
        return b"mp4-bytes", "video/mp4"

    monkeypatch.setattr("app.routes.media._download_ltx_file", fake_download)

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/media/ltx/files/file_out_1")

    assert response.status_code == 200
    assert response.content == b"mp4-bytes"
    assert response.headers["content-type"] == "video/mp4"
    assert captured["url"] == "https://ltx.example.test/v1/files/file_out_1"
    assert captured["api_key"] == "ltx-secret"


@pytest.mark.asyncio
async def test_local_ltx_file_serves_downloaded_video(monkeypatch) -> None:
    local_dir = Path("storage/test_ltx_route")
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "file_out_1.mp4").write_bytes(b"local-mp4")
    monkeypatch.setattr("app.routes.media.LOCAL_LTX_DIR", local_dir)

    try:
        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/media/local/ltx/file_out_1.mp4")

        assert response.status_code == 200
        assert response.content == b"local-mp4"
        assert response.headers["content-type"] == "video/mp4"
    finally:
        for path in local_dir.glob("*"):
            path.unlink(missing_ok=True)
        local_dir.rmdir()
