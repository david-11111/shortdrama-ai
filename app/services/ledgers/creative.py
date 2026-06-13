"""Creative technique ledger — tracks which production techniques are applied."""

from __future__ import annotations

from app.services.ledgers.models import STYLE_BASE_SCORE, STYLE_LOCK_WEIGHT, STYLE_REVIEW_WEIGHT, CreativeLedger, ShotAnalysis
from app.services.ledgers.shot_analysis import _as_strings


_STAGES: dict[str, set[str]] = {
    "script_understanding": {"matched_libraries", "content_humanizer"},
    "preflight_review": {"director_preflight", "prompt_revision"},
    "keyframe_generation": {"visual_quality_rules", "image_review"},
    "video_generation": {"visual_quality_rules"},
    "video_review": {"video_review"},
    "final_edit": {"voice_delivery_rules", "final_cut_recipes", "content_humanizer"},
}

_CLOSE_UP_TOKENS = ("特写", "close-up", "close up", "近景", "reaction")
_WIDE_TOKENS = ("全景", "wide", "establishing", "远景")
_MOTION_TOKENS = ("推进", "push", "dolly", "跟拍", "pan", "横移")


def build_creative_ledger(analysis: ShotAnalysis, has_final_edit: bool, has_recipe: bool) -> CreativeLedger:
    """Build the creative technique coverage ledger from a single-pass analysis."""
    applied: dict[str, list[str]] = {stage: [] for stage in _STAGES}
    candidate: dict[str, list[str]] = {stage: [] for stage in _STAGES}
    per_shot_public: list[dict] = []

    for item in analysis.per_shot:
        shot_applied = _shot_applied(item)
        shot_candidate = _shot_candidate(item)
        has_passed_review = item.image_review_passed or item.video_review_passed

        for stage, names in _STAGES.items():
            for name in sorted(names & shot_applied):
                _append_unique(applied[stage], name)
            for name in sorted(names & shot_candidate):
                _append_unique(candidate[stage], name)

        per_shot_public.append({
            "shot_index": item.shot_index,
            "matched_libraries": item.matched_libraries,
            "has_prompt_revision": item.has_prompt_revision,
            "director_preflight_status": item.director_preflight_status,
            "image_review_status": item.image_review_status,
            "video_review_status": item.video_review_status,
            "rules_applied": sorted(shot_applied),
            "rules_candidate": sorted(shot_candidate),
            "rules_missing": sorted(shot_candidate - shot_applied),
            "applied": item.matched_libraries if has_passed_review else [],
            "candidate": item.matched_libraries if not has_passed_review else [],
        })

    # Handle final edit
    if has_final_edit:
        _append_unique(candidate["final_edit"], "final_cut_recipes")
        if has_recipe:
            _append_unique(applied["final_edit"], "final_cut_recipes")

    missing_by_stage = {
        stage: [name for name in names if name in candidate[stage] and name not in applied[stage]]
        for stage, names in _STAGES.items()
    }
    missing_by_stage = {s: v for s, v in missing_by_stage.items() if v}

    # Compute library stats
    applied_libs = sorted(
        name for name, item in analysis.library_counts.items()
        if int(item.get("reviewed_count", 0)) > 0
    )
    candidate_libs = sorted(
        name for name, item in analysis.library_counts.items()
        if int(item.get("reviewed_count", 0)) <= 0
    )

    # Compute aggregated stats
    technique_total = len(analysis.library_counts)
    applied_count = len(applied_libs)
    candidate_count = len(candidate_libs)
    coverage_pct = int(round(100 * applied_count / max(technique_total, 1))) if technique_total else 0
    style_score = _style_consistency_score(analysis)
    missing_count = sum(len(v) for v in missing_by_stage.values())
    anchor_count = _reusable_anchor_count(analysis)

    # Pad per_shot if first index is 1
    first_index = min((p["shot_index"] for p in per_shot_public), default=0)
    if first_index == 1:
        per_shot_public = [_padding_item()] + per_shot_public

    return CreativeLedger(
        applied=applied,
        candidate=candidate,
        missing_by_stage=missing_by_stage,
        per_shot=per_shot_public,
        applied_count=applied_count,
        candidate_count=candidate_count,
        technique_total=technique_total,
        technique_coverage=coverage_pct,
        technique_coverage_label=f"{applied_count}/{technique_total} 已落地" if technique_total else "暂无技巧命中",
        style_consistency_score=style_score,
        style_consistency_label=f"{style_score}分",
        shot_strategy_label=_shot_strategy_label(analysis),
        reusable_anchor_count=anchor_count,
        reusable_anchor_label=f"{anchor_count} 个",
        next_action_label=_creative_next_action(missing_count, candidate_count),
        risk_label="技巧未覆盖执行层" if missing_count else "低",
        summary={
            "shot_count": analysis.total,
            "applied_count": sum(len(v) for v in applied.values()),
            "candidate_count": sum(len(v) for v in candidate.values()),
            "missing_count": missing_count,
            "matched_library_shot_count": sum(1 for p in per_shot_public if p["matched_libraries"]),
            "prompt_revision_count": sum(1 for p in per_shot_public if p["has_prompt_revision"]),
            "preflight_count": sum(1 for p in per_shot_public if p["director_preflight_status"]),
            "image_review_count": sum(1 for p in per_shot_public if p["image_review_status"]),
            "video_review_count": sum(1 for p in per_shot_public if p["video_review_status"]),
        },
    )


