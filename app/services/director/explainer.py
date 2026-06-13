from __future__ import annotations

from typing import Any

from .memory import get_project_memory
from .presets import get_director_presets
from .reasoning import TASK_LABELS, diagnose_and_recommend, recommend_mode
from .trace import load_trace_records
from app.services.prompt.engine import get_library_filters, resolve_filtered_library_ids


def _format_score_map(scores: dict[str, int] | None) -> str:
    scores = scores or {}
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    parts = []
    for key, value in ordered:
        label = TASK_LABELS.get(key, key)
        parts.append(f"{label}:{value}")
    return " / ".join(parts)


def _format_weight_map(weights: dict[str, float] | None) -> str:
    weights = weights or {}
    ordered = sorted(weights.items(), key=lambda item: (-float(item[1] or 0.0), item[0]))
    parts = []
    for key, value in ordered:
        label = TASK_LABELS.get(key, key)
        parts.append(f"{label}:{round(float(value or 0.0), 2)}%")
    return " / ".join(parts)


def _find_preset_meta(preset_key: str) -> dict[str, Any] | None:
    normalized = str(preset_key or "").strip()
    if not normalized:
        return None
    for item in get_director_presets().get("presets", []):
        if str(item.get("key", "")).strip() == normalized:
            return item
    return None


def _find_filter_count(filter_mode: str, filter_value: str) -> tuple[int, int]:
    filters = get_library_filters()
    total = int(filters.get("total", 0) or 0)
    ids = resolve_filtered_library_ids(filter_mode, filter_value)
    if ids is None:
        return total, total
    return len(ids), total


def _build_memory_summary(project_id: str) -> dict[str, Any]:
    normalized = str(project_id or "").strip()
    if not normalized:
        return {
            "enabled": False,
            "explanation": "\u672a\u4f20\u5165 project_id\uff0c\u672c\u6b21\u89e3\u91ca\u4e0d\u6302\u8f7d\u9879\u76ee\u8bb0\u5fc6\u3002",
        }

    memory = get_project_memory(normalized)
    project_profile = memory.get("project_profile", {}).get("profile", {})
    characters = memory.get("character_profiles", {}).get("characters", {})
    reworks = memory.get("recent_reworks", [])
    has_memory = bool(project_profile or characters or reworks)
    if not has_memory:
        return {
            "enabled": True,
            "project_id": normalized,
            "project_profile_fields": 0,
            "character_count": 0,
            "recent_rework_count": 0,
            "explanation": "\u5df2\u5173\u8054\u9879\u76ee\uff0c\u4f46\u5f53\u524d\u8fd8\u6ca1\u6709\u6c89\u6dc0\u9879\u76ee/\u89d2\u8272/\u8fd4\u5de5\u8bb0\u5fc6\u3002",
        }
    return {
        "enabled": True,
        "project_id": normalized,
        "project_profile_fields": len(project_profile),
        "character_count": len(characters),
        "recent_rework_count": len(reworks),
        "explanation": f"\u5df2\u52a0\u8f7d\u9879\u76ee\u8bb0\u5fc6\uff1a\u9879\u76ee\u5b57\u6bb5 {len(project_profile)} \u9879\uff0c\u89d2\u8272 {len(characters)} \u4e2a\uff0c\u8fd4\u5de5\u8bb0\u5f55 {len(reworks)} \u6761\u3002",
    }


