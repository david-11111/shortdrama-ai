from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def _storage_dir() -> Path:
    path = Path("storage/test_joy_echo_api")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_server(monkeypatch):
    storage_dir = _storage_dir()
    monkeypatch.setenv("JOY_ECHO_API_KEY", "joy-secret")
    monkeypatch.setenv("JOY_ECHO_API_STORAGE_DIR", str(storage_dir))
    module = importlib.import_module("provider_servers.joy_echo_api.main")
    return importlib.reload(module), storage_dir


def test_joy_echo_api_health_is_public_and_v1_requires_bearer_key(monkeypatch):
    joy_api, _storage_dir = _load_server(monkeypatch)
    client = TestClient(joy_api.app)

    assert client.get("/health").status_code == 200
    assert client.post("/v1/video/generate", json={"prompt": "p"}).status_code == 401
    assert client.post(
        "/v1/video/generate",
        json={"prompt": "p"},
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 401


def test_joy_echo_api_generates_task_and_serves_completed_file(monkeypatch):
    joy_api, storage_dir = _load_server(monkeypatch)

    def fake_run_task(task_id: str) -> None:
        file_id = "file-1"
        output_path = storage_dir / f"{file_id}.mp4"
        output_path.write_bytes(b"fake-video")
        joy_api.FILES[file_id] = output_path
        joy_api.TASKS[task_id].update(
            {
                "status": "completed",
                "progress": {"percentage": 100, "message": "Completed"},
                "output": {"file_id": file_id, "url": f"/v1/files/{file_id}", "duration": 30.0},
                "outputs": [
                    {
                        "id": file_id,
                        "type": "video",
                        "mime_type": "video/mp4",
                        "url": f"/v1/files/{file_id}",
                    }
                ],
                "error_message": None,
            }
        )

    monkeypatch.setattr(joy_api, "_run_task", fake_run_task)
    client = TestClient(joy_api.app)
    headers = {"Authorization": "Bearer joy-secret"}

    response = client.post("/v1/video/generate", json={"prompt": "p"}, headers=headers)
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    task_response = client.get(f"/v1/tasks/{task_id}", headers=headers)
    assert task_response.status_code == 200
    assert task_response.json()["status"] == "completed"
    assert task_response.json()["output"]["url"] == "/v1/files/file-1"

    file_response = client.get("/v1/files/file-1", headers=headers)
    assert file_response.status_code == 200
    assert file_response.content == b"fake-video"
