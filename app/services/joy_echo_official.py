"""Official JoyAI-Echo runner over SSH.

JoyAI-Echo has no official HTTP API in the current release. This adapter is the
SaaS bridge to the official repository entrypoint on the GPU host.
"""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import time
from typing import Any
from uuid import uuid4

from app.config import get_settings

JOY_DOWNLOAD_DIR = Path("storage") / "ltx_downloads"
JOY_MIN_DURATION_SECONDS = 30.0
JOY_MAX_DURATION_SECONDS = 300.0


def _local_joy_file_url(filename: str) -> str:
    from urllib.parse import quote

    return f"/api/media/local/ltx/{quote(filename, safe='')}"


def _payload_prompts(payload: dict[str, Any]) -> list[str]:
    raw_prompts = payload.get("prompts")
    if isinstance(raw_prompts, list):
        prompts = [str(item).strip() for item in raw_prompts if str(item).strip()]
        if prompts:
            return prompts

    shots = payload.get("shots")
    if isinstance(shots, list):
        prompts = []
        for shot in shots:
            if isinstance(shot, dict):
                prompt = str(shot.get("prompt") or shot.get("video_prompt") or "").strip()
            else:
                prompt = str(shot).strip()
            if prompt:
                prompts.append(prompt)
        if prompts:
            return prompts

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required for JoyAI-Echo official generation")
    return [prompt]


def _duration_seconds(payload: dict[str, Any]) -> float:
    raw_duration = payload.get("duration")
    duration = float(raw_duration if raw_duration is not None else JOY_MIN_DURATION_SECONDS)
    return min(JOY_MAX_DURATION_SECONDS, max(JOY_MIN_DURATION_SECONDS, duration))


def _frames_per_shot(payload: dict[str, Any], prompt_count: int) -> int:
    settings = get_settings()
    fps = max(1, int(getattr(settings, "joy_echo_fps", 25) or 25))
    duration_per_shot = _duration_seconds(payload) / max(1, prompt_count)
    return max(1, int(round(duration_per_shot * fps)))


def _remote_join(*parts: str) -> str:
    clean = [str(part).strip("/") for part in parts if str(part).strip("/")]
    if not clean:
        return "/"
    prefix = "/" if str(parts[0]).startswith("/") else ""
    return prefix + "/".join(clean)


def _mkdir_p_sftp(sftp: Any, remote_dir: str) -> None:
    current = "/" if remote_dir.startswith("/") else ""
    for part in [item for item in remote_dir.split("/") if item]:
        current = _remote_join(current, part)
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def _read_channel(channel: Any, timeout: int) -> tuple[int, str]:
    deadline = time.time() + timeout
    chunks: list[bytes] = []
    while True:
        while channel.recv_ready():
            chunks.append(channel.recv(65536))
        if channel.exit_status_ready():
            while channel.recv_ready():
                chunks.append(channel.recv(65536))
            return channel.recv_exit_status(), b"".join(chunks).decode("utf-8", errors="replace")
        if time.time() > deadline:
            channel.close()
            raise TimeoutError(f"JoyAI-Echo SSH command timeout after {timeout}s")
        time.sleep(1)


def _run_remote_command(client: Any, command: str, *, timeout: int) -> str:
    channel = client.get_transport().open_session()
    channel.set_combine_stderr(True)
    channel.exec_command(command)
    exit_code, output = _read_channel(channel, timeout)
    if exit_code != 0:
        tail = output[-4000:] if output else ""
        raise RuntimeError(f"JoyAI-Echo command failed with exit code {exit_code}: {tail}")
    return output


def _connect_ssh() -> Any:
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is required for JoyAI-Echo official SSH generation") from exc

    settings = get_settings()
    host = str(getattr(settings, "joy_echo_ssh_host", "") or "").strip()
    if not host:
        raise RuntimeError("JOY_ECHO_SSH_HOST is required for JoyAI-Echo official generation")
    password = str(getattr(settings, "joy_echo_ssh_password", "") or "").strip() or None

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=int(getattr(settings, "joy_echo_ssh_port", 22) or 22),
        username=str(getattr(settings, "joy_echo_ssh_user", "root") or "root"),
        password=password,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    return client


