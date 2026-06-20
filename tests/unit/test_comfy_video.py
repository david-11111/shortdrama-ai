from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import urllib.request

import pytest

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


def test_ltx_custom_video_api_env_aliases_are_used(monkeypatch) -> None:
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_API_BASE_URL", "http://127.0.0.1:7001")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_API_KEY", "custom-key")
    monkeypatch.setattr(
        comfy_video,
        "get_settings",
        lambda: SimpleNamespace(
            comfyui_base_url="http://127.0.0.1:8188",
            comfyui_api_key="",
            ltx_api_base_url="",
            ltx_api_key="",
            inference_api_base_url="http://127.0.0.1:8100",
            inference_api_key="sk-legacy",
        ),
    )

    assert comfy_video._inference_api_url("/v1/tasks/job_1") == "http://127.0.0.1:7001/v1/tasks/job_1"
    assert comfy_video._inference_api_key() == "custom-key"


def test_joy_echo_inference_api_uses_joy_echo_base_url_and_key(monkeypatch) -> None:
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        comfy_video,
        "get_settings",
        lambda: SimpleNamespace(
            comfyui_api_key="comfy-key",
            ltx_api_base_url="https://ltx.example.test",
            ltx_api_key="ltx-key",
            inference_api_base_url="https://fallback.example.test",
            inference_api_key="fallback-key",
            joy_echo_api_base_url="https://joy.example.test",
            joy_echo_api_key="joy-key",
        ),
    )

    def fake_urlopen(req: urllib.request.Request, timeout: int = 0) -> _FakeHTTPResponse:
        captured["url"] = req.full_url
        captured["authorization"] = req.get_header("Authorization")
        return _FakeHTTPResponse({"task_id": "joy_job_1", "status": "pending"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = comfy_video._inference_json_request(
        "/v1/video/generate",
        {"prompt": "slow dolly in"},
        provider="joy-echo",
    )

    assert result["task_id"] == "joy_job_1"
    assert captured["url"] == "https://joy.example.test/v1/video/generate"
    assert captured["authorization"] == "Bearer joy-key"


def test_joy_echo_api_base_url_requires_joy_echo_key(monkeypatch) -> None:
    monkeypatch.setattr(
        comfy_video,
        "get_settings",
        lambda: SimpleNamespace(
            comfyui_api_key="comfy-key",
            ltx_api_base_url="https://ltx.example.test",
            ltx_api_key="ltx-key",
            inference_api_base_url="https://fallback.example.test",
            inference_api_key="fallback-key",
            joy_echo_api_base_url="https://joy.example.test",
            joy_echo_api_key="",
        ),
    )

    with pytest.raises(RuntimeError, match="JOY_ECHO_API_KEY"):
        comfy_video._inference_api_key(provider="joy-echo")


def test_ltx_upload_accepts_id_alias(monkeypatch) -> None:
    image_path = Path("storage/test_inputs/ltx_upload_id_alias.png")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-png")

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
        assert req.full_url == "http://127.0.0.1:6008/v1/files/upload"
        return _FakeHTTPResponse({"id": "file_input_from_id"})

    monkeypatch.setattr(comfy_video.urllib.request, "urlopen", fake_urlopen)

    try:
        assert comfy_video._upload_image_to_inference_api(image_path) == "file_input_from_id"
    finally:
        image_path.unlink(missing_ok=True)


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
            assert body["duration"] == 3.0
            assert body["width"] == 960
            assert body["height"] == 544
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
                        "width": 960,
                        "height": 544,
                        "duration": 3.0,
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
            "width": 960,
            "height": 544,
            "duration": 3.0,
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
            "output": {"url": "/v1/files/file_out_1", "width": 960, "height": 544, "duration": 15.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", "file_out_1"),
    )

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 3, "image_url": "file_input_1"},
        provider="wan2.1",
    )

    assert submitted["payload"]["image"] == "file_input_1"
    assert submitted["payload"]["duration"] == 3.0
    assert submitted["payload"]["width"] == 960
    assert submitted["payload"]["height"] == 544
    assert result["provider"] == "ltx_api_wan2.1"


