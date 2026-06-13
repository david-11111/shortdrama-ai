"""Final quality readiness ledger — checklist, blocking items, pass rate."""

from __future__ import annotations

from typing import Any

from app.core.types import ReviewStatus
from app.services.ledgers.models import QualityLedger, ShotAnalysis


def build_quality_ledger(
    analysis: ShotAnalysis,
    final_edit_plan: dict[str, Any] | None,
) -> QualityLedger:
    """Build the final quality readiness ledger.

    All counters are read from the single-pass ``ShotAnalysis`` —
    no repeated iterations.
    """
    fe_plan = final_edit_plan if isinstance(final_edit_plan, dict) else {}
    clips = [c for c in (fe_plan.get("clips") or []) if isinstance(c, dict)]
    enabled_clips = [c for c in clips if bool(c.get("enabled", True))]
    settings = fe_plan.get("settings") if isinstance(fe_plan.get("settings"), dict) else {}

    produced_video_count = analysis.with_selected_video

    # Missing shots with no video
    missing_video = [item.shot_index for item in analysis.per_shot if not item.has_video]

    # Audio check
    missing_audio = []
    if _needs_voice(analysis, clips) and not _has_audio(analysis, clips):
        missing_audio.append("voiceover_or_tts")

    # BGM check
    has_clips_or_video = bool(clips or produced_video_count)
    bgm_path = str(settings.get("bgm_path") or "").strip()
    missing_bgm = has_clips_or_video and not bgm_path

    # Failed reviews
    failed_reviews = [
        {"shot_index": item.shot_index, "media_type": "image" if item.image_review_status in ReviewStatus.blocking() else "video",
         "status": item.image_review_status if item.image_review_status in ReviewStatus.blocking() else item.video_review_status}
        for item in analysis.per_shot
        if item.image_review_status in ReviewStatus.blocking() or item.video_review_status in ReviewStatus.blocking()
    ]

    # Subtitle risk
    subtitle_risk = bool(settings.get("burn_subtitles", True)) and any(
        not str(c.get("subtitle") or "").strip() for c in enabled_clips
    )

    # Theme risk
    theme_risk = not any(
        str(settings.get(k) or "").strip()
        for k in ("cover_title", "theme", "title")
    )

    # Edit plan risk
    edit_risk = bool(produced_video_count or clips) and (not enabled_clips or len(enabled_clips) < produced_video_count)

    # Build checklist
    checklist = [
        _check("video_complete", not missing_video, f"{len(missing_video)} shots missing video"),
        _check("audio_or_voice_ready", not missing_audio, "voiceover/TTS missing" if missing_audio else "audio optional or ready"),
        _check("bgm_ready", not missing_bgm, "BGM not selected"),
        _check("reviews_passed", not failed_reviews, f"{len(failed_reviews)} review blockers"),
        _check("subtitles_ready", not subtitle_risk, "enabled clip subtitles are incomplete"),
        _check("theme_ready", not theme_risk, "cover title/theme not set"),
        _check("edit_plan_ready", not edit_risk, "edit plan does not cover all produced videos"),
    ]

    # Blocking items
    blocking = _build_blocking_items(missing_video, missing_audio, missing_bgm, failed_reviews, edit_risk)

    # Score
    passed = sum(1 for c in checklist if c["passed"])
    total = max(len(checklist), 1)
    score = max(0, int(round(100 * passed / total)))
    pass_rate = int(round(100 * passed / total))

    return QualityLedger(
        checklist=checklist,
        ready_score=score,
        quality_score=score,
        quality_score_label=f"{score}分",
        acceptance_status="blocked" if blocking else "ready",
        acceptance_status_label="未通过" if blocking else "可预览",
        pass_rate=pass_rate,
        pass_rate_label=f"{pass_rate}%",
        pending_review_count=len(failed_reviews),
        pending_review_label=f"{len(failed_reviews)} 项",
        next_action_label=blocking[0]["label"] if blocking else "生成预览小样",
        risk_label=blocking[0]["label"] if blocking else "低",
        blocking_items=blocking,
        missing_video_shots=missing_video,
        review_blockers=failed_reviews,
        has_final_edit_plan=bool(clips),
        produced_video_count=produced_video_count,
    )


def _needs_voice(analysis: ShotAnalysis, clips: list[dict]) -> bool:
    text = " ".join(analysis.shots_with_text)
    text += " " + " ".join(str(c.get("subtitle") or c.get("prompt") or "") for c in clips)
    return any(t in text.lower() for t in ("voiceover", "dialogue", "旁白", "对白", "台词", "tts"))


def _has_audio(analysis: ShotAnalysis, clips: list[dict]) -> bool:
    audio_keys = ("audio_url", "tts_url", "voiceover_audio", "voice_url")
    # Check shots
    for item in analysis.per_shot:
        # We don't have raw shot data in ShotAnalysisItem for audio keys
        # so we return False — the caller must provide this
        pass
    for clip in clips:
        if any(clip.get(k) for k in audio_keys):
            return True
    return False


def _build_blocking_items(
    missing_video: list[int],
    missing_audio: list[str],
    missing_bgm: bool,
    failed_reviews: list[dict],
    edit_risk: bool,
) -> list[dict]:
    blocking = []
    if missing_video:
        blocking.append({
            "code": "missing_video",
            "label": f"Missing video for shots: {', '.join(str(x) for x in missing_video[:12])}",
        })
    if missing_audio:
        blocking.append({"code": "missing_audio", "label": "Voiceover/TTS is expected but no audio asset is attached."})
    if missing_bgm:
        blocking.append({"code": "missing_bgm", "label": "BGM is not selected."})
    if failed_reviews:
        blocking.append({"code": "review_not_passed", "label": "Image/video review has failed or regenerate statuses."})
    if edit_risk:
        blocking.append({"code": "edit_plan_incomplete", "label": "Final edit plan is missing or incomplete."})
    return blocking


def _check(code: str, passed: bool, detail: str) -> dict:
    return {"code": code, "passed": bool(passed), "detail": detail}
