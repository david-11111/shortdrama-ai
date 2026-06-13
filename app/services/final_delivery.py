from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from app.config import FFPROBE


def probe_final_video(path: str) -> dict[str, Any]:
    result = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", path],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    duration = 0.0
    if isinstance(payload.get("format"), dict):
        try:
            duration = float(payload["format"].get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
    return {
        "exists": os.path.exists(path),
        "file_size": os.path.getsize(path) if os.path.exists(path) else 0,
        "duration_sec": round(duration, 3),
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "width": int(video_stream.get("width") or 0) if video_stream else 0,
        "height": int(video_stream.get("height") or 0) if video_stream else 0,
    }


def build_final_delivery_report(
    *,
    path: str,
    final_video_url: str,
    target_duration_sec: int,
    clip_count: int,
    planned_clip_count: int,
    subtitles: list[dict[str, Any]] | None,
    audio_required: bool = True,
) -> dict[str, Any]:
    issues = []
    probe = probe_final_video(path)
    if not probe["exists"] or probe["file_size"] <= 0:
        issues.append({"code": "missing_file", "message": "Final video file is missing or empty."})
    if not probe["has_video"]:
        issues.append({"code": "missing_video_track", "message": "Final video has no video track."})
    if audio_required and not probe["has_audio"]:
        issues.append({"code": "missing_audio_track", "message": "Final video has no audio track."})
    if target_duration_sec and probe["duration_sec"] < max(1, target_duration_sec * 0.6):
        issues.append({
            "code": "duration_short",
            "message": "Final video is much shorter than target duration.",
            "target_duration_sec": target_duration_sec,
            "actual_duration_sec": probe["duration_sec"],
        })
    if clip_count < planned_clip_count:
        issues.append({
            "code": "clip_count_mismatch",
            "message": "Exported clip count is lower than planned clip count.",
            "clip_count": clip_count,
            "planned_clip_count": planned_clip_count,
        })
    if subtitles is not None and not subtitles:
        issues.append({"code": "missing_subtitles", "message": "Subtitle plan is empty."})
    if not final_video_url:
        issues.append({"code": "missing_final_url", "message": "Final video URL was not written back."})
    return {
        "passed": not issues,
        "score": max(0, 100 - len(issues) * 18),
        "issues": issues,
        "retryable": bool(issues),
        "recommended_action": "fix_delivery_inputs" if issues else "completed",
        "probe": probe,
        "final_video_url": final_video_url,
        "clip_count": clip_count,
        "planned_clip_count": planned_clip_count,
    }
