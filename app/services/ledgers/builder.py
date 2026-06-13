"""Top-level ledger builder — merges shots, dispatches to each ledger module."""

from __future__ import annotations

from typing import Any

from app.services.ledgers.models import ShotAnalysis
from app.services.ledgers.shot_analysis import analyze_shots
from app.services.ledgers.creative import build_creative_ledger
from app.services.ledgers.continuity import build_continuity_ledger
from app.services.ledgers.cost_risk import build_cost_risk_ledger
from app.services.ledgers.quality import build_quality_ledger


def build_director_ledgers(
    *,
    project_doc: str,
    episodes_doc: str,
    scene_doc: str,
    workspace_shots: list[Any],
    operational_shots: list[dict[str, Any]],
    final_edit_plan: dict[str, Any] | None,
    visual_budget: dict[str, Any],
    production_ledger: dict[str, Any],
) -> dict[str, Any]:
    """Build all four director ledgers in one pass.

    Key improvement over the original: shots are merged and analyzed
    **once**, then each ledger reads from the shared ``ShotAnalysis``.
    """
    # Merge workspace and operational shots (only dicts, in order)
    merged = _merge_shots(workspace_shots, operational_shots)
    fe_plan = final_edit_plan if isinstance(final_edit_plan, dict) else {}

    # Single-pass analysis
    analysis = analyze_shots(merged)

    # Build all four ledgers (no re-iteration over shots)
    creative = build_creative_ledger(
        analysis=analysis,
        has_final_edit=bool(fe_plan.get("clips")),
        has_recipe=bool(fe_plan.get("recipe_id") or (fe_plan.get("settings") or {}).get("recipe_id")),
    )
    continuity = build_continuity_ledger(project_doc, episodes_doc, scene_doc, analysis, production_ledger)
    cost = build_cost_risk_ledger(analysis, fe_plan, visual_budget, production_ledger)
    quality = build_quality_ledger(analysis, fe_plan)

    return {
        "creative_technique_ledger": creative.model_dump(),
        "story_continuity_ledger": continuity.model_dump(),
        "cost_risk_ledger": cost.model_dump(),
        "final_quality_ledger": quality.model_dump(),
    }


def _merge_shots(workspace_shots: list[Any], operational_shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge workspace and operational shots by index.

    Operational shots override workspace shots at matching indices.
    """
    by_index: dict[int, dict[str, Any]] = {}
    overflow = 100000
    for raw in workspace_shots:
        if not isinstance(raw, dict):
            continue
        idx = int(raw.get("shot_index", 0)) or overflow
        by_index[idx] = dict(raw)
        overflow += 1
    for raw in operational_shots:
        if not isinstance(raw, dict):
            continue
        idx = int(raw.get("shot_index", 0)) or overflow
        existing = by_index.get(idx, {})
        by_index[idx] = {**existing, **raw}
        overflow += 1
    return [by_index[k] for k in sorted(by_index)]