def test_generate_ltx23_provider_uses_text_only_ltx_api(monkeypatch) -> None:
    submitted: dict[str, object] = {}

    monkeypatch.setattr(
        comfy_video,
        "_inference_image_ref",
        lambda image_ref: (_ for _ in ()).throw(AssertionError("ltx2.3 must not upload reference images")),
    )
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
            "output": {"url": "/v1/files/file_out_1", "width": 960, "height": 544, "duration": 15.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", "file_out_1"),
    )

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 3, "image_url": "file_input_1"},
        provider="ltx2.3",
    )

    assert "image" not in submitted["payload"]
    assert submitted["payload"]["duration"] == 3.0
    assert submitted["payload"]["width"] == 960
    assert submitted["payload"]["height"] == 544
    assert result["provider"] == "ltx_api_ltx2.3"


def test_generate_joy_echo_provider_uses_inference_api(monkeypatch) -> None:
    submitted: dict[str, object] = {}

    monkeypatch.setattr(
        comfy_video,
        "_inference_image_ref",
        lambda image_ref: (_ for _ in ()).throw(AssertionError("joy-echo must not upload reference images")),
    )
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
            "output": {"url": "/v1/files/file_out_1", "width": 960, "height": 544, "duration": 15.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", "file_out_1"),
    )

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 3, "image_url": "file_input_1"},
        provider="joy-echo",
    )

    assert "image" not in submitted["payload"]
    assert submitted["payload"]["duration"] == 30.0
    assert submitted["payload"]["width"] == 960
    assert submitted["payload"]["height"] == 544
    assert result["provider"] == "joy_echo_api"


def test_generate_joy_echo_duration_starts_at_30_seconds(monkeypatch) -> None:
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
            "output": {"url": "/v1/files/file_out_1", "width": 960, "height": 544, "duration": 30.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", "file_out_1"),
    )

    comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 3, "image_url": "file_input_1"},
        provider="joy-echo",
    )

    assert submitted["payload"]["duration"] == 30.0


def test_generate_joy_echo_long_duration_is_not_ltx_segmented(monkeypatch) -> None:
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
            "output": {"url": "/v1/files/file_out_1", "width": 960, "height": 544, "duration": 120.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", "file_out_1"),
    )
    monkeypatch.setattr(
        comfy_video,
        "_generate_ltx_segmented_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("joy-echo must not use LTX segmentation")),
    )

    comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 120, "image_url": "file_input_1"},
        provider="joy-echo",
    )

    assert submitted["payload"]["duration"] == 120.0


def test_generate_ltx23_uses_custom_video_api_env_defaults(monkeypatch) -> None:
    submitted: dict[str, object] = {}

    monkeypatch.setenv("LTX_CUSTOM_VIDEO_WIDTH", "832")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_HEIGHT", "480")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_DURATION", "3")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_STEPS", "24")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_MODE", "quality")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_PROFILE", "current_quality")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_CFG_SCALE", "2.5")
    monkeypatch.setenv("LTX_CUSTOM_VIDEO_STG_SCALE", "0.7")
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
            "status": "done",
            "result": {"file_id": "file_out_1", "width": 832, "height": 480, "duration": 3.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", file_id),
    )

    result = comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "image_url": "file_input_1"},
        provider="ltx2.3",
    )

    assert submitted["payload"] == {
        "prompt": "slow dolly in",
        "duration": 3.0,
        "width": 832,
        "height": 480,
        "steps": 24,
        "mode": "quality",
        "profile": "current_quality",
        "cfg_scale": 2.5,
        "stg_scale": 0.7,
    }
    assert result["url"] == "/api/media/local/ltx/file_out_1.mp4"
    assert result["ltx_file_id"] == "file_out_1"
    assert result["provider"] == "ltx_api_ltx2.3"


