"""Single-pass shot analysis — traverse all shots once, compute every metric.

The original code computed the same aggregates (``high_risk_shot_count``,
``image_review_blocking_count``, etc.) multiple times by re-iterating
over shots in separate functions.  This module does it **once**.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.types import ReviewStatus
from app.services.ledgers.models import ShotAnalysis, ShotAnalysisItem

# ── Constants ───────────────────────────────────────────────────────────────

PASS_IMAGE_STATUSES = ReviewStatus.passing()
PASS_VIDEO_STATUSES = ReviewStatus.passing()  # same set
BLOCKING_REVIEW_STATUSES = ReviewStatus.blocking()
DONE_STATUSES = frozenset({"video_done", "done", "final_done", "exported"})

# Voice-related keywords
_VOICE_KEYWORDS = frozenset({"dialogue", "voiceover", "旁白", "对白", "台词", "tts"})

# Strategy tokens
_CLOSE_UP_TOKENS = ("特写", "close-up", "close up", "近景", "reaction")
_WIDE_TOKENS = ("全景", "wide", "establishing", "远景")
_MOTION_TOKENS = ("推进", "push", "dolly", "跟拍", "pan", "横移")

# Visual quality rule keys
_VISUAL_QUALITY_KEYS = (
    "visual_quality_rules", "quality_controls", "motion_controls",
    "negative_prompt", "lock_character", "lock_scene",
    "lock_costume", "lock_prop",
)

# Voice rule keys
_VOICE_KEYS = ("voice_delivery_rules", "tts_payload", "voice", "voiceover_audio", "tts_url", "audio_url")


def analyze_shots(shots: list[dict[str, Any]]) -> ShotAnalysis:
    """Analyze all shots in a single pass.

    Args:
        shots: List of raw shot-row dicts.

    Returns:
        A ``ShotAnalysis`` with all aggregate counts and per-shot items.
    """
    total = len(shots)
    with_prompt = 0
    with_selected_image = 0
    with_selected_video = 0
    with_prompt_revision = 0
    with_preflight = 0
    with_image_review = 0
    with_video_review = 0
    image_review_blocking = 0
    video_review_blocking = 0
    needs_image_count = 0
    needs_video_count = 0
    needs_tts_count = 0
    has_char_lock = 0
    has_style_refs = 0
    has_voice_rules = 0
    image_review_passed = 0
    video_review_passed = 0

    library_counts: dict[str, dict[str, int]] = {}
    per_shot: list[ShotAnalysisItem] = []
    shots_with_text: list[str] = []

    for shot in shots:
        item = _analyze_one(shot, library_counts)
        per_shot.append(item)

        if item.has_prompt:
            with_prompt += 1
        if item.has_image:
            with_selected_image += 1
        if item.has_video:
            with_selected_video += 1
        if item.has_prompt_revision:
            with_prompt_revision += 1
        if item.has_preflight:
            with_preflight += 1
        if item.image_review_status:
            with_image_review += 1
        if item.video_review_status:
            with_video_review += 1
        if item.image_review_status in BLOCKING_REVIEW_STATUSES:
            image_review_blocking += 1
        if item.video_review_status in BLOCKING_REVIEW_STATUSES:
            video_review_blocking += 1
        if item.needs_image:
            needs_image_count += 1
        if item.needs_video:
            needs_video_count += 1
        if item.needs_tts:
            needs_tts_count += 1
        if item.has_character_lock:
            has_char_lock += 1
        if item.has_style_refs:
            has_style_refs += 1
        if item.has_voice_rules:
            has_voice_rules += 1
        if item.image_review_passed:
            image_review_passed += 1
        if item.video_review_passed:
            video_review_passed += 1
        if item.prompt_text:
            shots_with_text.append(item.prompt_text)

    return ShotAnalysis(
        total=total,
        with_prompt=with_prompt,
        with_selected_image=with_selected_image,
        with_selected_video=with_selected_video,
        with_prompt_revision=with_prompt_revision,
        with_preflight=with_preflight,
        with_image_review=with_image_review,
        with_video_review=with_video_review,
        image_review_blocking=image_review_blocking,
        video_review_blocking=video_review_blocking,
        needs_image=needs_image_count,
        needs_video=needs_video_count,
        needs_tts=needs_tts_count,
        has_character_lock_count=has_char_lock,
        has_style_refs_count=has_style_refs,
        has_voice_rules_count=has_voice_rules,
        image_review_passed_count=image_review_passed,
        video_review_passed_count=video_review_passed,
        library_counts=library_counts,
        per_shot=per_shot,
        shots_with_text=shots_with_text,
    )


def _analyze_one(shot: dict[str, Any], library_counts: dict[str, dict[str, int]]) -> ShotAnalysisItem:
    """Analyze a single shot row, updating *library_counts* in place."""
    shot_index = int(shot.get("shot_index") or 0)
    prompt_text = str(shot.get("prompt") or shot.get("raw_text") or shot.get("scene_description") or "").strip()
    status = str(shot.get("status") or "").strip().lower()
    voiceover = str(shot.get("voiceover") or "").strip()
    dialogue = str(shot.get("dialogue") or "").strip()
    subtitle = str(shot.get("subtitle") or "").strip()
    has_prompt = bool(prompt_text)
    has_selected_image = bool(shot.get("selected_image"))
    has_selected_video = bool(shot.get("selected_video"))
    has_video = has_selected_video or status in DONE_STATUSES

    # Libraries
    libraries = _as_strings(shot.get("matched_libraries"))
    has_passed_review = _review_passed(shot, "image") or _review_passed(shot, "video")
    for name in libraries:
        entry = library_counts.setdefault(name, {"shot_count": 0, "reviewed_count": 0})
        entry["shot_count"] += 1
        if has_passed_review:
            entry["reviewed_count"] += 1

    # Various checks
    has_revision = isinstance(shot.get("prompt_revision"), dict) and bool(shot.get("prompt_revision"))
    has_preflight = isinstance(shot.get("director_preflight"), dict) and bool(shot.get("director_preflight"))
    image_review_st = _review_status(shot, "image")
    video_review_st = _review_status(shot, "video")
    img_review_passed = image_review_st in PASS_IMAGE_STATUSES
    vid_review_passed = video_review_st in PASS_VIDEO_STATUSES
    preflight_st = _preflight_status(shot)

    needs_image = has_prompt and not has_selected_image and status not in {"generating_image", "running_image"}
    needs_video = (has_prompt or has_selected_image) and not has_video and status not in {"generating_video", "running_video"}
    needs_tts = bool(voiceover or dialogue or subtitle) and not _has_voice_rules(shot)

    episode, scene = extract_episode_scene(shot, prompt_text)
    return ShotAnalysisItem(
        shot_index=shot_index,
        has_prompt=has_prompt,
        has_prompt_revision=has_revision,
        has_preflight=has_preflight,
        has_image=has_selected_image,
        has_video=has_video,
        has_visual_quality_rules=_has_visual_rules(shot),
        has_voice_rules=_has_voice_rules(shot),
        has_humanizer_marker=_has_humanizer(shot),
        needs_image=needs_image,
        needs_video=needs_video,
        needs_tts=needs_tts,
        image_review_status=image_review_st,
        video_review_status=video_review_st,
        matched_libraries=libraries,
        director_preflight_status=preflight_st,
        image_review_passed=img_review_passed,
        video_review_passed=vid_review_passed,
        has_character_lock=_has_any_lock(shot, "character"),
        has_scene_lock=_has_any_lock(shot, "scene"),
        has_style_refs=bool(_as_strings(shot.get("style_refs")) or _as_strings(shot.get("style_refs_json"))),
        duration=_duration(shot),
        prompt_text=prompt_text,
        voiceover=voiceover,
        dialogue=dialogue,
        subtitle=subtitle,
        episode=episode,
        scene=scene,
    )


# ── Review status helpers ───────────────────────────────────────────────────

def _review_status(shot: dict[str, Any], media_type: str) -> str:
    for key in (f"{media_type}_candidate", f"selected_{media_type}_candidate",
                f"{media_type}_review", f"{media_type}_review_result"):
        val = shot.get(key)
        if not isinstance(val, dict):
            continue
        status = str(val.get("review_status") or val.get("status") or "").strip().lower()
        if status:
            return status
        review = val.get("review") if isinstance(val.get("review"), dict) else {}
        status = str(review.get("status") or "").strip().lower()
        if status:
            return status
    # Fallback: check image_candidates / video_variants
    list_key = "image_candidates" if media_type == "image" else "video_variants"
    sel_key = "selected_image" if media_type == "image" else "selected_video"
    selected_url = str(shot.get(sel_key) or "").strip()
    candidates = shot.get(list_key)
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        st = str(candidate.get("review_status") or candidate.get("status") or "").strip().lower()
        if not st:
            continue
        url = str(candidate.get("url") or candidate.get("uri") or candidate.get("image_url") or candidate.get("video_url") or "").strip()
        if selected_url and url == selected_url:
            return st
    return ""


def _review_passed(shot: dict[str, Any], media_type: str) -> bool:
    status = _review_status(shot, media_type)
    pass_set = PASS_VIDEO_STATUSES if media_type == "video" else PASS_IMAGE_STATUSES
    return status in pass_set


def _preflight_status(shot: dict[str, Any]) -> str:
    preflight = shot.get("director_preflight")
    if not isinstance(preflight, dict):
        return ""
    return str(preflight.get("risk_level") or preflight.get("status") or "checked").strip().lower()


# ── Capability checks ───────────────────────────────────────────────────────

def _has_visual_rules(shot: dict[str, Any]) -> bool:
    return any(bool(shot.get(k)) for k in _VISUAL_QUALITY_KEYS)


def _has_voice_rules(shot: dict[str, Any]) -> bool:
    return any(bool(shot.get(k)) for k in _VOICE_KEYS)


def _has_humanizer(shot: dict[str, Any]) -> bool:
    val = shot.get("content_humanizer")
    if isinstance(val, dict) and val:
        return True
    return "humanized" in str(shot.get("revision_source") or shot.get("source") or "").lower()


def _has_any_lock(shot: dict[str, Any], prefix: str) -> bool:
    for key in (f"lock_{prefix}",):
        if bool(shot.get(key)):
            return True
    # Also check reference bindings as implicit locks
    ref_key = f"{prefix}_refs"
    ref_json = f"{prefix}_refs_json"
    return bool(_as_strings(shot.get(ref_key)) or _as_strings(shot.get(ref_json)))


# ── Data extraction helpers ─────────────────────────────────────────────────

def _as_strings(value) -> list[str]:
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                text = str(item.get("name") or item.get("asset_id") or item.get("id") or "").strip()
            else:
                text = str(item).strip()
            if text and text not in result:
                result.append(text)
        return result
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _duration(shot: dict[str, Any]) -> float:
    try:
        value = float(shot.get("duration") or shot.get("duration_seconds") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(0.1, value)


def _episode_num(shot: dict[str, Any]) -> int:
    for k in ("episode", "episode_index"):
        try:
            return int(shot.get(k) or 0)
        except (TypeError, ValueError):
            continue
    return 1


def _scene_num(shot: dict[str, Any]) -> int:
    for k in ("scene", "scene_index"):
        try:
            return int(shot.get(k) or 0)
        except (TypeError, ValueError):
            continue
    return 1


# ── Continuity helpers ──────────────────────────────────────────────────────

_EPISODE_SCENE_RE = re.compile(r"第\s*(\d+)\s*集\s*第\s*(\d+)\s*场")
_EPISODE_SCENE_EN_RE = re.compile(r"\bE(?:P)?\s*(\d{1,2})\s*S(?:C)?\s*(\d{1,2})\b", re.IGNORECASE)
_EPISODE_SCENE_FULL_RE = re.compile(r"\bEpisode\s*(\d{1,2})\s*Scene\s*(\d{1,2})\b", re.IGNORECASE)


def extract_episode_scene(shot: dict[str, Any], text: str = "") -> tuple[int, int]:
    """Extract (episode, scene) from shot fields or fallback to text parsing."""
    for ep_key, sc_key in (("episode", "scene"), ("episode_index", "scene_index")):
        ep = _int_or_none(shot.get(ep_key))
        sc = _int_or_none(shot.get(sc_key))
        if ep and sc:
            return ep, sc
    text = text or str(shot.get("prompt") or shot.get("raw_text") or "")
    for pat in (_EPISODE_SCENE_RE, _EPISODE_SCENE_EN_RE, _EPISODE_SCENE_FULL_RE):
        m = pat.search(text)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 1, 1


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── Scene grouping ──────────────────────────────────────────────────────────

def group_by_scene(shots: list[dict[str, Any]], analysis: ShotAnalysis | None = None) -> list[dict[str, Any]]:
    """Group shots into scenes, returning ordered list of scene dicts."""
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in (analysis.per_shot if analysis else None) or [_analyze_one(s, {}) for s in shots]:
        ep, sc = item.episode, item.scene
        key = f"E{ep:02d}S{sc:02d}"
        if key not in groups:
            groups[key] = {"scene_key": key, "episode": ep, "scene": sc, "shots": []}
            order.append(key)
        groups[key]["shots"].append(item)
    return [groups[k] for k in order]