def _build_execution_pack(
    *,
    query: str,
    diagnosis: dict[str, Any] | None,
    recommendation: dict[str, Any],
    memory_summary: dict[str, Any],
) -> dict[str, Any]:
    topology = recommendation.get("knowledge_topology", {}) or {}
    detected_genres = [
        str(item.get("name", "")).strip()
        for item in topology.get("detected_genres", [])
        if str(item.get("name", "")).strip()
    ]
    supporting_tasks = recommendation.get("supporting_tasks", []) or []
    secondary_tool_orders = recommendation.get("secondary_tool_orders", []) or []
    evolution_feedback = recommendation.get("evolution_feedback", {}) or {}
    task_type = str(recommendation.get("task_type", "")).strip().lower()
    execution_mode = str(recommendation.get("execution_mode", "single_focus") or "single_focus")
    primary_steps = [
        {
            "step": 1,
            "action": "lock_task",
            "instruction": f"\u4e3b\u95ee\u9898\u6309 {recommendation.get('task_label', task_type)} \u6267\u884c\uff0c\u4e0d\u8981\u5148\u53d1\u6563\u5230\u5176\u4ed6\u65b9\u5411\u3002",
        },
        {
            "step": 2,
            "action": "load_preset",
            "instruction": f"\u9884\u8bbe\u4f7f\u7528 {recommendation.get('preset_key', '')}\uff0c\u8c03\u5e93\u8303\u56f4 {recommendation.get('filter_mode', '')}={recommendation.get('filter_value', '')}\u3002",
        },
        {
            "step": 3,
            "action": "run_tool_chain",
            "instruction": " -> ".join(recommendation.get("tool_order", []) or []) or "\u5bfc\u6f14\u8bca\u65ad -> \u8c03\u5e93 -> \u751f\u6210",
        },
    ]
    if detected_genres:
        primary_steps.append({
            "step": len(primary_steps) + 1,
            "action": "apply_genre_topology",
            "instruction": f"\u9898\u6750\u6309 {' / '.join(detected_genres[:2])} \u6267\u884c\uff0c\u4f18\u5148\u5e26\u5165\u51b2\u7a81\u6bcd\u9898\u3001\u5173\u7cfb\u6a21\u5f0f\u3001\u60c5\u7eea\u5f27\u7ebf\u548c\u955c\u5934\u504f\u597d\u3002",
        })
    if supporting_tasks:
        primary_steps.append({
            "step": len(primary_steps) + 1,
            "action": "attach_secondary_tasks",
            "instruction": "\u6b21\u7ea7\u95ee\u9898\u540c\u6b65\u6302\u8f7d\uff1a" + " / ".join(
                f"{item.get('task_label', item.get('task_type', ''))} {item.get('weight', 0)}%"
                for item in supporting_tasks[:3]
            ),
        })
    if evolution_feedback.get("enabled"):
        if evolution_feedback.get("promoted_preset_key"):
            evolution_instruction = f"\u76f8\u4f3c\u6210\u529f\u6848\u4f8b\u63d0\u793a\u4f18\u5148\u53c2\u8003 {evolution_feedback.get('promoted_preset_key', '')}\u3002"
        elif evolution_feedback.get("avoid_preset_keys"):
            evolution_instruction = f"\u76f8\u4f3c\u5931\u8d25\u6848\u4f8b\u63d0\u793a\u907f\u514d\u590d\u7528 {' / '.join(evolution_feedback.get('avoid_preset_keys', [])[:2])}\u3002"
        else:
            evolution_instruction = "\u5b58\u5728\u5386\u53f2\u53cd\u54fa\u4fe1\u53f7\uff0c\u6267\u884c\u65f6\u53c2\u8003\u5386\u53f2\u6848\u4f8b\u3002"
        primary_steps.append({
            "step": len(primary_steps) + 1,
            "action": "apply_evolution_feedback",
            "instruction": evolution_instruction,
        })
    if secondary_tool_orders:
        primary_steps.append({
            "step": len(primary_steps) + 1,
            "action": "coordinate_secondary_chains",
            "instruction": "；".join(
                f"{item.get('task_label', item.get('task_type', ''))}: {' -> '.join(item.get('tool_order', [])[:4])}"
                for item in secondary_tool_orders[:2]
            ),
        })

    execution_constraints = []
    if diagnosis and diagnosis.get("manual_override_recommended"):
        execution_constraints.append("\u5f53\u524d\u4e3a\u6df7\u5408\u95ee\u9898\uff0c\u5982\u679c\u6267\u884c\u7ed3\u679c\u53d1\u6563\uff0c\u5148\u9501\u4e3b\u95ee\u9898\u518d\u8fdb\u4e00\u6b65\u751f\u6210\u3002")
    if topology.get("library_gap_notes"):
        execution_constraints.extend(topology.get("library_gap_notes", [])[:2])
    if not memory_summary.get("enabled"):
        execution_constraints.append("\u672a\u6302\u8f7d\u9879\u76ee\u8bb0\u5fc6\uff0c\u672c\u8f6e\u4e0d\u8981\u81ea\u884c\u5047\u8bbe\u957f\u671f\u98ce\u683c\u9501\u5b9a\u3002")

    execution_checklist = [
        f"\u4e3b\u4efb\u52a1\u4fdd\u6301\u5728 {recommendation.get('task_label', task_type)} \u8f68\u9053\u5185\u6267\u884c",
        f"\u9884\u8bbe\u4e0e\u8c03\u5e93\u4f7f\u7528 {recommendation.get('preset_key', '')} / {recommendation.get('filter_mode', '')}={recommendation.get('filter_value', '')}",
        f"\u5de5\u5177\u987a\u5e8f\u6309 {' -> '.join(recommendation.get('tool_order', [])[:4] or ['导演诊断', '调库', '生成'])}",
    ]
    if detected_genres:
        execution_checklist.append(f"\u9898\u6750\u952e\u4f4d\u4fdd\u7559 {' / '.join(detected_genres[:2])}")
    if supporting_tasks:
        execution_checklist.append("\u6b21\u7ea7\u4efb\u52a1\u540c\u6b65\u68c0\u67e5\uff1a" + " / ".join(item.get("task_label", item.get("task_type", "")) for item in supporting_tasks[:3]))

    stop_conditions = [
        "\u5982\u679c\u751f\u6210\u7ed3\u679c\u8131\u79bb\u4e3b\u95ee\u9898\uff0c\u7acb\u5373\u56de\u5230\u4e3b\u9884\u8bbe\u91cd\u65b0\u6267\u884c",
        "\u5982\u679c\u6b21\u7ea7\u4efb\u52a1\u53cd\u5ba2\u4e3a\u4e3b\uff0c\u964d\u4f4e\u6b21\u7ea7\u94fe\u8def\u6743\u91cd",
    ]
    if topology.get("library_gap_notes"):
        stop_conditions.append("\u9898\u6750\u4e13\u5c5e\u5e93\u4e0d\u8db3\u65f6\uff0c\u4e0d\u8981\u865a\u6784\u65b0\u5e93\u6761\u76ee\uff0c\u5148\u7528\u6bcd\u7ed3\u6784\u7ea6\u675f\u6267\u884c")

    claude_handoff_prompt = "\n".join([
        f"[任务] {recommendation.get('task_label', task_type)}",
        f"[执行模式] {execution_mode}",
        f"[预设] {recommendation.get('preset_key', '')}",
        f"[调库] {recommendation.get('filter_mode', '')}={recommendation.get('filter_value', '')}",
        f"[题材] {' / '.join(detected_genres[:2]) if detected_genres else '未显式识别'}",
        f"[主链] {' -> '.join(recommendation.get('tool_order', []) or [])}",
        f"[约束] {'；'.join(execution_constraints[:3]) if execution_constraints else '先按主任务执行'}",
    ])

    return {
        "version": "1.0",
        "query": query,
        "task_type": recommendation.get("task_type", ""),
        "task_label": recommendation.get("task_label", ""),
        "execution_mode": execution_mode,
        "preset_key": recommendation.get("preset_key", ""),
        "filter_mode": recommendation.get("filter_mode", ""),
        "filter_value": recommendation.get("filter_value", ""),
        "detected_genres": detected_genres,
        "topology_focus": {
            "conflict_motifs": topology.get("conflict_motifs", []) or [],
            "relationship_patterns": topology.get("relationship_patterns", []) or [],
            "emotion_arcs": topology.get("emotion_arcs", []) or [],
            "shot_preferences": topology.get("shot_preferences", []) or [],
        },
        "supporting_tasks": supporting_tasks,
        "secondary_tool_orders": secondary_tool_orders,
        "tool_order": recommendation.get("tool_order", []) or [],
        "primary_steps": primary_steps,
        "execution_checklist": execution_checklist,
        "execution_constraints": execution_constraints,
        "stop_conditions": stop_conditions,
        "claude_handoff_prompt": claude_handoff_prompt,
        "success_signal": {
            "target_preset": recommendation.get("preset_key", ""),
            "must_keep": [
                recommendation.get("task_label", ""),
                *detected_genres[:2],
            ],
        },
    }


