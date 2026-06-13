from __future__ import annotations

from typing import Any


DEFAULT_EXPORT_SETTINGS = {
    "transition": "fade",
    "burn_subtitles": True,
    "subtitle_source": "prompt",
    "bgm_path": "",
    "bgm_volume": 0.15,
    "cover_title": "",
    "cover_frame_sec": None,
}


def build_default_edit_plan(shot_rows: list[dict[str, Any]]) -> dict[str, Any]:
    clips = []
    for order, row in enumerate(shot_rows, 1):
        video_url = str(row.get("selected_video") or "").strip()
        if not video_url:
            continue
        duration = _positive_float(row.get("duration"), 5.0)
        clips.append(
            {
                "shot_index": int(row.get("shot_index") or row.get("index") or order),
                "order": order,
                "enabled": True,
                "video_url": video_url,
                "prompt": str(row.get("prompt") or ""),
                "duration": duration,
                "trim_start": 0.0,
                "trim_end": 0.0,
                "transition": DEFAULT_EXPORT_SETTINGS["transition"],
                "subtitle": str(row.get("prompt") or ""),
            }
        )
    return {
        "version": 1,
        "settings": dict(DEFAULT_EXPORT_SETTINGS),
        "clips": clips,
    }


def merge_plan_with_shots(plan: dict[str, Any] | None, shot_rows: list[dict[str, Any]]) -> dict[str, Any]:
    default_plan = build_default_edit_plan(shot_rows)
    if not isinstance(plan, dict):
        return default_plan

    shot_by_index = {
        int(row.get("shot_index") or row.get("index")): row
        for row in shot_rows
        if row.get("shot_index") is not None or row.get("index") is not None
    }
    saved_clips = plan.get("clips") if isinstance(plan.get("clips"), list) else []
    merged = []
    seen: set[int] = set()
    for raw_clip in saved_clips:
        if not isinstance(raw_clip, dict):
            continue
        shot_index = _int_or_none(raw_clip.get("shot_index"))
        if shot_index is None or shot_index not in shot_by_index:
            continue
        row = shot_by_index[shot_index]
        video_url = str(row.get("selected_video") or raw_clip.get("video_url") or "").strip()
        if not video_url:
            continue
        duration = _positive_float(row.get("duration"), _positive_float(raw_clip.get("duration"), 5.0))
        merged.append(
            normalize_clip(
                {
                    **raw_clip,
                    "shot_index": shot_index,
                    "video_url": video_url,
                    "prompt": row.get("prompt") or raw_clip.get("prompt") or "",
                    "duration": duration,
                },
                len(merged) + 1,
            )
        )
        seen.add(shot_index)

    for clip in default_plan["clips"]:
        if clip["shot_index"] not in seen:
            clip["order"] = len(merged) + 1
            merged.append(clip)

    settings = {
        **DEFAULT_EXPORT_SETTINGS,
        **(plan.get("settings") if isinstance(plan.get("settings"), dict) else {}),
    }
    return {"version": 1, "settings": settings, "clips": merged}


