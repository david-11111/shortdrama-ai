from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


app = FastAPI(title="Joy-Echo API")
TASKS: dict[str, dict[str, Any]] = {}
REQUESTS: dict[str, "GenerateRequest"] = {}
FILES: dict[str, Path] = {}


class GenerateRequest(BaseModel):
    prompt: str = ""
    prompts: list[str] = Field(default_factory=list)
    duration: float = 30.0
    width: int = 1280
    height: int = 736
    fps: int = 25
    seed: int = 20260625

    def clean_prompts(self) -> list[str]:
        prompts = [str(item).strip() for item in self.prompts if str(item).strip()]
        if prompts:
            return prompts
        prompt = self.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=422, detail="prompt is required")
        return [prompt]


def _api_key() -> str:
    return os.getenv("JOY_ECHO_API_KEY", "").strip()


def _storage_dir() -> Path:
    path = Path(os.getenv("JOY_ECHO_API_STORAGE_DIR", "storage/joy_echo_api")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_bearer(authorization: str = Header(default="")) -> None:
    key = _api_key()
    if not key or authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="Invalid bearer token")


def _task_payload(task_id: str, status: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "id": task_id,
        "status": status,
        "progress": {"percentage": 0, "message": "Pending"},
        "output": None,
        "outputs": [],
        "error_message": None,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/video/generate", dependencies=[Depends(_require_bearer)])
def generate_video(req: GenerateRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    req.clean_prompts()
    task_id = uuid4().hex
    REQUESTS[task_id] = req
    TASKS[task_id] = _task_payload(task_id, "pending")
    background_tasks.add_task(_run_task, task_id)
    return {"task_id": task_id, "id": task_id, "status": "pending"}


@app.get("/v1/tasks/{task_id}", dependencies=[Depends(_require_bearer)])
def get_task(task_id: str) -> dict[str, Any]:
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@app.get("/v1/files/{file_id}", dependencies=[Depends(_require_bearer)])
def get_file(file_id: str) -> FileResponse:
    path = FILES.get(file_id) or (_storage_dir() / f"{file_id}.mp4")
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


def _run_task(task_id: str) -> None:
    req = REQUESTS[task_id]
    TASKS[task_id]["status"] = "running"
    TASKS[task_id]["progress"] = {"percentage": 10, "message": "Running Joy-Echo"}
    try:
        source_video = _run_joy_echo(req, task_id)
        file_id = uuid4().hex
        target = _storage_dir() / f"{file_id}.mp4"
        shutil.copyfile(source_video, target)
        FILES[file_id] = target
        TASKS[task_id].update(
            {
                "status": "completed",
                "progress": {"percentage": 100, "message": "Completed"},
                "output": {"file_id": file_id, "url": f"/v1/files/{file_id}", "duration": req.duration},
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
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        TASKS[task_id].update(
            {
                "status": "failed",
                "progress": {"percentage": 100, "message": "Failed"},
                "error_message": str(exc)[-2000:],
            }
        )


def _run_joy_echo(req: GenerateRequest, task_id: str) -> Path:
    repo_path = Path(os.getenv("JOY_ECHO_REPO_PATH", "/root/autodl-tmp/joyai/JoyAI-Echo/JoyAI-Echo-code"))
    python_path = os.getenv("JOY_ECHO_PYTHON_PATH", "/root/autodl-tmp/joyai/envs/echo-long/bin/python")
    output_root = os.getenv("JOY_ECHO_OUTPUT_ROOT", "inference_result/outputs")
    timeout = int(os.getenv("JOY_ECHO_TIMEOUT_SECONDS", "7200"))
    prompt_stem = f"saas_joy_echo_{task_id}"
    prompt_dir = repo_path / "prompts" / "saas_runtime"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{prompt_stem}.json"
    prompt_path.write_text(json.dumps({"prompts": req.clean_prompts()}, ensure_ascii=False, indent=2), encoding="utf-8")

    num_frames = max(1, int(round(max(30.0, req.duration) * max(1, req.fps) / max(1, len(req.clean_prompts())))))
    command = [
        python_path,
        "inference.py",
        "--config",
        "configs/inference.yaml",
        "--prompts-dir",
        str(prompt_dir),
        "--prompts-glob",
        prompt_path.name,
        "--output-root",
        output_root,
        "--num-frames",
        str(num_frames),
        "--video-height",
        str(req.height),
        "--video-width",
        str(req.width),
        "--seed",
        str(req.seed),
        "--v2a-grad-scale",
        "0",
    ]
    result = subprocess.run(command, cwd=repo_path, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0:
        tail = (result.stdout + "\n" + result.stderr)[-2000:]
        raise RuntimeError(f"Joy-Echo exited with code {result.returncode}: {tail}")
    return _find_output_video(repo_path, output_root, prompt_stem)


def _find_output_video(repo_path: Path, output_root: str, prompt_stem: str) -> Path:
    root = Path(output_root)
    if not root.is_absolute():
        root = repo_path / root
    matches = [path for path in root.rglob("combined_shots.mp4") if prompt_stem in str(path)]
    if not matches:
        raise RuntimeError(f"combined_shots.mp4 not found for {prompt_stem}")
    return max(matches, key=lambda path: path.stat().st_mtime)
