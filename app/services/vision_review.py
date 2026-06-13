"""Vision review adapter for generated image and video candidates.

This module deliberately keeps the first version provider-agnostic. Production
can register a callable backend later; until then callers receive a typed
unavailable error and can fall back to deterministic rule review.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

IMAGE_CHECKS = (
    "face_clarity",
    "person_count",
    "subject_consistency",
    "reference_match",
    "composition_cleanliness",
)

VIDEO_CHECKS = (
    *IMAGE_CHECKS,
    "video_motion_stability",
    "identity_drift",
)

CRITICAL_CHECKS = {
    "face_clarity",
    "person_count",
    "subject_consistency",
    "reference_match",
    "video_motion_stability",
    "identity_drift",
}

VisionReviewProvider = Callable[[str, dict[str, Any], str, dict[str, Any]], dict[str, Any] | None]
_VISION_REVIEW_PROVIDER: VisionReviewProvider | None = None
_VISION_REVIEW_PROVIDER_PATH: str = ""


class VisionReviewUnavailable(RuntimeError):
    """Raised when no visual model/provider is available for review."""


def set_vision_review_provider(provider: VisionReviewProvider | None) -> None:
    global _VISION_REVIEW_PROVIDER
    _VISION_REVIEW_PROVIDER = provider


def configure_vision_review_provider(provider_path: str | None = None) -> VisionReviewProvider | None:
    global _VISION_REVIEW_PROVIDER, _VISION_REVIEW_PROVIDER_PATH
    path = str(provider_path if provider_path is not None else get_settings().vision_review_provider or "").strip()
    if not path:
        _VISION_REVIEW_PROVIDER = None
        _VISION_REVIEW_PROVIDER_PATH = ""
        return None
    if _VISION_REVIEW_PROVIDER is not None and _VISION_REVIEW_PROVIDER_PATH == path:
        return _VISION_REVIEW_PROVIDER
    module_name, sep, attr = path.partition(":")
    if not sep:
        module_name, _, attr = path.rpartition(".")
    if not module_name or not attr:
        raise VisionReviewUnavailable(f"invalid vision review provider path: {path}")
    module = importlib.import_module(module_name)
    provider = getattr(module, attr)
    if not callable(provider):
        raise VisionReviewUnavailable(f"vision review provider is not callable: {path}")
    _VISION_REVIEW_PROVIDER = provider
    _VISION_REVIEW_PROVIDER_PATH = path
    logger.info("Configured vision review provider: %s", path)
    return _VISION_REVIEW_PROVIDER


def review_image_with_vision(
    shot: dict[str, Any] | None,
    image_url: str,
    refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _review_with_vision("image", shot or {}, image_url, refs or {})


def review_video_with_vision(
    shot: dict[str, Any] | None,
    video_url: str,
    refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _review_with_vision("video", shot or {}, video_url, refs or {})


def _review_with_vision(
    media_type: str,
    shot: dict[str, Any],
    media_url: str,
    refs: dict[str, Any],
) -> dict[str, Any]:
    if not media_url:
        raise VisionReviewUnavailable("missing media url")
    provider = _VISION_REVIEW_PROVIDER or configure_vision_review_provider()
    if provider is None:
        raise VisionReviewUnavailable("vision review provider is not configured")
    raw = provider(media_type, shot, media_url, refs)
    if not isinstance(raw, dict):
        raise VisionReviewUnavailable("vision review provider returned no report")
    return normalize_vision_review(media_type, raw)


def normalize_vision_review(media_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    checks = _normalize_checks(media_type, raw.get("checks"))
    score = _score_from_checks(checks, raw.get("score"))
    status = _status_from_checks(media_type, score, checks, raw.get("status"))
    notes = _notes_from_report(status, checks, raw.get("notes"))
    actions = _actions_from_report(media_type, status, checks, raw.get("actions"))
    return {
        "version": "vision_review_v1",
        "media_type": media_type,
        "status": status,
        "score": score,
        "notes": notes,
        "actions": _unique(actions),
        "checks": checks,
        "review_source": "vision",
    }


def _normalize_checks(media_type: str, raw_checks: Any) -> list[dict[str, Any]]:
    names = VIDEO_CHECKS if media_type == "video" else IMAGE_CHECKS
    raw_by_name: dict[str, Any] = {}
    if isinstance(raw_checks, dict):
        raw_by_name = raw_checks
    elif isinstance(raw_checks, list):
        raw_by_name = {
            str(item.get("name") or item.get("check") or ""): item
            for item in raw_checks
            if isinstance(item, dict)
        }

    checks: list[dict[str, Any]] = []
    for name in names:
        raw = raw_by_name.get(name) if isinstance(raw_by_name.get(name), dict) else {}
        if name in raw_by_name and not raw:
            raw = {"score": raw_by_name.get(name)}
        score = _clamp_score(raw.get("score"), default=70)
        status = str(raw.get("status") or _check_status(score)).strip() or _check_status(score)
        note = str(raw.get("note") or raw.get("notes") or "").strip()
        check = {
            "name": name,
            "status": status,
            "score": score,
        }
        if note:
            check["note"] = note
        checks.append(check)
    return checks


def _score_from_checks(checks: list[dict[str, Any]], raw_score: Any) -> int:
    if raw_score is not None:
        return _clamp_score(raw_score, default=0)
    if not checks:
        return 0
    return _clamp_score(round(sum(int(item.get("score") or 0) for item in checks) / len(checks)), default=0)


def _status_from_checks(media_type: str, score: int, checks: list[dict[str, Any]], raw_status: Any) -> str:
    if raw_status in {"usable", "cuttable", "needs_review", "regenerate"}:
        if raw_status == "cuttable" and media_type != "video":
            return "usable"
        if raw_status == "usable" and media_type == "video":
            return "cuttable"
        return str(raw_status)

    has_critical_fail = any(
        item.get("name") in CRITICAL_CHECKS and item.get("status") == "fail"
        for item in checks
    )
    if has_critical_fail or score < 50:
        return "regenerate"
    if media_type == "video":
        return "cuttable" if score >= 74 else "needs_review"
    return "usable" if score >= 72 else "needs_review"


def _notes_from_report(status: str, checks: list[dict[str, Any]], raw_notes: Any) -> list[str]:
    notes = [str(item) for item in raw_notes if item] if isinstance(raw_notes, list) else []
    risky = [item for item in checks if item.get("status") in {"fail", "warning"}]
    for item in risky:
        note = item.get("note") or f"{item.get('name')} 检查未完全通过。"
        notes.append(str(note))
    if not notes:
        notes.append("视觉审查通过。")
    elif status == "regenerate":
        notes.insert(0, "视觉审查发现高风险问题。")
    return _unique(notes)


def _actions_from_report(media_type: str, status: str, checks: list[dict[str, Any]], raw_actions: Any) -> list[str]:
    actions = [str(item) for item in raw_actions if item] if isinstance(raw_actions, list) else []
    if status == "regenerate":
        actions.append("重新生成图片" if media_type == "image" else "重新生成视频")
    elif status == "needs_review":
        actions.append("人工确认后再进入下一步")
    elif media_type == "video":
        actions.append("可进入剪辑")
    else:
        actions.append("可进入视频生成")

    failed_names = {item.get("name") for item in checks if item.get("status") == "fail"}
    if "reference_match" in failed_names or "subject_consistency" in failed_names:
        actions.append("补齐或锁定参考资产后重试")
    if "identity_drift" in failed_names:
        actions.append("缩短视频时长或加强角色参考后重试")
    return actions


def _check_status(score: int) -> str:
    if score >= 72:
        return "pass"
    if score >= 50:
        return "warning"
    return "fail"


def _clamp_score(value: Any, *, default: int) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = default
    return max(0, min(100, score))


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