def normalize_edit_plan(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("edit plan must be an object")
    raw_clips = raw.get("clips")
    if not isinstance(raw_clips, list):
        raise ValueError("edit plan clips must be a list")
    settings = {
        **DEFAULT_EXPORT_SETTINGS,
        **(raw.get("settings") if isinstance(raw.get("settings"), dict) else {}),
    }
    clips = [normalize_clip(clip, idx + 1) for idx, clip in enumerate(raw_clips) if isinstance(clip, dict)]
    clips.sort(key=lambda item: item["order"])
    for idx, clip in enumerate(clips, 1):
        clip["order"] = idx
    return {"version": 1, "settings": settings, "clips": clips}


def normalize_clip(raw: dict[str, Any], fallback_order: int) -> dict[str, Any]:
    shot_index = _int_or_none(raw.get("shot_index"))
    if shot_index is None:
        raise ValueError("clip shot_index is required")
    duration = _positive_float(raw.get("duration"), 5.0)
    trim_start = max(0.0, _positive_float(raw.get("trim_start"), 0.0))
    trim_end = max(0.0, _positive_float(raw.get("trim_end"), 0.0))
    if trim_start + trim_end >= duration:
        trim_start = 0.0
        trim_end = 0.0
    return {
        "shot_index": shot_index,
        "order": max(1, _int_or_none(raw.get("order")) or fallback_order),
        "enabled": bool(raw.get("enabled", True)),
        "video_url": str(raw.get("video_url") or raw.get("selected_video") or "").strip(),
        "prompt": str(raw.get("prompt") or ""),
        "duration": duration,
        "trim_start": round(trim_start, 3),
        "trim_end": round(trim_end, 3),
        "transition": _normalize_transition(raw.get("transition")),
        "subtitle": str(raw.get("subtitle") or raw.get("prompt") or ""),
    }


def export_payload_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_edit_plan(plan)
    clips = [
        clip for clip in normalized["clips"]
        if clip["enabled"] and clip["video_url"]
    ]
    transitions = [
        clip.get("transition") or normalized["settings"].get("transition") or "fade"
        for clip in clips[1:]
    ]
    subtitles = None
    if normalized["settings"].get("burn_subtitles"):
        subtitles = []
        cursor = 0.0
        for clip in clips:
            duration = max(0.1, clip["duration"] - clip["trim_start"] - clip["trim_end"])
            text = str(clip.get("subtitle") or clip.get("prompt") or "").strip()
            if text:
                subtitles.append({"start": round(cursor, 3), "end": round(cursor + duration, 3), "text": text})
            cursor += duration
    return {
        "clips": clips,
        "transitions": transitions,
        "subtitles": subtitles,
        "bgm_path": str(normalized["settings"].get("bgm_path") or "").strip() or None,
        "bgm_volume": _clamp_float(normalized["settings"].get("bgm_volume"), 0.15, 0.0, 1.0),
    }


def validate_delivery_plan(
    plan: dict[str, Any],
    *,
    require_bgm: bool = True,
    require_subtitles: bool = True,
    require_voiceover: bool | None = None,
) -> dict[str, Any]:
    """Validate final-cut delivery completeness before preview/export.

    This is the executable counterpart of the project brain final delivery
    audit. It deliberately blocks incomplete commercial exports instead of
    relying on UI warnings alone.
    """
    normalized = normalize_edit_plan(plan)
    raw_settings = plan.get("settings") if isinstance(plan.get("settings"), dict) else {}
    raw_clips = plan.get("clips") if isinstance(plan.get("clips"), list) else []
    clips = [
        clip for clip in normalized["clips"]
        if clip["enabled"] and clip["video_url"]
    ]
    errors: list[dict[str, Any]] = []
    if not clips:
        errors.append({"code": "missing_clips", "message": "No enabled video clips are available for export."})
    if require_bgm and not str(normalized["settings"].get("bgm_path") or "").strip():
        errors.append({"code": "missing_bgm", "message": "BGM is required before preview/export."})
    if require_subtitles and normalized["settings"].get("burn_subtitles"):
        missing_subtitles = [
            clip["shot_index"]
            for clip in clips
            if not str(clip.get("subtitle") or "").strip()
        ]
        if missing_subtitles:
            errors.append({
                "code": "missing_subtitles",
                "message": "Subtitles are required when burn_subtitles is enabled.",
                "shot_indices": missing_subtitles,
            })

    voice_required = (
        bool(require_voiceover)
        if require_voiceover is not None
        else bool(raw_settings.get("require_voiceover") or raw_settings.get("voiceover_required"))
    )
    if voice_required and not _has_voice_asset(raw_settings, raw_clips):
        errors.append({"code": "missing_voiceover", "message": "Voiceover/TTS audio is required before preview/export."})

    return {
        "passed": not errors,
        "errors": errors,
        "clip_count": len(clips),
    }


def _has_voice_asset(settings: dict[str, Any], clips: list[Any]) -> bool:
    for key in ("voiceover_path", "voice_path", "tts_path", "audio_path", "voiceover_url", "tts_url", "audio_url"):
        if str(settings.get(key) or "").strip():
            return True
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        for key in ("voiceover_audio", "voice_url", "tts_url", "audio_url"):
            if str(clip.get(key) or "").strip():
                return True
    return False


def _normalize_transition(value: Any) -> str:
    normalized = str(value or "fade").strip().lower()
    if normalized in {"none", "cut", "fade", "dissolve"}:
        return normalized
    return "fade"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    return number


def _clamp_float(value: Any, default: float, min_value: float, max_value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, number))