def _shot_applied(item) -> set[str]:
    applied: set[str] = set()
    if item.matched_libraries:
        applied.add("matched_libraries")
    if item.has_prompt_revision:
        applied.add("prompt_revision")
    if item.has_preflight:
        applied.add("director_preflight")
    if item.image_review_status:
        applied.add("image_review")
    if item.video_review_status:
        applied.add("video_review")
    if item.has_visual_quality_rules:
        applied.add("visual_quality_rules")
    if item.has_voice_rules:
        applied.add("voice_delivery_rules")
    if item.has_humanizer_marker:
        applied.add("content_humanizer")
    return applied


def _shot_candidate(item) -> set[str]:
    candidate = {"director_preflight"}
    if item.prompt_text:
        candidate.update({"matched_libraries", "prompt_revision", "content_humanizer", "visual_quality_rules"})
    if item.has_image or item.image_review_status:
        candidate.add("image_review")
        candidate.add("video_review")
    if item.has_video or item.video_review_status:
        candidate.add("video_review")
    if item.needs_tts or any(w in item.prompt_text.lower() for w in ("dialogue", "voiceover", "旁白", "对白", "台词")):
        candidate.add("voice_delivery_rules")
    return candidate


def _style_consistency_score(analysis: ShotAnalysis) -> int:
    if analysis.total == 0:
        return 0
    locked = analysis.has_style_refs_count
    reviewed = analysis.image_review_passed_count + analysis.video_review_passed_count
    return min(100, int(round(
        STYLE_BASE_SCORE + STYLE_LOCK_WEIGHT * locked / max(analysis.total, 1) +
        STYLE_REVIEW_WEIGHT * reviewed / max(analysis.total, 1)
    )))


def _shot_strategy_label(analysis: ShotAnalysis) -> str:
    text = " ".join(analysis.shots_with_text).lower()
    close_hits = sum(1 for t in _CLOSE_UP_TOKENS if t.lower() in text)
    wide_hits = sum(1 for t in _WIDE_TOKENS if t.lower() in text)
    motion_hits = sum(1 for t in _MOTION_TOKENS if t.lower() in text)

    if close_hits and wide_hits:
        return "特写+全景"
    if motion_hits:
        return "运镜优先"
    if close_hits:
        return "表演特写"
    return "待细化"


def _reusable_anchor_count(analysis: ShotAnalysis) -> int:
    """Count unique anchor references across all shots."""
    # This requires re-accessing raw shots — we skip recomputation here
    # since it's only called once per render cycle. We approximate from
    # the analysis data.
    seen: set[str] = set()
    for item in analysis.per_shot:
        if item.matched_libraries:
            seen.update(item.matched_libraries)
    return len(seen)


def _creative_next_action(missing_count: int, candidate_count: int) -> str:
    if missing_count:
        return "把候选技巧下沉到执行层"
    if candidate_count:
        return "验证候选技巧效果"
    return "继续复用已验证技巧"


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _padding_item() -> dict:
    return {
        "shot_index": 0,
        "is_index_padding": True,
        "matched_libraries": [],
        "has_prompt_revision": False,
        "director_preflight_status": "",
        "image_review_status": "",
        "video_review_status": "",
        "rules_applied": [],
        "rules_candidate": [],
        "rules_missing": [],
        "applied": [],
        "candidate": [],
    }