def generate_joy_echo_official_video(
    payload: dict[str, Any],
    api_key: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    prompts = _payload_prompts(payload)
    settings = get_settings()
    if str(getattr(settings, "joy_echo_api_base_url", "") or "").strip():
        from app.services.comfy_video import generate_comfy_video

        provider = str(kwargs.get("provider") or payload.get("provider") or "joy-echo")
        api_payload = dict(payload)
        api_payload.setdefault("prompt", "\n".join(prompts))
        return generate_comfy_video(api_payload, provider=provider)

    repo_path = str(getattr(settings, "joy_echo_repo_path", "") or "").rstrip("/")
    python_path = str(getattr(settings, "joy_echo_python_path", "") or "python").strip()
    output_root = str(getattr(settings, "joy_echo_output_root", "") or "inference_result/outputs").strip()
    timeout = int(payload.get("timeout_seconds") or getattr(settings, "joy_echo_timeout_seconds", 7200) or 7200)
    width = int(payload.get("width") or getattr(settings, "joy_echo_video_width", 1280) or 1280)
    height = int(payload.get("height") or getattr(settings, "joy_echo_video_height", 736) or 736)
    seed = int(payload.get("seed") or getattr(settings, "joy_echo_default_seed", 20260625) or 20260625)
    num_frames = int(payload.get("num_frames") or _frames_per_shot(payload, len(prompts)))

    if not repo_path:
        raise RuntimeError("JOY_ECHO_REPO_PATH is required for JoyAI-Echo official generation")

    prompt_stem = f"saas_joy_echo_{uuid4().hex}"
    prompt_filename = f"{prompt_stem}.json"
    remote_prompt_dir = _remote_join(repo_path, "prompts", "saas_runtime")
    remote_prompt_path = _remote_join(remote_prompt_dir, prompt_filename)
    remote_output_root = output_root if output_root.startswith("/") else _remote_join(repo_path, output_root)
    prompt_json = json.dumps({"prompts": prompts}, ensure_ascii=False, indent=2)

    client = _connect_ssh()
    try:
        sftp = client.open_sftp()
        try:
            _mkdir_p_sftp(sftp, remote_prompt_dir)
            with sftp.file(remote_prompt_path, "w") as remote_file:
                remote_file.write(prompt_json)
        finally:
            sftp.close()

        command = " ".join(
            [
                "cd",
                shlex.quote(repo_path),
                "&&",
                shlex.quote(python_path),
                "inference.py",
                "--config",
                "configs/inference.yaml",
                "--prompts-dir",
                shlex.quote(remote_prompt_dir),
                "--prompts-glob",
                shlex.quote(prompt_filename),
                "--output-root",
                shlex.quote(output_root),
                "--num-frames",
                str(num_frames),
                "--video-height",
                str(height),
                "--video-width",
                str(width),
                "--seed",
                str(seed),
                "--v2a-grad-scale",
                "0",
            ]
        )
        _run_remote_command(client, command, timeout=timeout)

        find_command = (
            "find "
            f"{shlex.quote(remote_output_root)} "
            f"-path {shlex.quote('*' + prompt_stem + '*')} "
            "-name combined_shots.mp4 -type f -printf '%T@ %p\\n' | "
            "sort -nr | head -1 | cut -d' ' -f2-"
        )
        remote_video = _run_remote_command(client, find_command, timeout=60).strip()
        if not remote_video:
            raise RuntimeError(f"JoyAI-Echo completed but combined_shots.mp4 was not found for {prompt_filename}")

        JOY_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_id = uuid4().hex
        local_target = JOY_DOWNLOAD_DIR / f"{file_id}.mp4"
        sftp = client.open_sftp()
        try:
            sftp.get(remote_video, str(local_target))
        finally:
            sftp.close()

        return {
            "url": _local_joy_file_url(local_target.name),
            "width": width,
            "height": height,
            "duration": _duration_seconds(payload),
            "provider": "joy_echo_official",
            "prompt_id": prompt_stem,
            "remote_output": remote_video,
            "num_frames": num_frames,
        }
    finally:
        client.close()
