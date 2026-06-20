"""ComfyUI video generation adapter for SaaS video_gen tasks."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from app.config import get_settings

LOGGER = logging.getLogger(__name__)


def _should_use_local_ltx() -> bool:
    """Check if the local LTX Desktop should be preferred over the remote API."""
    s = get_settings()
    if not getattr(s, "ltx_desktop_auto_launch", False):
        return False
    if not getattr(s, "ltx_desktop_install_path", ""):
        return False
    install_path = Path(s.ltx_desktop_install_path)
    return install_path.exists() and (install_path / "api_login_launcher.py").exists()


def _ltx_workflow(prompt: str, image_url: str, duration: int) -> dict[str, Any]:
    width = 720
    height = 1280
    frame_count = max(1, int(duration * 24))
    seed = int(time.time() * 1000) % (2**32)

    return {
        "3": {
            "class_type": "LTXVideoSampler",
            "inputs": {
                "model": ["LTXVideoModelLoader", 0],
                "positive": ["CLIPTextEncode", 0],
                "negative": ["CLIPTextEncode", 1],
                "vae": ["LTXVideoVAELoader", 0],
                "seed": seed,
                "steps": 20,
                "cfg": 3.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "frame_count": frame_count,
                "width": width,
                "height": height,
            },
        },
        "6": {
            "class_type": "LTXVideoModelLoader",
            "inputs": {"model_name": "ltx-video-2b-0.9.1.safetensors"},
        },
        "8": {"class_type": "LTXVideoVAELoader", "inputs": {}},
        "9": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["LTXVideoModelLoader", 1]},
        },
        "10": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "blurry, low quality, distorted, ugly, bad anatomy, watermark, text",
                "clip": ["LTXVideoModelLoader", 1],
            },
        },
        "12": {"class_type": "LoadImage", "inputs": {"image": image_url}},
        "13": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["LTXVideoSampler", 0],
                "frame_rate": 24,
                "loop_count": 0,
                "filename_prefix": "ltx_output",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
            },
        },
    }


def _wan_workflow(prompt: str, image_url: str, duration: int, negative_prompt: str = "") -> dict[str, Any]:
    width = 832
    height = 480
    frame_count = 49
    seed = int(time.time() * 1000) % (2**32)
    negative = negative_prompt or "blurry, low quality, distorted, ugly, bad anatomy, watermark, text"

    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_url}},
        "2": {
            "class_type": "WanVideoVAELoader",
            "inputs": {"model_name": "Wan2_1_VAE_bf16.safetensors", "precision": "bf16"},
        },
        "3": {
            "class_type": "LoadWanVideoT5TextEncoder",
            "inputs": {
                "model_name": "umt5-xxl-enc-fp8_e4m3fn.safetensors",
                "precision": "bf16",
                "load_device": "offload_device",
                "quantization": "fp8_e4m3fn",
            },
        },
        "4": {
            "class_type": "LoadWanVideoClipTextEncoder",
            "inputs": {
                "model_name": "open-clip-xlm-roberta-large-vit-huge-14_fp16.safetensors",
                "precision": "fp16",
                "load_device": "offload_device",
            },
        },
        "5": {
            "class_type": "WanVideoTextEncode",
            "inputs": {
                "t5": ["3", 0],
                "positive_prompt": prompt,
                "negative_prompt": negative,
                "force_offload": True,
            },
        },
        "6": {
            "class_type": "WanVideoImageClipEncode",
            "inputs": {
                "clip": ["4", 0],
                "image": ["1", 0],
                "vae": ["2", 0],
                "generation_width": width,
                "generation_height": height,
                "num_frames": frame_count,
                "force_offload": True,
                "noise_aug_strength": 0.02,
                "latent_strength": 1.0,
                "clip_embed_strength": 1.0,
            },
        },
        "7": {"class_type": "WanVideoBlockSwap", "inputs": {"blocks_to_swap": 20}},
        "8": {
            "class_type": "WanVideoModelLoader",
            "inputs": {
                "model": "Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors",
                "base_precision": "bf16",
                "quantization": "fp8_e4m3fn",
                "load_device": "main_device",
                "attention_mode": "sdpa",
                "block_swap_args": ["7", 0],
            },
        },
        "9": {
            "class_type": "WanVideoSampler",
            "inputs": {
                "model": ["8", 0],
                "text_embeds": ["5", 0],
                "image_embeds": ["6", 0],
                "steps": 20,
                "cfg": 5.5,
                "shift": 5.0,
                "seed": seed,
                "force_offload": True,
                "scheduler": "dpm++",
                "riflex_freq_index": 0,
                "denoise_strength": 1.0,
            },
        },
        "10": {
            "class_type": "WanVideoDecode",
            "inputs": {
                "vae": ["2", 0],
                "samples": ["9", 0],
                "enable_vae_tiling": True,
                "tile_x": 272,
                "tile_y": 272,
                "tile_stride_x": 144,
                "tile_stride_y": 128,
            },
        },
        "11": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["10", 0],
                "frame_rate": 16,
                "loop_count": 0,
                "filename_prefix": "wan_output",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
            },
        },
    }


_WORKFLOW_BUILDERS = {
    "ltx": _ltx_workflow,
    "wan": _wan_workflow,
}

_JOY_ECHO_PROVIDERS = {"joy-echo", "joy_echo", "joyai-echo", "joyai_echo"}
_LTX_API_PROVIDERS = {"ltx2.3", "wan", "wan2.1", "wan2_1", *_JOY_ECHO_PROVIDERS}
LTX_DOWNLOAD_DIR = Path("storage") / "ltx_downloads"
LTX_MIN_DURATION_SECONDS = 15.0
LTX_REMOTE_MAX_DURATION_SECONDS = 15.0
JOY_ECHO_MIN_DURATION_SECONDS = 30.0
JOY_ECHO_REMOTE_MAX_DURATION_SECONDS = 300.0
LTX_MIN_WIDTH = 960
LTX_MIN_HEIGHT = 544


def _env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _env_float(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _ceil_to_multiple(value: int, multiple: int) -> int:
    value = max(1, int(value or 1))
    return ((value + multiple - 1) // multiple) * multiple


def _comfyui_url() -> str:
    settings = get_settings()
    return (settings.comfyui_base_url or "http://127.0.0.1:8188").rstrip("/")


def _comfyui_api_url(path: str) -> str:
    return f"{_comfyui_url()}{path}"


def _is_joy_echo_provider(provider: str) -> bool:
    return str(provider or "").strip().lower() in _JOY_ECHO_PROVIDERS


def _joy_echo_api_base_url() -> str:
    settings = get_settings()
    return str(getattr(settings, "joy_echo_api_base_url", "") or "").rstrip("/")


def _use_joy_echo_api_config(provider: str) -> bool:
    return _is_joy_echo_provider(provider) and bool(_joy_echo_api_base_url())


def _inference_api_url(path: str, *, provider: str = "") -> str:
    settings = get_settings()
    if _is_joy_echo_provider(provider):
        base_url = _joy_echo_api_base_url()
        if base_url:
            return f"{base_url}{path}"
    base_url = str(
        getattr(settings, "ltx_api_base_url", "")
        or os.getenv("LTX_CUSTOM_VIDEO_API_BASE_URL", "")
        or getattr(settings, "inference_api_base_url", "")
        or "http://127.0.0.1:8100"
    ).rstrip("/")
    return f"{base_url}{path}"


def _inference_api_key(*, provider: str = "") -> str:
    settings = get_settings()
    if _use_joy_echo_api_config(provider):
        api_key = str(getattr(settings, "joy_echo_api_key", "") or "")
        if api_key:
            return api_key
        raise RuntimeError("JOY_ECHO_API_KEY is required when JOY_ECHO_API_BASE_URL is configured")
    return str(
        getattr(settings, "ltx_api_key", "")
        or os.getenv("LTX_CUSTOM_VIDEO_API_KEY", "")
        or getattr(settings, "inference_api_key", "")
        or getattr(settings, "comfyui_api_key", "")
        or "sk-default-dev-key"
    )


def _inference_headers(extra: dict[str, str] | None = None, *, provider: str = "") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_inference_api_key(provider=provider)}"}
    if extra:
        headers.update(extra)
    return headers


def _inference_json_request(
    path: str,
    payload: dict[str, Any],
    *,
    timeout: int = 60,
    method: str = "POST",
    provider: str = "",
) -> dict[str, Any]:
    req = urllib.request.Request(
        _inference_api_url(path, provider=provider),
        data=json.dumps(payload).encode("utf-8"),
        headers=_inference_headers({"Content-Type": "application/json"}, provider=provider),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Inference API request failed (HTTP {e.code}): {detail}") from e
    except Exception as e:
        raise RuntimeError(f"Inference API request error: {e}") from e
    return data if isinstance(data, dict) else {}


def _inference_get(path: str, *, timeout: int = 30, provider: str = "") -> dict[str, Any]:
    req = urllib.request.Request(
        _inference_api_url(path, provider=provider),
        headers=_inference_headers(provider=provider),
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Inference API request failed (HTTP {e.code}): {detail}") from e
    except Exception as e:
        raise RuntimeError(f"Inference API request error: {e}") from e
    return data if isinstance(data, dict) else {}


def _inference_file_url(url: str) -> str:
    url = str(url or "").strip()
    parsed = urllib.parse.urlparse(url)
    path = parsed.path if parsed.scheme else url
    marker = "/v1/files/"
    if path.startswith(marker):
        file_id = path.removeprefix(marker).strip("/")
        if file_id:
            return f"/api/media/ltx/files/{urllib.parse.quote(file_id, safe='')}"
    if url.startswith(("http://", "https://")):
        return url
    if not url.startswith("/"):
        url = f"/{url}"
    return _inference_api_url(url)


def _ltx_file_id_from_url(url: str) -> str:
    url = str(url or "").strip()
    parsed = urllib.parse.urlparse(url)
    path = parsed.path if parsed.scheme else url
    marker = "/v1/files/"
    if path.startswith(marker):
        return path.removeprefix(marker).strip("/")
    return ""


def _local_ltx_file_url(filename: str) -> str:
    return f"/api/media/local/ltx/{urllib.parse.quote(filename, safe='')}"


def _ltx_result_provider_label(provider: str) -> str:
    provider = str(provider or "").strip().lower()
    if provider in _JOY_ECHO_PROVIDERS:
        return "joy_echo_api"
    if provider == "ltx2.3":
        return "ltx_api_ltx2.3"
    return "ltx_api_wan2.1"


def _download_ltx_output_locally(file_url: str, *, file_id: str = "", provider: str = "") -> tuple[str, str]:
    file_id = (file_id or _ltx_file_id_from_url(file_url)).strip()
    if not file_id or any(ch in file_id for ch in ("/", "\\", "..")):
        raise RuntimeError(f"LTX API returned invalid file_id for local download: {file_id!r}")

    source_url = file_url if file_url.startswith(("http://", "https://")) else _inference_api_url(file_url, provider=provider)
    req = urllib.request.Request(source_url, headers=_inference_headers(provider=provider))
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            content = resp.read()
            content_type = resp.headers.get("content-type", "application/octet-stream")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LTX API file download failed (HTTP {e.code}): {detail}") from e
    except Exception as e:
        raise RuntimeError(f"LTX API file download error: {e}") from e

    ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ".mp4"
    if ext == ".jpe":
        ext = ".jpg"
    filename = f"{file_id}{ext}"
    LTX_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = LTX_DOWNLOAD_DIR / filename
    temp_target = target.with_suffix(target.suffix + ".part")
    temp_target.write_bytes(content)
    temp_target.replace(target)
    return _local_ltx_file_url(filename), file_id


def _download_image_locally(url: str) -> Path:
    """下载远程图片到本地临时文件，供上传到推理 API。

    远程 GPU 服务器出站 HTTPS 可能受限（SSL handshake 超时），
    改为 worker 本地下载后通过 /v1/files/upload 上传。
    """
    suffix = Path(url.split("?", 1)[0]).suffix or ".png"
    temp_dir = Path(os.getenv("TMPDIR") or os.getenv("TEMP") or "/tmp")
    temp_path = temp_dir / f"infer_api_input_{uuid4().hex}{suffix}"
    req = urllib.request.Request(url, headers={"User-Agent": "shortdrama-ai-inference/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            temp_path.write_bytes(resp.read())
    except Exception as e:
        raise RuntimeError(f"Failed to download reference image for inference API: {e}") from e
    return temp_path


def _inference_image_ref(image_ref: str) -> str:
    image_ref = str(image_ref or "").strip()
    if not image_ref:
        raise ValueError("image_url is required for LTX API video generation")
    if image_ref.startswith("file_"):
        return image_ref
    if image_ref.startswith(("http://", "https://")):
        # 远程服务器出站 HTTPS 受限时无法自拉取图片
        # 改为本地下载后上传，绕过远程服务器的 HTTPS 限制
        local_path = _download_image_locally(image_ref)
        return _upload_image_to_inference_api(local_path)
    local_path = _resolve_local_image_path(image_ref)
    if local_path:
        return _upload_image_to_inference_api(local_path)
    return image_ref


def _upload_image_to_inference_api(path: str | Path) -> str:
    path = Path(path)
    filename = path.name
    boundary = f"----shortdrama-infer-api-{uuid4().hex}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_bytes = path.read_bytes()
    body = b"".join(
        [
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + file_bytes
            + b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    req = urllib.request.Request(
        _inference_api_url("/v1/files/upload"),
        data=body,
        headers=_inference_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Inference API upload failed (HTTP {e.code}): {detail}") from e
    except Exception as e:
        raise RuntimeError(f"Inference API upload error: {e}") from e
    file_id = str(data.get("file_id") or data.get("id") or "").strip()
    if not file_id:
        raise RuntimeError(f"Inference API upload did not return file_id: {data}")
    return file_id


def _submit_inference_job(payload: dict[str, Any], *, provider: str = "") -> str:
    data = _inference_json_request("/v1/video/generate", payload, timeout=60, provider=provider)
    job_id = str(data.get("task_id") or data.get("id") or "").strip()
    if not job_id:
        raise RuntimeError(f"LTX API did not return task_id: {data}")
    return job_id


def _ltx_completed_output(result: dict[str, Any]) -> dict[str, Any]:
    for key in ("output", "result", "data", "video"):
        value = result.get(key)
        if isinstance(value, dict):
            return value
    outputs = result.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict):
                return item
    return {}


def _poll_inference_job(job_id: str, timeout: int = 1400, *, provider: str = "") -> dict[str, Any]:
    deadline = time.time() + timeout
    transient_errors = 0
    while time.time() < deadline:
        try:
            if provider:
                data = _inference_get(f"/v1/tasks/{job_id}", timeout=30, provider=provider)
            else:
                data = _inference_get(f"/v1/tasks/{job_id}", timeout=30)
            transient_errors = 0
        except RuntimeError as exc:
            transient_errors += 1
            if transient_errors >= 6:
                raise
            LOGGER.warning("LTX API poll transient error for %s (%s/5): %s", job_id, transient_errors, exc)
            time.sleep(5)
            continue
        status = str(data.get("status") or "").lower()
        if status in {"completed", "succeeded"}:
            return data
        if status == "failed":
            error = data.get("error") if isinstance(data.get("error"), dict) else None
            message = (
                data.get("error_message")
                or (error.get("message") if isinstance(error, dict) else None)
                or data
            )
            code = data.get("error_code") or (error.get("code") if isinstance(error, dict) else "")
            suffix = f" ({code})" if code else ""
            raise RuntimeError(f"LTX API task failed{suffix}: {message}")
        if status in {"cancelled", "canceled"}:
            raise RuntimeError(f"LTX API task was cancelled: {job_id}")
        time.sleep(5)
    raise TimeoutError(f"LTX API task timeout after {timeout}s (task_id={job_id})")


def _complete_ltx_inference_result(
    job_id: str,
    request_payload: dict[str, Any],
    *,
    timeout: int,
    provider: str,
) -> dict[str, Any]:
    use_joy_api = _use_joy_echo_api_config(provider)
    if use_joy_api:
        result = _poll_inference_job(job_id, timeout=timeout, provider=provider)
    else:
        result = _poll_inference_job(job_id, timeout=timeout)
    output = _ltx_completed_output(result)
    url = str(output.get("url") or output.get("video_url") or output.get("output_url") or "").strip()
    file_id = str(output.get("file_id") or output.get("fileId") or _ltx_file_id_from_url(url)).strip()
    if not url and file_id:
        url = f"/v1/files/{file_id}"
    if not url:
        raise RuntimeError(f"LTX API task completed but did not return output url or file_id: {result}")
    if use_joy_api:
        local_url, file_id = _download_ltx_output_locally(url, file_id=file_id, provider=provider)
    else:
        local_url, file_id = _download_ltx_output_locally(url, file_id=file_id)
    return {
        "url": local_url,
        "width": int(output.get("width") or request_payload["width"]),
        "height": int(output.get("height") or request_payload["height"]),
        "duration": float(output.get("duration") or request_payload["duration"]),
        "provider": _ltx_result_provider_label(provider),
        "prompt_id": job_id,
        "ltx_file_id": file_id,
    }


def _generate_ltx_inference_api_video(payload: dict[str, Any], *, provider: str = "ltx2.3") -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required for LTX API video generation")
    normalized_provider = str(provider or "").strip().lower()
    is_ltx23 = normalized_provider == "ltx2.3"
    is_joy_echo = normalized_provider in _JOY_ECHO_PROVIDERS
    is_text_only = is_ltx23 or is_joy_echo
    use_ltx_api_defaults = is_ltx23 or is_joy_echo
    min_duration = JOY_ECHO_MIN_DURATION_SECONDS if is_joy_echo else LTX_MIN_DURATION_SECONDS
    max_duration = JOY_ECHO_REMOTE_MAX_DURATION_SECONDS if is_joy_echo else LTX_REMOTE_MAX_DURATION_SECONDS
    env_duration = _env_float("LTX_CUSTOM_VIDEO_DURATION") if use_ltx_api_defaults else None
    env_width = _env_int("LTX_CUSTOM_VIDEO_WIDTH") if use_ltx_api_defaults else None
    env_height = _env_int("LTX_CUSTOM_VIDEO_HEIGHT") if use_ltx_api_defaults else None
    duration_raw = payload.get("duration")
    duration = float(duration_raw if duration_raw is not None else env_duration if env_duration is not None else min_duration)
    if is_joy_echo or (duration_raw is None and env_duration is None):
        duration = max(min_duration, duration)
    if use_ltx_api_defaults and duration > max_duration:
        return _generate_ltx_segmented_video(payload, provider=provider, duration=duration)
    timeout = int(payload.get("timeout_seconds") or payload.get("timeout") or 1400)
    width_raw = payload.get("width") if payload.get("width") is not None else env_width
    height_raw = payload.get("height") if payload.get("height") is not None else env_height
    width = _ceil_to_multiple(int(width_raw if width_raw is not None else LTX_MIN_WIDTH), 32)
    height = _ceil_to_multiple(int(height_raw if height_raw is not None else LTX_MIN_HEIGHT), 32)
    if env_width is None and payload.get("width") is None:
        width = max(LTX_MIN_WIDTH, width)
    if env_height is None and payload.get("height") is None:
        height = max(LTX_MIN_HEIGHT, height)
    request_payload: dict[str, Any] = {
        "prompt": prompt,
        "duration": duration,
        "width": width,
        "height": height,
        "steps": int(payload.get("steps") or (_env_int("LTX_CUSTOM_VIDEO_STEPS") if use_ltx_api_defaults else None) or 20),
    }
    if not is_text_only:
        request_payload["image"] = _inference_image_ref(str(payload.get("image_url") or ""))
    for source, target, caster in (
        ("LTX_CUSTOM_VIDEO_MODE", "mode", str),
        ("LTX_CUSTOM_VIDEO_PROFILE", "profile", str),
        ("LTX_CUSTOM_VIDEO_CFG_SCALE", "cfg_scale", float),
        ("LTX_CUSTOM_VIDEO_STG_SCALE", "stg_scale", float),
    ):
        value = payload.get(target)
        if value is None and use_ltx_api_defaults:
            value = os.getenv(source)
        if value is not None and value != "":
            request_payload[target] = caster(value)
    if payload.get("model") is not None:
        request_payload["model"] = payload.get("model")
    if payload.get("seed") is not None:
        request_payload["seed"] = payload.get("seed")
    if _use_joy_echo_api_config(normalized_provider):
        job_id = _submit_inference_job(request_payload, provider=normalized_provider)
    else:
        job_id = _submit_inference_job(request_payload)
    return _complete_ltx_inference_result(job_id, request_payload, timeout=timeout, provider=provider)


def _generate_ltx_segmented_video(payload: dict[str, Any], *, provider: str, duration: float) -> dict[str, Any]:
    remaining = float(duration)
    clips: list[dict[str, Any]] = []
    normalized_provider = str(provider or "").strip().lower()
    image_ref = "" if normalized_provider == "ltx2.3" or normalized_provider in _JOY_ECHO_PROVIDERS else _inference_image_ref(str(payload.get("image_url") or ""))
    while remaining > 0:
        clip_duration = min(LTX_REMOTE_MAX_DURATION_SECONDS, remaining)
        clip_payload = {**payload, "duration": clip_duration}
        if image_ref:
            clip_payload["image_url"] = image_ref
        clips.append(_generate_ltx_inference_api_video(clip_payload, provider=provider))
        remaining -= clip_duration

    sources = [str(clip.get("url") or "").strip() for clip in clips if str(clip.get("url") or "").strip()]
    if not sources:
        raise RuntimeError("LTX segmented generation did not produce any clips")

    from app.services.video_edit import export_final_video

    LTX_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid4())
    target = (LTX_DOWNLOAD_DIR / f"{file_id}.mp4").resolve()
    temp_target = target.with_name(f"{file_id}.joining.mp4")
    export_info = export_final_video(sources, str(temp_target), preview=False)
    temp_target.replace(target)

    return {
        "url": _local_ltx_file_url(target.name),
        "width": int(clips[0].get("width") or payload.get("width") or LTX_MIN_WIDTH),
        "height": int(clips[0].get("height") or payload.get("height") or LTX_MIN_HEIGHT),
        "duration": float(export_info.get("duration_sec") or duration),
        "provider": _ltx_result_provider_label(provider),
        "prompt_id": ",".join(str(clip.get("prompt_id") or "") for clip in clips if clip.get("prompt_id")),
        "ltx_file_id": file_id,
        "segments": clips,
    }


def _submit_workflow(workflow: dict[str, Any]) -> str:
    body = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        _comfyui_api_url("/prompt"),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI submit failed (HTTP {e.code}): {detail}") from e
    except Exception as e:
        raise RuntimeError(f"ComfyUI submit error: {e}") from e

    prompt_id = data.get("prompt_id", "")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {data}")
    return prompt_id


def _prepare_image_for_comfyui(image_ref: str) -> str:
    image_ref = str(image_ref or "").strip()
    if not image_ref:
        raise ValueError("image_url is required for Wan ComfyUI video generation")
    if image_ref.startswith(("http://", "https://")):
        return _download_and_upload_image(image_ref)
    local_path = _resolve_local_image_path(image_ref)
    if local_path:
        return _upload_image_to_comfyui(local_path)
    return image_ref


def _resolve_local_image_path(image_ref: str) -> Path | None:
    candidates: list[Path] = []
    raw = Path(image_ref)
    if raw.exists():
        candidates.append(raw)
    if image_ref.startswith("/storage/"):
        candidates.append(Path.cwd() / "storage" / image_ref.removeprefix("/storage/"))
    elif image_ref.startswith("storage/"):
        candidates.append(Path.cwd() / image_ref)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    if image_ref.startswith(("/storage/", "storage/")):
        raise FileNotFoundError(f"selected_image file not found for ComfyUI upload: {image_ref}")
    return None


def _download_and_upload_image(url: str) -> str:
    suffix = Path(url.split("?", 1)[0]).suffix or ".png"
    temp_path = Path(os.getenv("TMPDIR") or os.getenv("TEMP") or ".") / f"comfyui_input_{uuid4().hex}{suffix}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shortdrama-ai-comfyui/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            temp_path.write_bytes(resp.read())
        return _upload_image_to_comfyui(temp_path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _upload_image_to_comfyui(path: str | Path) -> str:
    path = Path(path)
    filename = path.name
    boundary = f"----shortdrama-comfyui-{uuid4().hex}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_bytes = path.read_bytes()
    body = b"".join(
        [
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + file_bytes
            + b"\r\n",
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="type"\r\n\r\n'
                "input\r\n"
            ).encode("utf-8"),
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
                "true\r\n"
            ).encode("utf-8"),
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    req = urllib.request.Request(
        _comfyui_api_url("/upload/image"),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    name = str(data.get("name") or filename).strip()
    subfolder = str(data.get("subfolder") or "").strip().strip("/")
    return f"{subfolder}/{name}" if subfolder else name


def _poll_result(prompt_id: str, timeout: int = 300, interval: int = 5) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        time.sleep(interval)
        try:
            req = urllib.request.Request(_comfyui_api_url(f"/history/{prompt_id}"))
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue

        history = data.get(prompt_id, {})
        status = history.get("status", {})
        status_str = status.get("status_str", "")

        if status_str and status_str != last_status:
            last_status = status_str

        if status.get("completed"):
            outputs = history.get("outputs", {})
            videos = _extract_video_urls(outputs)
            if videos:
                return {
                    "url": videos[0],
                    "all_videos": videos,
                    "prompt_id": prompt_id,
                    "provider": "comfyui",
                    "width": _extract_meta(outputs, "width", 832),
                    "height": _extract_meta(outputs, "height", 480),
                }
            raise RuntimeError(
                f"ComfyUI task completed but no video found in outputs. "
                f"Check ComfyUI queue for prompt_id={prompt_id}"
            )

        if status.get("failed"):
            error_msg = _extract_error(history)
            raise RuntimeError(f"ComfyUI task failed: {error_msg}")

    raise TimeoutError(f"ComfyUI task timeout after {timeout}s (prompt_id={prompt_id})")


def _extract_video_urls(outputs: dict[str, Any]) -> list[str]:
    videos = []
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key in ("video", "videos", "gifs"):
            items = node_output.get(key, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        url = item.get("filename") or item.get("url") or ""
                        if url:
                            videos.append(_comfyui_file_url(url))
                    elif isinstance(item, str) and item.strip():
                        videos.append(_comfyui_file_url(item))
            elif isinstance(items, str) and items.strip():
                videos.append(_comfyui_file_url(items))
    return videos


def _extract_meta(outputs: dict[str, Any], key: str, default: Any = None) -> Any:
    for node_output in outputs.values():
        if isinstance(node_output, dict):
            meta = node_output.get("meta", {}) if isinstance(node_output.get("meta"), dict) else {}
            value = meta.get(key)
            if value is not None:
                return value
    return default


def _extract_error(history: dict[str, Any]) -> str:
    outputs = history.get("outputs", {})
    for node_output in outputs.values():
        if isinstance(node_output, dict):
            messages = node_output.get("messages", [])
            for msg in messages:
                if isinstance(msg, list) and len(msg) > 1:
                    return str(msg[1])
    return str(history)


def _comfyui_file_url(filename: str) -> str:
    return f"{_comfyui_url()}/view?filename={urllib.request.quote(filename)}"


def generate_comfy_video(payload: dict[str, Any], api_key: str | None = None, **kwargs: Any) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required for ComfyUI video generation")

    duration = int(payload.get("duration", 5))
    image_url = str(payload.get("image_url") or "").strip()
    provider = str(kwargs.get("provider") or payload.get("provider") or "ltx").lower()

    # Route to local LTX Desktop if configured and available
    if provider in _LTX_API_PROVIDERS:
        if provider not in _JOY_ECHO_PROVIDERS and _should_use_local_ltx():
            from app.services.ltx_desktop import LtxDesktopService, LtxDesktopUnavailableError
            service = LtxDesktopService()
            if service.health().get("status") == "ok":
                try:
                    return service.generate_video(payload)
                except LtxDesktopUnavailableError:
                    LOGGER.warning("Local LTX Desktop unavailable, falling back to remote API")
            # Fall through to remote API if desktop is not running
        return _generate_ltx_inference_api_video(payload, provider=provider)

    builder = _WORKFLOW_BUILDERS.get(provider)
    if not builder:
        raise ValueError(f"Unknown ComfyUI video provider: {provider}. Supported: {list(_WORKFLOW_BUILDERS)}")

    is_wan_workflow = builder is _wan_workflow
    if is_wan_workflow:
        image_url = _prepare_image_for_comfyui(image_url)
        workflow = _wan_workflow(prompt, image_url, duration, str(payload.get("negative_prompt") or ""))
    else:
        workflow = builder(prompt, image_url, duration)

    prompt_id = _submit_workflow(workflow)
    timeout = int(payload.get("timeout") or (1400 if is_wan_workflow else 300))
    result = _poll_result(prompt_id, timeout=timeout)

    return {
        "url": result["url"],
        "width": result.get("width", 832 if is_wan_workflow else 720),
        "height": result.get("height", 480 if is_wan_workflow else 1280),
        "duration": duration,
        "provider": f"comfyui_{provider}",
        "prompt_id": result.get("prompt_id", prompt_id),
    }
