"""Signal extractors — flatten ledger data for UI and risk feeds."""

from __future__ import annotations

from typing import Any

from app.core.types import safe_dict, safe_list


def director_ledger_signals(ledgers: dict[str, Any]) -> dict[str, Any]:
    """Extract flat signal dict from ledger result."""
    creative = safe_dict(ledgers.get("creative_technique_ledger"))
    continuity = safe_dict(ledgers.get("story_continuity_ledger"))
    cost = safe_dict(ledgers.get("cost_risk_ledger"))
    quality = safe_dict(ledgers.get("final_quality_ledger"))
    estimated = safe_dict(cost.get("estimated_operations"))
    return {
        "creative_applied_technique_count": int(creative.get("applied_count", 0)),
        "creative_candidate_technique_count": int(creative.get("candidate_count", 0)),
        "creative_technique_total": int(creative.get("technique_total", 0)),
        "creative_missing_stage_count": sum(
            len(v) for v in safe_dict(creative.get("missing_by_stage")).values() if isinstance(v, list)
        ),
        "continuity_gap_count": len(safe_list(continuity.get("continuity_gaps"))),
        "continuity_handoff_question_count": len(safe_list(continuity.get("handoff_questions"))),
        "cost_risk_level": str(cost.get("risk_level", "ok")),
        "remaining_image_operations": int(estimated.get("image", 0)),
        "remaining_video_operations": int(estimated.get("video", 0)),
        "remaining_tts_operations": int(estimated.get("tts", 0)),
        "remaining_final_edit_operations": int(estimated.get("final_edit", 0)),
        "final_quality_ready_score": int(quality.get("ready_score", 0)),
        "final_quality_blocking_count": len(safe_list(quality.get("blocking_items"))),
    }


def director_ledger_risks(ledgers: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract risk items from all ledgers."""
    risks: list[dict[str, Any]] = []
    continuity = safe_dict(ledgers.get("story_continuity_ledger"))
    cost = safe_dict(ledgers.get("cost_risk_ledger"))
    quality = safe_dict(ledgers.get("final_quality_ledger"))

    continuity_gaps = safe_list(continuity.get("continuity_gaps"))
    handoff_gaps = [
        g for g in continuity_gaps
        if isinstance(g, dict) and g.get("code") in {"scene_handoff_check", "scene_count_mismatch"}
    ]
    if handoff_gaps:
        risks.append({
            "code": "story_handoff_gap",
            "severity": "info",
            "title": "Scene handoff needs confirmation",
            "reason": str(handoff_gaps[0].get("reason", "Confirm previous/current/next scene continuity before larger batches.")),
        })

    risk_level = str(cost.get("risk_level", "ok"))
    if risk_level in {"watch", "high"}:
        risks.append({
            "code": "cost_risk_ledger",
            "severity": "warning" if risk_level == "high" else "info",
            "title": "Remaining operations need guardrails",
            "reason": "; ".join(safe_list(cost.get("guardrail_actions"))[:2]) or "Reuse assets and keep generation batches capped.",
        })

    blocking = safe_list(quality.get("blocking_items"))
    if blocking and (quality.get("has_final_edit_plan") or quality.get("produced_video_count")):
        risks.append({
            "code": "final_quality_blockers",
            "severity": "warning",
            "title": "Final cut is not ready",
            "reason": str(blocking[0].get("label", str(blocking[0]))),
        })

    return risks


def director_ledger_missing_items(ledgers: dict[str, Any]) -> list[dict[str, str]]:
    """Extract missing-item flags from all ledgers."""
    missing: list[dict[str, str]] = []
    creative = safe_dict(ledgers.get("creative_technique_ledger"))
    quality = safe_dict(ledgers.get("final_quality_ledger"))

    if safe_dict(creative.get("missing_by_stage")):
        missing.append({"code": "creative_technique_coverage", "label": "Creative technique ledger has stage coverage gaps."})

    if safe_list(quality.get("blocking_items")) and (quality.get("has_final_edit_plan") or quality.get("produced_video_count")):
        missing.append({"code": "final_quality_blockers", "label": "Final quality ledger has blocking items before export."})

    return missing