def explain_decision(
    query: str,
    *,
    project_id: str = "",
    style_hint: str = "",
    context_hint: str = "",
    task_type: str = "",
    manual_task_type: str = "",
    preset_key: str = "",
    filter_mode: str = "",
    filter_value: str = "",
) -> dict[str, Any]:
    if str(task_type or "").strip():
        diagnosis = None
        recommendation = recommend_mode(
            task_type=task_type,
            project_id=project_id,
            query=query,
            style_hint=style_hint,
            context_hint=context_hint,
            manual_preset_key=preset_key,
            manual_filter_mode=filter_mode,
            manual_filter_value=filter_value,
        )
    else:
        package = diagnose_and_recommend(
            query,
            project_id=project_id,
            style_hint=style_hint,
            context_hint=context_hint,
            manual_task_type=manual_task_type,
            manual_preset_key=preset_key,
            manual_filter_mode=filter_mode,
            manual_filter_value=filter_value,
        )
        diagnosis = package.get("diagnosis")
        recommendation = package.get("recommendation", {})

    preset_meta = _find_preset_meta(recommendation.get("preset_key", ""))
    matched_count, total_count = _find_filter_count(
        recommendation.get("filter_mode", ""),
        recommendation.get("filter_value", ""),
    )
    memory_summary = _build_memory_summary(project_id)

    if diagnosis is None:
        diagnosis_explanation = "\u5df2\u76f4\u63a5\u6307\u5b9a\u4efb\u52a1\u7c7b\u578b\uff0c\u8df3\u8fc7\u81ea\u52a8\u8bca\u65ad\uff0c\u76f4\u63a5\u8fdb\u5165\u63a8\u8350\u9636\u6bb5\u3002"
    else:
        reason_tags = diagnosis.get("reason_tags", []) or []
        reason_text = "\u3001".join(reason_tags) if reason_tags else "\u672a\u547d\u4e2d\u5f3a\u89c4\u5219\uff0c\u8d70\u4fdd\u5e95\u5224\u65ad"
        diagnosis_explanation = (
            f"\u5f53\u524d\u8bf7\u6c42\u88ab\u5f52\u4e3a\u300c{diagnosis.get('task_label', '')}\u300d\uff0c"
            f"\u7f6e\u4fe1\u5ea6 {diagnosis.get('confidence', '')}\uff1b\u89e6\u53d1\u4f9d\u636e\uff1a{reason_text}\u3002"
        )
        if diagnosis.get("fallback_note"):
            diagnosis_explanation += f" {diagnosis['fallback_note']}"
        score_text = _format_score_map(diagnosis.get("scores"))
        if score_text:
            diagnosis_explanation += f" \u5206\u503c\u5206\u5e03\uff1a{score_text}\u3002"
        weight_text = _format_weight_map(diagnosis.get("weight_map"))
        if weight_text:
            diagnosis_explanation += f" \u6df7\u5408\u6743\u91cd\uff1a{weight_text}\u3002"

    if preset_meta:
        recommended_stage = "/".join(
            str(item).strip()
            for item in (preset_meta.get("recommended_stage", []) or [])
            if str(item).strip()
        )
        stage_suffix = f"\uff1b\u9002\u7528\u9636\u6bb5 {recommended_stage}" if recommended_stage else ""
        preset_explanation = (
            f"\u5f53\u524d\u63a8\u8350\u9884\u8bbe\u4e3a {recommendation.get('preset_key', '')}{stage_suffix}\uff1b"
            f"\u63a8\u8350\u539f\u56e0\uff1a{recommendation.get('recommendation_reason', '')}"
        )
    else:
        preset_explanation = (
            f"\u5f53\u524d\u76f4\u63a5\u4f7f\u7528\u7b5b\u9009\u6761\u4ef6\u6216\u9ed8\u8ba4\u9884\u8bbe\uff0c\u63a8\u8350\u539f\u56e0\uff1a{recommendation.get('recommendation_reason', '')}"
        )

    topology = recommendation.get("knowledge_topology", {}) or {}
    detected_genres = [str(item.get("name", "")).strip() for item in topology.get("detected_genres", []) if str(item.get("name", "")).strip()]
    if detected_genres:
        preset_explanation += f" \u5df2\u8bc6\u522b\u9898\u6750\uff1a{' / '.join(detected_genres[:2])}\u3002"

    if recommendation.get("filter_mode") and recommendation.get("filter_value"):
        library_explanation = (
            f"\u672c\u6b21\u8c03\u5e93\u8303\u56f4\u9501\u5b9a\u4e3a {recommendation.get('filter_mode', '')}="
            f"{recommendation.get('filter_value', '')}\uff0c\u9884\u8ba1\u547d\u4e2d {matched_count}/{total_count} \u4e2a\u5e93\u6761\u76ee\u3002"
        )
    else:
        library_explanation = (
            f"\u672c\u6b21\u672a\u9650\u5236\u5e93\u8303\u56f4\uff0c\u5c06\u5728\u603b\u5e93\u7cfb\u7edf\u5185\u5168\u91cf\u68c0\u7d22\uff0c\u5171 {matched_count} \u4e2a\u53ef\u7528\u6761\u76ee\u3002"
        )
    if topology.get("library_gap_notes"):
        library_explanation += f" \u9898\u6750\u5c42\u63d0\u9192\uff1a{'；'.join(topology.get('library_gap_notes', [])[:2])}\u3002"

    tool_order = recommendation.get("tool_order", []) or []
    if tool_order:
        tool_order_explanation = (
            "\u6267\u884c\u987a\u5e8f\u4e3a\uff1a" + " -> ".join(tool_order) +
            "\u3002\u8fd9\u6837\u80fd\u5148\u7a33\u4f4f\u4e3b\u95ee\u9898\uff0c\u518d\u628a\u7ed3\u679c\u9001\u5165\u540e\u7eed\u751f\u6210\u94fe\u8def\u3002"
        )
    else:
        tool_order_explanation = "\u5f53\u524d\u6ca1\u6709\u9644\u5e26\u5de5\u5177\u987a\u5e8f\uff0c\u5efa\u8bae\u6309\u5bfc\u6f14\u8bca\u65ad -> \u8c03\u5e93 -> \u751f\u6210\u7684\u4e3b\u94fe\u6267\u884c\u3002"

    evolution_feedback = recommendation.get("evolution_feedback", {}) or {}
    if evolution_feedback.get("enabled"):
        if evolution_feedback.get("promoted_preset_key"):
            preset_explanation += f" \u8fdb\u5316\u53cd\u54fa\u63a8\u8350\u4f18\u5148\u53c2\u8003 {evolution_feedback.get('promoted_preset_key', '')}\u3002"
        elif evolution_feedback.get("avoid_preset_keys"):
            preset_explanation += f" \u8fdb\u5316\u53cd\u54fa\u63d0\u793a\u907f\u514d\u590d\u7528 {' / '.join(evolution_feedback.get('avoid_preset_keys', [])[:2])}\u3002"

    execution_pack = _build_execution_pack(
        query=query,
        diagnosis=diagnosis,
        recommendation=recommendation,
        memory_summary=memory_summary,
    )

    return {
        "query": query,
        "project_id": str(project_id or "").strip(),
        "diagnosis": diagnosis,
        "recommendation": recommendation,
        "memory_summary": memory_summary,
        "diagnosis_explanation": diagnosis_explanation,
        "preset_explanation": preset_explanation,
        "library_explanation": library_explanation,
        "tool_order_explanation": tool_order_explanation,
        "execution_pack": execution_pack,
    }


