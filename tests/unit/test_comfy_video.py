from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import urllib.request

from app.services import comfy_video


class _FakeHTTPResponse:
    def __init__(
        self,
        payload: dict[str, object] | None = None,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        if self._body is not None:
            return self._body
        return json.dumps(self._payload).encode("utf-8")


def test_wan_workflow_uses_installed_wan_video_wrapper_nodes() -> None:
    workflow = comfy_video._wan_workflow("slow dolly in", "input_keyframe.png", 5)

    classes = {node["class_type"] for node in workflow.values()}

    assert "LoadWanVideoT5TextEncoder" in classes
    assert "LoadWanVideoClipTextEncoder" in classes
    assert "WanVideoImageClipEncode" in classes
    assert "WanVideoBlockSwap" in classes
    assert "WanVideoModelLoader" in classes
    assert "WanVideoSampler" in classes
    assert "WanVideoDecode" in classes
    assert "VHS_VideoCombine" in classes
    assert "WanVideoTextEncoder" not in classes


def test_wan_workflow_matches_installed_model_filenames() -> None:
    workflow = comfy_video._wan_workflow("slow dolly in", "input_keyframe.png", 5)

    serialized = str(workflow)

    assert "Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors" in serialized
    assert "umt5-xxl-enc-fp8_e4m3fn.safetensors" in serialized
    assert "open-clip-xlm-roberta-large-vit-huge-14_fp16.safetensors" in serialized
    assert "Wan2_1_VAE_bf16.safetensors" in serialized
    assert "Wan2.1-I2V-14B-480P.safetensors" not in serialized


def test_generate_ltx_video_still_submits_legacy_comfy_workflow(monkeypatch) -> None:
    submitted: dict[str, object] = {}
    def submit_workflow(workflow: dict[str, object]) -> str:
        submitted["workflow"] = workflow
        return "prompt-123"

    monkeypatch.setattr(comfy_video, "_submit_workflow", submit_workflow)
    monkeypatch.setattr(
        comfy_video,
        "_poll_result",
        lambda prompt_id, **_: {
            "url": "http://127.0.0.1:8188/view?filename=wan_output.mp4",
            "width": 832,
            "height": 480,
            "prompt_id": prompt_id,
        },
    )

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 5, "image_url": "/storage/projects/demo/shot.png"},
        provider="ltx",
    )

    workflow = submitted["workflow"]
    assert isinstance(workflow, dict)
    assert workflow["3"]["class_type"] == "LTXVideoSampler"
    assert result["provider"] == "comfyui_ltx"
    assert result["prompt_id"] == "prompt-123"


def test_generate_wan_video_calls_inference_api_with_uploaded_local_image(monkeypatch) -> None:
    image_path = Path("storage/test_inputs/wan_api_unit_shot.png")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-png")
    download_dir = Path("storage/test_ltx_downloads")
    calls: list[urllib.request.Request] = []

    monkeypatch.setattr(
        comfy_video,
        "get_settings",
        lambda: SimpleNamespace(
            comfyui_base_url="http://127.0.0.1:8188",
            comfyui_api_key="",
            ltx_api_base_url="http://127.0.0.1:6008",
            ltx_api_key="sk-test",
            inference_api_base_url="http://127.0.0.1:8100",
            inference_api_key="sk-legacy",
        ),
    )

    def fake_urlopen(req: urllib.request.Request, timeout: int = 0) -> _FakeHTTPResponse:
        calls.append(req)
        url = req.full_url
        if url.endswith("/v1/files/upload"):
            assert req.get_header("Authorization") == "Bearer sk-test"
            assert b'filename="wan_api_unit_shot.png"' in (req.data or b"")
            assert b'name="purpose"' not in (req.data or b"")
            return _FakeHTTPResponse({"file_id": "file_input_1"})
        if url.endswith("/v1/video/generate") and req.get_method() == "POST":
            body = json.loads((req.data or b"{}").decode("utf-8"))
            assert body["image"] == "file_input_1"
            assert body["prompt"] == "slow dolly in"
            assert body["duration"] == 15
            assert body["width"] == 1088
            assert body["height"] == 960
            assert body["steps"] == 20
            return _FakeHTTPResponse({"task_id": "task_1", "id": "task_1", "status": "pending"})
        if url.endswith("/v1/tasks/task_1"):
            return _FakeHTTPResponse(
                {
                    "task_id": "task_1",
                    "status": "completed",
                    "output": {
                        "file_id": "file_out_1",
                        "url": "/v1/files/file_out_1",
                        "width": 1088,
                        "height": 960,
                        "duration": 15.0,
                    },
                }
            )
        if url.endswith("/v1/files/file_out_1"):
            assert req.get_header("Authorization") == "Bearer sk-test"
            return _FakeHTTPResponse(body=b"mp4-bytes", headers={"content-type": "video/mp4"})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(comfy_video.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(comfy_video, "LTX_DOWNLOAD_DIR", download_dir)

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 3, "image_url": str(image_path), "timeout": 30},
        provider="wan",
    )

    try:
        assert [call.full_url for call in calls] == [
            "http://127.0.0.1:6008/v1/files/upload",
            "http://127.0.0.1:6008/v1/video/generate",
            "http://127.0.0.1:6008/v1/tasks/task_1",
            "http://127.0.0.1:6008/v1/files/file_out_1",
        ]
        assert result == {
            "url": "/api/media/local/ltx/file_out_1.mp4",
            "width": 1088,
            "height": 960,
            "duration": 15.0,
            "provider": "ltx_api_wan2.1",
            "prompt_id": "task_1",
            "ltx_file_id": "file_out_1",
        }
        assert (download_dir / "file_out_1.mp4").read_bytes() == b"mp4-bytes"
    finally:
        image_path.unlink(missing_ok=True)
        for path in download_dir.glob("*"):
            path.unlink(missing_ok=True)
        download_dir.rmdir()


