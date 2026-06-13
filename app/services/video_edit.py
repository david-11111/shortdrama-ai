import os
import logging
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import FFMPEG
from app.config import FFPROBE
from app.services.media_proxy import validate_public_media_url


MAX_INPUT_VIDEO_BYTES = 1024 * 1024 * 1024
logger = logging.getLogger(__name__)


def _build_vf(enhance: dict) -> str | None:
    parts = []
    eq_parts = []
    b = enhance.get("brightness", 0.0)
    c = enhance.get("contrast", 1.0)
    g = enhance.get("gamma", 1.0)
    if b != 0.0 or c != 1.0 or g != 1.0:
        eq_parts.append(f"brightness={b}")
        eq_parts.append(f"contrast={c}")
        eq_parts.append(f"gamma={g}")
        parts.append("eq=" + ":".join(eq_parts))
    s = enhance.get("sharpness", 0.0)
    if s > 0:
        parts.append(f"unsharp=5:5:{s}:5:5:{s / 2}")
    return ",".join(parts) if parts else None


def cut_scene(input_path: str, start: float, end: float, out_path: str,
              enhance: dict | None = None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    vf = _build_vf(enhance) if enhance else None
    if vf:
        subprocess.run([
            FFMPEG, "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            "-c:a", "aac",
            out_path,
        ], capture_output=True, check=True)
    else:
        subprocess.run([
            FFMPEG, "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", input_path,
            "-c", "copy",
            out_path,
        ], capture_output=True, check=True)


def concat_scenes(scene_paths: list, out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in scene_paths:
            f.write(f"file '{p}'\n")
        list_file = f.name
    try:
        subprocess.run([
            FFMPEG, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            out_path,
        ], capture_output=True, check=True)
    finally:
        os.unlink(list_file)


def export_final_video(
    sources: list[str | dict[str, Any]],
    out_path: str,
    *,
    transitions: list[str] | None = None,
    subtitles: list[dict[str, Any]] | None = None,
    bgm_path: str | None = None,
    bgm_volume: float = 0.15,
    preview: bool = False,
) -> dict[str, Any]:
    """Download/normalize source clips and export a browser-friendly final MP4.

    Downloads and normalization run concurrently via a ThreadPoolExecutor
    for speed; the final concat/transitions/subtitles/bgm pass is sequential.
    """
    if not sources:
        raise ValueError("No source videos to export")

    import concurrent.futures

    output_dir = os.path.dirname(out_path)
    os.makedirs(output_dir, exist_ok=True)
    prefix = f".final_export_{uuid.uuid4().hex}_"
    temp_paths: list[str] = []
    downloaded: list[str] = []
    normalized: list[str] = []
    try:
        prepared_sources = [_normalize_source_spec(source) for source in sources]
        # ── 并发下载所有源视频 ──────────────────────────────────────────────
        def _do_download(idx: int, spec: dict) -> str:
            input_path = Path(output_dir) / f"{prefix}input_{idx:03d}.mp4"
            resolved = _resolve_input_video(spec["source"], input_path)
            if str(resolved) == str(input_path):
                temp_paths.append(str(input_path))
            return str(resolved)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(_do_download, i + 1, spec)
                for i, spec in enumerate(prepared_sources)
            ]
            downloaded = [f.result() for f in concurrent.futures.as_completed(futures)]
            # 保持与 prepared_sources 顺序一致
            downloaded = [
                futures[i].result() for i in range(len(prepared_sources))
            ]

        target_width, target_height = _pick_target_size(downloaded[0], preview=preview)
        encode_crf = 28 if preview else 20
        encode_preset = "veryfast" if preview else "veryfast"

        # ── 并发 normalize 所有视频 ──────────────────────────────────────────
        def _do_normalize(idx: int, input_path: str, spec: dict) -> str:
            output_path = Path(output_dir) / f"{prefix}normalized_{idx:03d}.mp4"
            _normalize_clip(
                input_path,
                str(output_path),
                target_width,
                target_height,
                trim_start=spec["trim_start"],
                trim_end=spec["trim_end"],
                crf=encode_crf,
                preset=encode_preset,
            )
            return str(output_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(_do_normalize, i + 1, inp, spec)
                for i, (inp, spec) in enumerate(zip(downloaded, prepared_sources))
            ]
            normalized = [f.result() for f in futures]
        temp_paths.extend(normalized)

        concat_scenes_with_transitions(
            normalized,
            out_path,
            transitions=transitions,
            subtitles=subtitles,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
            video_crf=28 if preview else 18,
            video_preset="veryfast" if preview else "medium",
        )
    finally:
        for temp_path in temp_paths:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass

    if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
        raise RuntimeError("FFmpeg export did not create an output file")

    return {
        "path": out_path,
        "clip_count": len(sources),
        "file_size": os.path.getsize(out_path),
        "duration_sec": _get_video_duration(out_path),
    }


def _normalize_source_spec(source: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        value = str(source.get("source") or source.get("video_url") or source.get("selected_video") or "").strip()
        return {
            "source": value,
            "trim_start": max(0.0, _float_or_zero(source.get("trim_start"))),
            "trim_end": max(0.0, _float_or_zero(source.get("trim_end"))),
        }
    return {"source": str(source or "").strip(), "trim_start": 0.0, "trim_end": 0.0}


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _resolve_input_video(source: str, out_path: Path) -> Path:
    source = str(source or "").strip()
    if not source:
        raise ValueError("Empty video source")

    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        validate_public_media_url(source)
        return _download_video(source, out_path)

    path = Path(source)
    if source.startswith("/storage/"):
        path = Path("storage") / source.removeprefix("/storage/")
    elif source.startswith("/assets/"):
        path = Path("storage") / "projects" / source.removeprefix("/assets/")
    if not path.exists():
        raise FileNotFoundError(f"Video source not found: {source}")
    return path


def _resolve_bgm_audio(source: str | None, out_path: Path) -> Path | None:
    source = str(source or "").strip()
    if not source:
        return None
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        validate_public_media_url(source)
        return _download_video(source, out_path)
    path = Path(source)
    if source.startswith("/assets/"):
        path = Path("storage") / "projects" / source.removeprefix("/assets/")
    elif source.startswith("/storage/"):
        path = Path("storage") / source.removeprefix("/storage/")
    if not path.exists():
        raise FileNotFoundError(f"BGM source not found: {source}")
    return path


def _download_video(url: str, out_path: Path) -> Path:
    validate_public_media_url(url)
    total = 0
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            validate_public_media_url(str(response.url))
            response.raise_for_status()
            with open(out_path, "wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    total += len(chunk)
                    if total > MAX_INPUT_VIDEO_BYTES:
                        raise RuntimeError("Input video is larger than the 1GB safety limit")
                    handle.write(chunk)
    if total == 0:
        raise RuntimeError(f"Downloaded empty video: {url}")
    return out_path


def _probe_media(path: str) -> dict[str, Any]:
    import json as _json

    result = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", path],
        capture_output=True,
        text=True,
        check=True,
    )
    streams = _json.loads(result.stdout).get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream:
        raise RuntimeError(f"No video stream found in {path}")
    return {
        "width": int(video_stream.get("width") or 720),
        "height": int(video_stream.get("height") or 1280),
        "duration": float(video_stream.get("duration") or 0),
        "has_audio": audio_stream is not None,
    }


def _pick_target_size(path: str, *, preview: bool = False) -> tuple[int, int]:
    media = _probe_media(path)
    width = max(2, int(media["width"]) // 2 * 2)
    height = max(2, int(media["height"]) // 2 * 2)
    if preview:
        if width >= height:
            target_height = min(height, 480)
            target_width = int(target_height * width / height) // 2 * 2
        else:
            target_width = min(width, 480)
            target_height = int(target_width * height / width) // 2 * 2
        width = max(2, target_width)
        height = max(2, target_height)
    return width, height


def _normalize_clip(
    input_path: str,
    out_path: str,
    width: int,
    height: int,
    *,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
    crf: int = 20,
    preset: str = "veryfast",
) -> None:
    media = _probe_media(input_path)
    source_duration = max(float(media.get("duration") or 0), 0.1)
    trim_start = max(0.0, float(trim_start or 0.0))
    trim_end = max(0.0, float(trim_end or 0.0))
    effective_duration = max(source_duration - trim_start - trim_end, 0.1)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,format=yuv420p"
    )
    cmd = [FFMPEG, "-y"]
    if trim_start > 0:
        cmd.extend(["-ss", f"{trim_start:.3f}"])
    cmd.extend(["-i", input_path])
    if media["has_audio"]:
        cmd.extend([
            "-map", "0:v:0", "-map", "0:a:0",
            "-t", f"{effective_duration:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            out_path,
        ])
    else:
        cmd.extend([
            "-f", "lavfi", "-t", f"{effective_duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map", "0:v:0", "-map", "1:a:0",
            "-t", f"{effective_duration:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-c:a", "aac", "-shortest",
            "-movflags", "+faststart",
            out_path,
        ])
    subprocess.run(cmd, capture_output=True, check=True)


def score_scenes(scenes: list, transcripts: list) -> list:
    if not scenes:
        return []

    durations = [s["duration_sec"] for s in scenes]
    max_dur = max(durations) if durations else 1.0
    min_dur = min(durations) if durations else 0.0

    all_words = [
        sum(len(t["text"]) for t in transcripts if t["start_sec"] < s["end_sec"] and t["end_sec"] > s["start_sec"])
        for s in scenes
    ]
    max_words = max(all_words) if all_words else 1

    scored = []
    for i, scene in enumerate(scenes):
        dur = scene["duration_sec"] or 0.001

        dialogue_score = all_words[i] / max_words if max_words else 0.0

        dur_range = max_dur - min_dur if max_dur > min_dur else 1.0
        mid_dur = (max_dur + min_dur) / 2
        pace_score = 1.0 - abs(dur - mid_dur) / (dur_range / 2)
        pace_score = max(0.0, pace_score)

        quality = round(dialogue_score * 0.6 + pace_score * 0.4, 4)
        scored.append({**scene, "quality_score": quality})

    return scored


def _get_video_duration(path: str) -> float:
    """Return video duration in seconds via ffprobe, fallback to 5.0."""
    try:
        import json as _json
        result = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, check=True,
        )
        streams = _json.loads(result.stdout).get("streams", [])
        for s in streams:
            if s.get("codec_type") == "video":
                return float(s.get("duration") or 0)
    except Exception as exc:
        logger.warning("ffprobe duration detection failed for %s: %s", path, exc)
    return 5.0


def concat_scenes_with_transitions(scene_paths: list, out_path: str,
                                    transitions: list = None,
                                    subtitles: list = None,
                                    bgm_path: str = None,
                                    bgm_volume: float = 0.15,
                                    video_crf: int = 18,
                                    video_preset: str = "medium"):
    """Concat scenes with crossfade transitions, burned subtitles, and BGM overlay."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if not transitions and not subtitles and not bgm_path:
        return concat_scenes(scene_paths, out_path)

    filter_parts = []
    inputs = []
    for i, p in enumerate(scene_paths):
        inputs.extend(["-i", p])

    n = len(scene_paths)
    fade_duration = 0.5

    if n == 1:
        filter_parts.append(f"[0:v]copy[outv];[0:a]anull[outa]")
    else:
        # Compute cumulative offsets so xfade knows when each clip starts
        durations = [_get_video_duration(p) for p in scene_paths]
        cumulative = 0.0
        prev = "[0:v]"
        for i in range(1, n):
            transition = (transitions[i - 1] if transitions and i - 1 < len(transitions) else "").lower()
            out_label = f"[v{i}]"
            cumulative += durations[i - 1]
            offset = max(0.0, cumulative - fade_duration)
            fd = fade_duration if "fade" in transition or "dissolve" in transition else 0.3
            filter_parts.append(
                f"{prev}[{i}:v]xfade=transition=fade:duration={fd}:offset={offset:.3f}{out_label}"
            )
            prev = out_label
        filter_parts.append(f"{prev}copy[outv]")

        audio_labels = "".join(f"[{i}:a]" for i in range(n))
        filter_parts.append(f"{audio_labels}concat=n={n}:v=0:a=1[outa]")

    if subtitles:
        srt_file = tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8")
        for idx, sub in enumerate(subtitles, 1):
            start = sub.get("start", 0)
            end = sub.get("end", start + 3)
            text = sub.get("text", "")
            srt_file.write(f"{idx}\n")
            srt_file.write(f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n")
            srt_file.write(f"{text}\n\n")
        srt_file.close()
        srt_path = srt_file.name.replace("\\", "/").replace(":", "\\\\:")
        filter_parts[-2] = filter_parts[-2].replace("[outv]", f"[prevv];[prevv]subtitles='{srt_path}':force_style='FontSize=22,PrimaryColour=&HFFFFFF&,Alignment=2'[outv]")

    filter_complex = ";".join(filter_parts)

    cmd = [FFMPEG, "-y"] + inputs
    bgm_temp_path = None
    bgm_source_path = None
    try:
        if bgm_path:
            bgm_temp_path = Path(os.path.dirname(out_path)) / f".bgm_{uuid.uuid4().hex}{Path(str(bgm_path)).suffix or '.audio'}"
            bgm_source_path = _resolve_bgm_audio(bgm_path, bgm_temp_path)
        if bgm_source_path:
            safe_volume = max(0.0, min(1.0, float(bgm_volume or 0.15)))
            cmd.extend(["-i", str(bgm_source_path)])
            cmd.extend([
                "-filter_complex",
                filter_complex + f";[{n}:a]volume={safe_volume:.3f}[bgm];[outa][bgm]amix=inputs=2:duration=first:dropout_transition=2[finala]",
            ])
            cmd.extend(["-map", "[outv]", "-map", "[finala]"])
        else:
            cmd.extend(["-filter_complex", filter_complex])
            cmd.extend(["-map", "[outv]", "-map", "[outa]"])
    except Exception as exc:
        logger.warning("BGM resolution failed for %s, exporting without BGM: %s", bgm_path, exc)
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[outv]", "-map", "[outa]"])

    cmd.extend(["-c:v", "libx264", "-crf", str(video_crf), "-preset", video_preset, "-c:a", "aac", out_path])

    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("FFmpeg filter export failed, falling back to plain concat: %s", exc)
        concat_scenes(scene_paths, out_path)
    finally:
        if bgm_temp_path and os.path.exists(bgm_temp_path):
            try:
                os.unlink(bgm_temp_path)
            except OSError:
                pass


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def overlay_voiceover(video_path: str, audio_path: str, out_path: str,
                      has_original_audio: bool = True):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if has_original_audio:
        subprocess.run([
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2",
            "-c:v", "copy", "-c:a", "aac",
            out_path,
        ], capture_output=True, check=True)
    else:
        subprocess.run([
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            out_path,
        ], capture_output=True, check=True)
