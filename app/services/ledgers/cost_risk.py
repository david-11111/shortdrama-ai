"""Cost and risk estimation ledger — budget health, remaining ops, guardrails."""

from __future__ import annotations

from typing import Any

from app.services.ledgers.models import (
    COST_RISK_HIGH_THRESHOLD,
    COST_RISK_WATCH_THRESHOLD,
    HIGH_RISK_VIDEO_SHOT_THRESHOLD,
    MEDIUM_RISK_VIDEO_SHOT_THRESHOLD,
    IMAGE_BATCH_MAX,
    VIDEO_BATCH_MAX,
    CostRiskLedger,
    ShotAnalysis,
)


def build_cost_risk_ledger(
    analysis: ShotAnalysis,
    final_edit_plan: dict[str, Any] | None,
    visual_budget: dict[str, Any],
    production_ledger: dict[str, Any],
) -> CostRiskLedger:
    """Build the cost and risk estimation ledger.

    All counters are read from the single-pass ``ShotAnalysis`` —
    no repeated iterations.
    """
    fe_plan = final_edit_plan if isinstance(final_edit_plan, dict) else {}
    clips = fe_plan.get("clips") if isinstance(fe_plan.get("clips"), list) else []
    settings = fe_plan.get("settings") if isinstance(fe_plan.get("settings"), dict) else {}

    video_done = analysis.with_selected_video
    image_remaining = analysis.needs_image
    video_remaining = analysis.needs_video
    tts_remaining = analysis.needs_tts
    final_edit_remaining = 0 if clips and video_done and not video_remaining else 1 if video_done or clips else 0

    # Estimated operations
    estimated = {
        "image": image_remaining,
        "video": video_remaining,
        "tts": tts_remaining,
        "final_edit": final_edit_remaining,
        "seedream_images": int(visual_budget.get("estimated_seedream_images", image_remaining)),
        "remaining_seconds": int(production_ledger.get("remaining_seconds", 0)),
    }

    # Risk level (computed once)
    total_weight = image_remaining + video_remaining * 2 + tts_remaining + final_edit_remaining
    visual_budget_level = str(visual_budget.get("budget_level", "ok"))
    risk_level = (
        "high" if total_weight >= COST_RISK_HIGH_THRESHOLD or visual_budget_level == "over_budget"
        else "watch" if total_weight >= COST_RISK_WATCH_THRESHOLD or visual_budget_level == "watch"
        else "ok"
    )

    # Guardrail actions
    actions: list[str] = []
    if image_remaining:
        actions.append("Reuse locked references before generating remaining keyframes.")
    if video_remaining:
        actions.append("Cap video generation to small batches and retry only reviewed keyframes.")
    if tts_remaining:
        actions.append("Prepare voice delivery text once per scene and avoid repeated TTS trials.")
    if final_edit_remaining:
        actions.append("Build or refresh final edit plan from existing cuttable videos before export.")
    if settings.get("bgm_path"):
        actions.append("Keep existing BGM asset; do not regenerate audio unless it fails review.")
    if not actions:
        actions.append("No extra generation needed; preserve current assets for final review.")

    # High-risk shot count (computed from analysis — no repeat loop)
    high_risk_count = sum(
        1 for item in analysis.per_shot
        if item.director_preflight_status == "blocked" or item.video_review_status in {"regenerate", "failed", "fail", "rejected", "blocked"}
    )

    # Retry risk
    retry_risk = (
        "高" if video_remaining >= HIGH_RISK_VIDEO_SHOT_THRESHOLD
        else "中" if video_remaining >= MEDIUM_RISK_VIDEO_SHOT_THRESHOLD
        else "低"
    )

    return CostRiskLedger(
        risk_level=risk_level,
        estimated_operations=estimated,
        estimated_image_count=estimated["seedream_images"],
        pending_image_count=image_remaining,
        pending_video_count=video_remaining,
        pending_operation_count=image_remaining + video_remaining + tts_remaining + final_edit_remaining,
        budget_status_label={"high": "高风险", "watch": "需观察", "ok": "正常"}.get(risk_level, risk_level),
        estimated_cost_label=f"图 {estimated['seedream_images']} / 视频 {video_remaining} / 配音 {tts_remaining}",
        retry_risk_label=retry_risk,
        high_risk_shot_count=high_risk_count,
        high_risk_shot_label=f"{high_risk_count} 个",
        guardrail_actions=actions,
        next_action_label=actions[0] if actions else "保持当前计划",
        risk_label={"high": "成本和批量风险高", "watch": "需要分批控制", "ok": "低"}.get(risk_level, risk_level),
    )
