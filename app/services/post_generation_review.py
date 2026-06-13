"""Lightweight post-generation review reports for produced media candidates.

This first pass is intentionally deterministic. It does not inspect pixels yet;
it records whether the generated candidate is usable under the known shot
constraints so the UI can show an审片 flow and later swap in a vision model.
"""

from __future__ import annotations

from typing import Any

from app.services.director_preflight import analyze_shot_risk
from app.services import vision_review


def review_image_candidate(shot: dict[str, Any] | None, image_url: str) -> dict[str, Any]:
    shot = shot or {}
    try:
        return vision_review.review_image_with_vision(shot, image_url, _refs_from_shot(shot))
    except vision_review.VisionReviewUnavailable:
        return _rule_review_image_candidate(shot, image_url)
    except Exception:
        return _rule_review_image_candidate(shot, image_url)


def review_video_candidate(shot: dict[str, Any] | None, video_url: str) -> dict[str, Any]:
    shot = shot or {}
    try:
        return vision_review.review_video_with_vision(shot, video_url, _refs_from_shot(shot))
    except vision_review.VisionReviewUnavailable:
        return _rule_review_video_candidate(shot, video_url)
    except Exception:
        return _rule_review_video_candidate(shot, video_url)


def _rule_review_image_candidate(shot: dict[str, Any] | None, image_url: str) -> dict[str, Any]:
    shot = shot or {}
    preflight = _preflight(shot)
    score = 86
    notes: list[str] = []
    actions: list[str] = []

    if not image_url:
        return _report("image", "regenerate", 0, ["没有返回图片 URL。"], ["重新生成图片"], "rule")

    level = preflight.get("risk_level")
    if level == "blocked":
        score -= 45
        notes.append("该候选来自高风险分镜，不能直接进入视频。")
        actions.append("先应用安全改写，再重新生成关键帧")
    elif level == "warning":
        score -= 18
        notes.append("该候选仍有资产或提示词风险，需要人工快速确认。")
        actions.append("确认主体、人脸和参考资产后再进入视频")

    missing = preflight.get("missing_refs") or []
    if missing:
        score -= min(25, len(missing) * 6)
        notes.append("生成时仍缺少参考资产：" + "、".join(str(x) for x in missing))
        actions.append("补齐参考资产后可重生更稳的关键帧")

    if not notes:
        notes.append("基础审片通过，可作为图生视频候选。")

    status = "usable" if score >= 72 else "needs_review" if score >= 50 else "regenerate"
    if status == "usable":
        actions.append("可进入视频生成")
    elif status == "needs_review":
        actions.append("人工确认后再进入视频")
    return _report("image", status, score, notes, actions, "rule")


def _rule_review_video_candidate(shot: dict[str, Any] | None, video_url: str) -> dict[str, Any]:
    shot = shot or {}
    preflight = _preflight(shot)
    score = 84
    notes: list[str] = []
    actions: list[str] = []

    if not video_url:
        return _report("video", "regenerate", 0, ["没有返回视频 URL。"], ["重新生成视频"], "rule")

    if not shot.get("selected_image"):
        score -= 18
        notes.append("没有明确关键帧来源，视频连续性风险较高。")
        actions.append("先选择可用关键帧，再重新生成视频")

    level = preflight.get("risk_level")
    if level == "blocked":
        score -= 42
        notes.append("该视频来自高风险分镜，可能存在主体丢失、脸糊或画面拥挤。")
        actions.append("修正分镜并重新生成视频")
    elif level == "warning":
        score -= 14
        notes.append("该视频仍需人工确认主体、动作和连续性。")

    duration = float(shot.get("duration") or 0)
    if duration and (duration < 2 or duration > 10):
        score -= 12
        notes.append("视频时长不在推荐范围 2-10 秒内。")
        actions.append("调整时长后重新生成")

    if not notes:
        notes.append("基础审片通过，可进入剪辑候选。")

    status = "cuttable" if score >= 74 else "needs_review" if score >= 52 else "regenerate"
    if status == "cuttable":
        actions.append("可进入剪辑")
    elif status == "needs_review":
        actions.append("人工确认后再进入剪辑")
    return _report("video", status, score, notes, actions, "rule")


def media_candidate(url: str, review: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": url,
        "review": review,
        "review_status": review.get("status"),
        "review_score": review.get("score"),
    }


def _preflight(shot: dict[str, Any]) -> dict[str, Any]:
    existing = shot.get("director_preflight")
    if isinstance(existing, dict):
        return existing
    return analyze_shot_risk(shot)


def _refs_from_shot(shot: dict[str, Any]) -> dict[str, Any]:
    return {
        "character": shot.get("character_refs") or shot.get("character_refs_json") or [],
        "scene": shot.get("scene_refs") or shot.get("scene_refs_json") or [],
        "prop": shot.get("prop_refs") or shot.get("prop_refs_json") or [],
        "costume": shot.get("costume_refs") or shot.get("costume_refs_json") or [],
        "style": shot.get("style_refs") or shot.get("style_refs_json") or [],
        "selected_image": shot.get("selected_image"),
    }


def _rule_checks(media_type: str, status: str, score: int) -> list[dict[str, Any]]:
    names = vision_review.VIDEO_CHECKS if media_type == "video" else vision_review.IMAGE_CHECKS
    check_status = "pass" if status in {"usable", "cuttable"} else "warning" if status == "needs_review" else "fail"
    return [
        {
            "name": name,
            "status": check_status,
            "score": max(0, min(100, int(score))),
            "note": "规则审片占位，未调用视觉模型。",
        }
        for name in names
    ]


def _report(
    media_type: str,
    status: str,
    score: int,
    notes: list[str],
    actions: list[str],
    review_source: str,
) -> dict[str, Any]:
    normalized_score = max(0, min(100, int(score)))
    return {
        "version": "post_generation_review_v1",
        "media_type": media_type,
        "status": status,
        "score": normalized_score,
        "notes": notes,
        "actions": _unique(actions),
        "checks": _rule_checks(media_type, status, normalized_score),
        "review_source": review_source,
    }


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
