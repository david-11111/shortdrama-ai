"""Service for interacting with locally-installed LTX Desktop backend.

LTX Desktop is an Electron app by Lightricks with a Python FastAPI backend
running on http://127.0.0.1:41954.  This service manages the backend subprocess
and provides video/image generation capabilities via the local GPU.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.config import get_settings

LOGGER = logging.getLogger(__name__)

LTX_DOWNLOAD_DIR = Path("storage") / "ltx_downloads"
_LAUNCH_LOCK = Lock()
_DEFAULT_PORT = 41954
_LTX_DESKTOP_PYTHON = Path(r"C:\Users\福星1号\AppData\Local\LTXDesktop\python\python.exe")
_STARTUP_TIMEOUT_SEC = 90
_POLL_INTERVAL_SEC = 3.0
_GENERATION_POLL_SEC = 3.0


class LtxDesktopUnavailableError(RuntimeError):
    """Raised when LTX Desktop backend is not running and cannot be started."""
    pass


class LtxDesktopService:
    """Manages the LTX Desktop backend lifecycle and proxies generation requests."""

    _process: subprocess.Popen | None = None

    # ── properties ──────────────────────────────────────────────

    @property
    def _install_path(self) -> Path:
        s = get_settings()
        raw = s.ltx_desktop_install_path or ""
        return Path(raw) if raw else Path(r"D:\Users\福星1号\AppData\Local\Programs\LTX Desktop")

    @property
    def _api_base(self) -> str:
        s = get_settings()
        return (s.ltx_desktop_api_base_url or f"http://127.0.0.1:{_DEFAULT_PORT}").rstrip("/")

    @property
    def _data_dir(self) -> Path:
        s = get_settings()
        if s.ltx_desktop_data_dir:
            return Path(s.ltx_desktop_data_dir)
        return Path("storage") / "ltx_desktop_data"

    @property
    def _launcher(self) -> Path:
        return self._install_path / "api_login_launcher.py"

    # ── public API ──────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Check if LTX Desktop backend is healthy.

        Returns a dict with at least ``status`` (``"ok"`` or ``"error"``).
        """
        try:
            req = urllib.request.Request(self._url("/health"), method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    def ensure_running(self) -> bool:
        """Make sure LTX Desktop backend is running (launch if needed).

        Returns ``True`` if the backend is reachable, ``False`` otherwise.
        Repeated calls are safe – the health check runs first.
        """
        h = self.health()
        if h.get("status") == "ok":
            return True

        if not self._launcher.exists():
            LOGGER.warning("LTX Desktop launcher not found at %s", self._launcher)
            return False

        with _LAUNCH_LOCK:
            # Double-check after acquiring lock
            h = self.health()
            if h.get("status") == "ok":
                return True

            self._data_dir.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "LTX_APP_DATA_DIR": str(self._data_dir)}
            LOGGER.info("Launching LTX Desktop backend from %s", self._launcher)

            python_exe = str(_LTX_DESKTOP_PYTHON) if _LTX_DESKTOP_PYTHON.exists() else sys.executable
            try:
                self._process = subprocess.Popen(
                    [python_exe, str(self._launcher)],
                    env=env,
                    cwd=str(self._install_path),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                LOGGER.error("Failed to launch LTX Desktop: %s", exc)
                return False

            deadline = time.time() + _STARTUP_TIMEOUT_SEC
            while time.time() < deadline:
                time.sleep(_POLL_INTERVAL_SEC)
                h = self.health()
                if h.get("status") == "ok":
                    LOGGER.info("LTX Desktop backend started (pid=%s)", self._process.pid)
                    return True

            LOGGER.error("LTX Desktop backend did not start within %ss", _STARTUP_TIMEOUT_SEC)
            return False

    def generate_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate a video via the local LTX Desktop backend.

        Accepts a payload dict with at least ``prompt``, and optionally
        ``image_url`` (for image-to-video), ``duration``, ``width``, ``height``.

        Returns a result dict shaped like ``generate_comfy_video()``:
        ``{"url": …, "width": …, "height": …, "duration": …, "provider": "ltx_desktop", "prompt_id": …}``.

        If the local backend is not available, falls back to raising
        ``LtxDesktopUnavailableError`` so the caller can fall back to the remote API.
        """
        if not self.ensure_running():
            raise LtxDesktopUnavailableError("LTX Desktop backend is not available")

        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("payload must contain a non-empty 'prompt'")

        duration = int(payload.get("duration") or 5)
        width = int(payload.get("width") or 1080)
        height = int(payload.get("height") or 1920)
        image_url = str(payload.get("image_url") or "").strip()

        # Download image if image-to-video
        image_path: str | None = None
        if image_url:
            local_img = self._download_file(image_url)
            if local_img:
                image_path = str(local_img)

        # Build request body for LTX Desktop API
        body = {
            "prompt": prompt,
            "duration": min(max(duration, 1), 10),
            "resolution": "1080p",
            "model": "fast",
            "fps": 24,
            "audio": False,
            "aspectRatio": "9:16",
            "numSteps": 25,
        }
        if image_path:
            body["imagePath"] = image_path

        LOGGER.info("LTX Desktop generate_video: prompt=%s duration=%s", prompt[:60], duration)

        resp = self._api_post("/api/generate", body)
        # The /api/generate endpoint returns immediately with generation info

        # Poll for completion
        prompt_id = self._extract_prompt_id(resp)
        output_path = self._poll_generation(prompt_id)

        # Copy output to standard location
        dest = LTX_DOWNLOAD_DIR / f"{uuid4().hex}{output_path.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(output_path), str(dest))

        local_url = f"/api/media/local/ltx/{dest.name}"

        return {
            "url": local_url,
            "width": width,
            "height": height,
            "duration": duration,
            "provider": "ltx_desktop",
            "prompt_id": prompt_id,
        }

    def generate_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate an image via the local LTX Desktop backend."""
        if not self.ensure_running():
            raise LtxDesktopUnavailableError("LTX Desktop backend is not available")

        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("payload must contain a non-empty 'prompt'")

        width = int(payload.get("width") or 1080)
        height = int(payload.get("height") or 1920)

        body = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "numSteps": 25,
            "numImages": 1,
        }

        LOGGER.info("LTX Desktop generate_image: prompt=%s", prompt[:60])
        resp = self._api_post("/api/generate-image", body)

        # The response should contain the output image path(s)
        output_path = self._extract_output_path(resp)
        if not output_path:
            raise RuntimeError(f"LTX Desktop image generation returned no output path: {resp}")

        dest = LTX_DOWNLOAD_DIR / f"{uuid4().hex}{Path(str(output_path)).suffix or '.png'}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(output_path), str(dest))

        return {
            "url": f"/api/media/local/ltx/{dest.name}",
            "width": width,
            "height": height,
            "provider": "ltx_desktop",
        }

    def send_media(self, media_url: str, action: str = "preview", prompt: str = "") -> dict[str, Any]:
        """Send a media file to LTX Desktop for preview or further processing.

        * ``action="preview"`` – Open the file in LTX Desktop Electron app.
        * ``action="image-to-video"`` – Submit the image to ``/api/generate`` (requires backend).
        * ``action="extract-conditioning"`` – Extract IC-LoRA conditioning (requires backend).
        """
        local_path = self._resolve_local_path(media_url)
        if not local_path or not local_path.exists():
            raise FileNotFoundError(f"Media file not found: {media_url} -> {local_path}")

        action = action or "preview"

        # Actions that need the API backend
        if action in ("image-to-video", "extract-conditioning"):
            if not self.ensure_running():
                raise LtxDesktopUnavailableError(
                    "LTX Desktop 后端未运行，无法进行此操作。请先打开 LTX Desktop 应用完成登录。"
                )

            if action == "image-to-video" and local_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                body = {
                    "prompt": prompt or "Continue this scene",
                    "duration": 5,
                    "model": "fast",
                    "resolution": "1080p",
                    "imagePath": str(local_path),
                }
                resp = self._api_post("/api/generate", body)
                prompt_id = self._extract_prompt_id(resp)
                return {
                    "success": True,
                    "ltx_url": f"{self._api_base}/api/generation/progress",
                    "message": f"已发送到 LTX Desktop 处理，任务 {prompt_id}",
                    "task_id": prompt_id,
                }

            if action == "extract-conditioning":
                body = {"imagePath": str(local_path)}
                resp = self._api_post("/api/ic-lora/extract-conditioning", body)
                return {
                    "success": True,
                    "ltx_url": f"{self._api_base}/api/ic-lora/extract-conditioning",
                    "message": "已提取 IC-LoRA conditioning",
                    "data": resp,
                }

        # Default: preview – open LTX Desktop Electron app to view the file
        try:
            exe_path = self._install_path / "LTX Desktop.exe"
            if exe_path.exists():
                import subprocess
                subprocess.Popen(
                    [str(exe_path)],
                    cwd=str(self._install_path),
                    shell=True,
                )
                LOGGER.info("Opened LTX Desktop for preview of %s", local_path.name)
        except Exception as exc:
            LOGGER.warning("Failed to open LTX Desktop app: %s", exc)

        return {
            "success": True,
            "message": f"已打开 LTX Desktop，请查看文件: {local_path.name}",
            "file_path": str(local_path),
        }

    def shutdown(self) -> None:
        """Gracefully shut down the LTX Desktop backend."""
        if self._process is None or self._process.poll() is not None:
            return

        try:
            req = urllib.request.Request(
                self._url("/api/system/shutdown"),
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            LOGGER.info("LTX Desktop backend shutdown requested")
        except Exception as exc:
            LOGGER.warning("LTX Desktop shutdown API call failed: %s", exc)
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                LOGGER.warning("LTX Desktop backend did not terminate; killing")
                self._process.kill()

    # ── internal helpers ────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self._api_base}{path}"

    def _api_post(self, path: str, body: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
        req = urllib.request.Request(
            self._url(path),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LTX Desktop API error (HTTP {e.code}): {detail}") from e

    def _api_get(self, path: str, timeout: int = 30) -> dict[str, Any]:
        req = urllib.request.Request(self._url(path), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LTX Desktop API error (HTTP {e.code}): {detail}") from e

    def _download_file(self, url: str) -> Path | None:
        """Download a file from a URL (SaaS media URL) to a local temp file."""
        temp_dir = Path("storage") / "ltx_desktop_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Resolve relative URLs
        if url.startswith("/"):
            settings = get_settings()
            base = f"http://127.0.0.1:{settings.app_port}"
            url = f"{base}{url}"

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=60) as resp:
                suffix = Path(url).suffix or ".png"
                dest = temp_dir / f"input_{uuid4().hex}{suffix}"
                with open(dest, "wb") as f:
                    f.write(resp.read())
                return dest
        except Exception as exc:
            LOGGER.warning("Failed to download file for LTX Desktop: %s", exc)
            return None

    def _resolve_local_path(self, media_url: str) -> Path | None:
        """Resolve a SaaS media URL to a local file path."""
        # Handle /api/media/local/ltx/xxx.mp4
        clean = media_url.lstrip("/")
        # Try storage/ltx_downloads/ path
        candidates = [
            Path("storage") / "ltx_downloads" / Path(media_url).name,
            LTX_DOWNLOAD_DIR / Path(media_url).name,
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _extract_prompt_id(self, resp: dict[str, Any]) -> str:
        """Extract a generation task/prompt ID from the API response."""
        # LTX Desktop may return id/prompt_id/generation_id at various keys
        for key in ("prompt_id", "id", "generation_id", "task_id"):
            val = resp.get(key)
            if val:
                return str(val)
        return str(uuid4().hex)

    def _extract_output_path(self, resp: dict[str, Any]) -> Path | None:
        """Extract the output file path from the API response."""
        # The response may contain output_path, file_path, or be nested
        for key in ("output_path", "file_path", "path", "videoPath", "imagePath"):
            val = resp.get(key)
            if val:
                p = Path(str(val))
                if p.exists():
                    return p
        # Check data sub-dict
        data = resp.get("data") or {}
        if isinstance(data, dict):
            for key in ("output_path", "file_path", "path", "videoPath", "imagePath"):
                val = data.get(key)
                if val:
                    p = Path(str(val))
                    if p.exists():
                        return p
        # Look in LTX_APP_DATA_DIR/outputs for recent files
        outputs_dir = self._data_dir / "outputs"
        if outputs_dir.exists():
            files = sorted(outputs_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
            if files:
                return files[0]
        return None

    def _poll_generation(self, prompt_id: str) -> Path:
        """Poll ``/api/generation/progress`` until the generation is complete."""
        deadline = time.time() + 360  # 6 min timeout
        while time.time() < deadline:
            time.sleep(_GENERATION_POLL_SEC)
            try:
                status = self._api_get(f"/api/generation/progress?prompt_id={prompt_id}", timeout=10)
            except Exception as exc:
                LOGGER.warning("LTX Desktop progress poll failed: %s", exc)
                continue

            state = str(status.get("status") or status.get("state") or "").lower()
            LOGGER.debug("LTX Desktop generation progress: %s", state)

            if state in ("completed", "done", "finished"):
                out = self._extract_output_path(status)
                if out:
                    return out
                # Fall through – keep waiting if path not yet written
            elif state in ("failed", "error"):
                err = status.get("error") or status.get("detail") or "unknown error"
                raise RuntimeError(f"LTX Desktop generation failed: {err}")
            elif state in ("cancelled", "canceled"):
                raise RuntimeError("LTX Desktop generation was cancelled")

        raise TimeoutError("LTX Desktop generation timed out after 360s")