def test_generate_ltx23_payload_duration_overrides_custom_default(monkeypatch) -> None:
    submitted: dict[str, object] = {}

    monkeypatch.setenv("LTX_CUSTOM_VIDEO_DURATION", "1")
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
            "status": "done",
            "result": {"file_id": "file_out_1", "width": 512, "height": 288, "duration": 4.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": ("/api/media/local/ltx/file_out_1.mp4", file_id),
    )

    comfy_video.generate_comfy_video(
        {"prompt": "slow dolly in", "duration": 4, "image_url": "file_input_1"},
        provider="ltx2.3",
    )

    assert submitted["payload"]["duration"] == 4.0


def test_generate_ltx23_long_duration_segments_and_concats(monkeypatch) -> None:
    submitted: list[dict[str, object]] = []
    download_dir = Path("storage/test_ltx_long_concat_case")
    output_path = download_dir / "joined.mp4"
    download_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(comfy_video, "LTX_DOWNLOAD_DIR", download_dir)
    monkeypatch.setattr(
        comfy_video,
        "_inference_image_ref",
        lambda image_ref: (_ for _ in ()).throw(AssertionError("ltx2.3 must not upload reference images")),
    )

    def submit(payload: dict[str, object]) -> str:
        submitted.append(payload)
        return f"job_{len(submitted)}"

    monkeypatch.setattr(comfy_video, "_submit_inference_job", submit)
    monkeypatch.setattr(
        comfy_video,
        "_poll_inference_job",
        lambda job_id, timeout=0: {
            "task_id": job_id,
            "status": "done",
            "result": {
                "file_id": f"file_out_{job_id.rsplit('_', 1)[-1]}",
                "width": 512,
                "height": 288,
                "duration": 15.0,
            },
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": (f"/api/media/local/ltx/{file_id}.mp4", file_id),
    )

    def fake_export(sources, out_path, **_kwargs):
        assert sources == [
            "/api/media/local/ltx/file_out_1.mp4",
            "/api/media/local/ltx/file_out_2.mp4",
        ]
        output_path.write_bytes(b"joined-mp4")
        Path(out_path).write_bytes(output_path.read_bytes())
        return {"duration_sec": 30.0, "file_size": len(b"joined-mp4"), "clip_count": 2}

    import app.services.video_edit as video_edit

    monkeypatch.setattr(video_edit, "export_final_video", fake_export)

    try:
        result = comfy_video.generate_comfy_video(
            {"prompt": "slow dolly in", "duration": 30, "image_url": "file_input_1", "width": 512, "height": 288},
            provider="ltx2.3",
        )

        assert [payload["duration"] for payload in submitted] == [15.0, 15.0]
        assert all("image" not in payload for payload in submitted)
        assert result["duration"] == 30.0
        assert result["provider"] == "ltx_api_ltx2.3"
        assert result["url"].startswith("/api/media/local/ltx/")
        assert (download_dir / result["url"].rsplit("/", 1)[-1]).read_bytes() == b"joined-mp4"
    finally:
        for path in download_dir.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        if download_dir.exists() and not any(download_dir.iterdir()):
            download_dir.rmdir()


def test_ltx23_extracts_completed_output_from_result_file_id(monkeypatch) -> None:
    monkeypatch.setattr(
        comfy_video,
        "_poll_inference_job",
        lambda job_id, timeout=0: {
            "task_id": job_id,
            "status": "done",
            "result": {"file_id": "file_out_1", "width": 832, "height": 480, "duration": 3.0},
        },
    )
    monkeypatch.setattr(
        comfy_video,
        "_download_ltx_output_locally",
        lambda url, *, file_id="": (f"/api/media/local/ltx/{file_id}.mp4", file_id),
    )

    result = comfy_video._complete_ltx_inference_result(
        "job_1",
        {"duration": 3.0, "width": 832, "height": 480},
        timeout=30,
        provider="ltx2.3",
    )

    assert result == {
        "url": "/api/media/local/ltx/file_out_1.mp4",
        "width": 832,
        "height": 480,
        "duration": 3.0,
        "provider": "ltx_api_ltx2.3",
        "prompt_id": "job_1",
        "ltx_file_id": "file_out_1",
    }


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