def test_generate_wan21_provider_alias_uses_inference_api(monkeypatch) -> None:
    submitted: dict[str, object] = {}

    monkeypatch.setattr(comfy_video, "_inference_image_ref", lambda image_ref: "file_input_1")
    monkeypatch.setattr(
        comfy_video,
        "_submit_inference_job",
        lambda payload: submitted.setdefault("payload", payload) or "job_1",
    )
    monkeypatch.setattr(
        comfy_video,
        "_poll_inference_job",
        lambda job_id, timeout=0: {
            "task_id": job_id,
            "status": "completed",
            "output": {"url": "/v1/files/file_out_1", "width": 1088, "height": 960, "duration": 15.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", "file_out_1"),
    )

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 3, "image_url": "file_input_1", "width": 1080, "height": 960},
        provider="wan2.1",
    )

    assert submitted["payload"]["image"] == "file_input_1"
    assert submitted["payload"]["duration"] == 15
    assert submitted["payload"]["width"] == 1088
    assert submitted["payload"]["height"] == 960
    assert result["provider"] == "ltx_api_wan2.1"


def test_generate_ltx23_provider_uses_ltx_api(monkeypatch) -> None:
    submitted: dict[str, object] = {}

    monkeypatch.setattr(comfy_video, "_inference_image_ref", lambda image_ref: "file_input_1")
    monkeypatch.setattr(
        comfy_video,
        "_submit_inference_job",
        lambda payload: submitted.setdefault("payload", payload) or "job_1",
    )
    monkeypatch.setattr(
        comfy_video,
        "_poll_inference_job",
        lambda job_id, timeout=0: {
            "task_id": job_id,
            "status": "completed",
            "output": {"url": "/v1/files/file_out_1", "width": 1088, "height": 960, "duration": 15.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", "file_out_1"),
    )

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 3, "image_url": "file_input_1", "width": 1080, "height": 960},
        provider="ltx2.3",
    )

    assert submitted["payload"]["image"] == "file_input_1"
    assert submitted["payload"]["duration"] == 15
    assert submitted["payload"]["width"] == 1088
    assert submitted["payload"]["height"] == 960
    assert result["provider"] == "ltx_api_ltx2.3"


def test_ltx_poll_retries_transient_request_errors(monkeypatch) -> None:
    calls = {"count": 0}

    def flaky_get(path: str, *, timeout: int = 30) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Inference API request error: <urlopen error [Errno -5] No address associated with hostname>")
        return {
            "task_id": "job_1",
            "status": "completed",
            "output": {"file_id": "file_out_1", "url": "/v1/files/file_out_1"},
        }

    monkeypatch.setattr(comfy_video, "_inference_get", flaky_get)
    monkeypatch.setattr(comfy_video.time, "sleep", lambda _seconds: None)

    result = comfy_video._poll_inference_job("job_1", timeout=30)

    assert calls["count"] == 2
    assert result["status"] == "completed"