def explain_run(project_id: str = "", *, event_type: str = "", limit: int = 20) -> dict[str, Any]:
    records = load_trace_records(project_id, limit=limit, event_type=event_type)
    if not records:
        return {
            "project_id": str(project_id or "").strip(),
            "event_type": str(event_type or "").strip(),
            "records": [],
            "summary": {
                "total_records": 0,
                "message": "\u672a\u627e\u5230\u53ef\u89e3\u91ca\u7684\u5bfc\u6f14\u8fd0\u884c\u65e5\u5fd7\u3002",
            },
        }

    latest = records[-1]
    event_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    preset_keys: list[str] = []
    families: list[str] = []
    clusters: list[str] = []
    for item in records:
        event = str(item.get("event_type", "")).strip()
        status = str(item.get("status", "")).strip()
        if event:
            event_counts[event] = event_counts.get(event, 0) + 1
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        preset = str(item.get("preset_key", "")).strip()
        if preset:
            preset_keys.append(preset)
        families.extend(item.get("matched_library_families", []) or [])
        clusters.extend(item.get("matched_library_clusters", []) or [])

    explanation = (
        f"\u6700\u8fd1 {len(records)} \u6761\u5bfc\u6f14\u65e5\u5fd7\u4e2d\uff0c\u6700\u65b0\u4e8b\u4ef6\u662f {latest.get('event_type', '')}\uff0c"
        f"\u72b6\u6001\u4e3a {latest.get('status', '')}\u3002"
    )
    if latest.get("preset_key"):
        explanation += f" \u6700\u8fd1\u94fe\u8def\u4e3b\u8981\u4f7f\u7528\u9884\u8bbe {latest.get('preset_key', '')}\u3002"
    if families:
        explanation += f" \u547d\u4e2d\u7684\u5e93\u65cf\u4ee5 {'?'.join(sorted(set(families))[:4])} \u4e3a\u4e3b\u3002"

    summary = {
        "total_records": len(records),
        "latest_event_type": latest.get("event_type", ""),
        "latest_status": latest.get("status", ""),
        "latest_message": latest.get("message", ""),
        "event_counts": event_counts,
        "status_counts": status_counts,
        "preset_keys": sorted(set(preset_keys)),
        "matched_library_families": sorted(set(families)),
        "matched_library_clusters": sorted(set(clusters)),
        "explanation": explanation,
    }
    return {
        "project_id": str(project_id or "").strip(),
        "event_type": str(event_type or "").strip(),
        "records": records,
        "summary": summary,
    }
