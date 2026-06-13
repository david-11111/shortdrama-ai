from __future__ import annotations

from typing import Any

from .explainer import explain_run
from .reasoning import recommend_mode
from .trace import load_trace_records

PROBLEM_LABELS = {
    "structure": "\u7ed3\u6784",
    "character": "\u4eba\u7269",
    "emotion": "\u60c5\u7eea",
    "stability": "\u7a33\u5b9a\u6027",
    "aesthetic": "\u5ba1\u7f8e",
    "shot": "\u955c\u5934",
}

DIMENSION_TO_TASK = {
    "structure": "structure",
    "character": "character",
    "emotion": "emotion",
    "stability": "shot",
    "aesthetic": "shot",
}

TASK_TO_FILTER_OVERRIDE = {
    "structure": {
        "preset_key": "core_engineering",
        "filter_mode": "library_family",
        "filter_value": "\u6838\u5fc3\u5de5\u7a0b\u5e93",
    },
    "character": {
        "preset_key": "character_soul",
        "filter_mode": "parent_library",
        "filter_value": "\u4eba\u7269\u7075\u9b42\u5e93\u7fa4",
    },
    "emotion": {
        "preset_key": "destiny_cinematic",
        "filter_mode": "parent_library",
        "filter_value": "\u4eba\u7269\u7075\u9b42\u5e93\u7fa4",
    },
    "shot": {
        "preset_key": "viral_shot",
        "filter_mode": "parent_library",
        "filter_value": "\u955c\u5934\u4e0e\u62cd\u6cd5\u5e93\u7fa4",
    },
}

TASK_STRATEGY_LIBRARY = {
    "structure": [
        "\u5148\u56de\u5230\u5267\u672c\u548c\u955c\u5934\u62c6\u89e3\u5c42\uff0c\u91cd\u5199\u5f00\u573a\u94a9\u5b50\u3001\u51b2\u7a81\u63a8\u8fdb\u548c\u7ed3\u5c3e\u529f\u80fd\u3002",
        "\u91cd\u5efa\u5206\u955c\u987a\u5e8f\uff0c\u786e\u4fdd\u6bcf\u4e2a\u955c\u5934\u90fd\u6709\u660e\u786e\u5185\u5bb9\u3001\u65f6\u957f\u548c\u5bf9\u5e94\u60c5\u8282\u4efb\u52a1\u3002",
        "\u82e5\u5f53\u524d\u7ed3\u6784\u5206\u4f4e\u4e8e 60\uff0c\u5efa\u8bae\u5148\u505c\u6389\u751f\u6210\u94fe\uff0c\u5148\u505a\u4e00\u8f6e\u811a\u672c\u6807\u6ce8\u548c\u7ed3\u6784\u8fd4\u4fee\u3002",
    ],
    "character": [
        "\u5148\u8865\u89d2\u8272\u8bb0\u5fc6\u548c\u4eba\u7269\u6807\u6ce8\uff0c\u8ba9\u6bcf\u4e2a\u89d2\u8272\u6709\u7a33\u5b9a\u7684\u4eba\u8bbe\u3001\u5173\u7cfb\u548c\u773c\u795e\u795e\u6001\u7ea6\u675f\u3002",
        "\u91cd\u505a\u4eba\u7269\u63d0\u793a\u5c42\uff0c\u628a\u773c\u795e\u3001\u5fae\u8868\u60c5\u3001\u547c\u5438\u548c\u4eea\u6001\u7ed1\u5230\u89d2\u8272\u540d\u4e0a\u3002",
        "\u82e5\u524d\u540e\u8f6e\u89d2\u8272\u72b6\u6001\u4e0d\u4e00\u81f4\uff0c\u5148\u9501\u5b9a\u6838\u5fc3\u4eba\u8bbe\u5b57\u6bb5\uff0c\u518d\u8fdb\u884c\u4e0b\u4e00\u8f6e\u751f\u6210\u3002",
    ],
    "emotion": [
        "\u5148\u589e\u5f3a\u60c5\u7eea\u8c03\u6027\u5b57\u6bb5\uff0c\u8865\u9f50\u955c\u5934\u7ea7\u7684 atmosphere/emotion/voiceover/subtext\u3002",
        "\u628a\u60c5\u7eea\u5199\u6210\u6e10\u53d8\u94fe\u8def\uff0c\u907f\u514d\u53ea\u5199\u7ed3\u679c\uff0c\u8981\u5199\u4ece\u5e73\u9759\u5230\u6ce2\u52a8\u7684\u8fc7\u7a0b\u3002",
        "\u82e5\u6c1b\u56f4\u59cb\u7ec8\u4e0d\u5bf9\uff0c\u5148\u6539\u9884\u8bbe\u5230\u60c5\u7eea\u5411\uff0c\u518d\u8fdb\u53c2\u8003\u56fe\u6216 Seedance \u751f\u6210\u3002",
    ],
    "shot": [
        "\u4f18\u5148\u56de\u770b\u751f\u6210\u94fe\u8def\u65e5\u5fd7\uff0c\u68c0\u67e5\u662f\u955c\u5934\u63d0\u793a\u4e0d\u7a33\u8fd8\u662f\u4ea7\u51fa\u6587\u4ef6\u4e0d\u5168\u3002",
        "\u91cd\u65b0\u7f29\u5c0f\u8c03\u5e93\u8303\u56f4\uff0c\u5148\u9501\u5b9a\u955c\u5934\u4e0e\u62cd\u6cd5\u5e93\u7fa4\uff0c\u907f\u514d\u5f15\u5165\u8fc7\u591a\u98ce\u683c\u5e72\u6270\u3002",
        "\u82e5\u751f\u6210\u6210\u529f\u4f46\u6210\u7247\u4e0d\u7a33\uff0c\u5efa\u8bae\u628a\u5904\u7406\u62c6\u6210\u201c\u51fa\u955c\u5934 -> \u51fa\u53c2\u8003\u56fe -> \u751f\u89c6\u9891 -> \u5408\u6210\u201d\u56db\u6b65\u68c0\u67e5\u3002",
    ],
    "aesthetic": [
        "\u4f18\u5148\u63d0\u9ad8\u955c\u5934\u8bed\u8a00\u5bc6\u5ea6\uff0c\u8865\u5145\u666f\u522b\u53d8\u5316\u3001\u6784\u56fe\u91cd\u5fc3\u548c\u8fd0\u955c\u76ee\u7684\uff0c\u907f\u514d\u5e73\u94fa\u76f4\u53d9\u3002",
        "\u8865\u5145\u5149\u5f71\u3001\u8272\u5f69\u3001\u6750\u8d28\u548c\u6c14\u6c1b\u7ea6\u675f\uff0c\u8ba9\u753b\u9762\u4ece\u201c\u80fd\u770b\u201d\u5347\u7ea7\u5230\u201c\u6709\u8d28\u611f\u201d\u3002",
        "\u5982\u679c\u5ba1\u7f8e\u5206\u504f\u4f4e\u4e14\u60c5\u7eea\u5206\u540c\u65f6\u504f\u4f4e\uff0c\u8bf7\u540c\u6b65\u5f3a\u5316\u60c5\u7eea\u6e10\u53d8\u3001\u7559\u767d\u548c\u53cd\u5e94\u955c\u5934\u3002",
    ],
}

FEEDBACK_HINTS = {
    "\u4eba\u7269": "character",
    "\u4eba\u8bbe": "character",
    "\u773c\u795e": "character",
    "\u60c5\u7eea": "emotion",
    "\u6c1b\u56f4": "emotion",
    "\u5bbf\u547d": "emotion",
    "\u955c\u5934": "shot",
    "\u62cd\u6cd5": "shot",
    "Seedance": "shot",
    "\u7ed3\u6784": "structure",
    "\u5267\u60c5": "structure",
    "\u8282\u594f": "structure",
}


def _normalize_problem_types(problem_types: list[str] | None) -> list[str]:
    ordered: list[str] = []
    for item in problem_types or []:
        value = str(item or "").strip().lower()
        if value and value not in ordered:
            ordered.append(value)
    return ordered


def _infer_problem_from_feedback(manual_feedback: str) -> list[str]:
    hits: list[str] = []
    text = str(manual_feedback or "")
    for term, task_type in FEEDBACK_HINTS.items():
        if term in text and task_type not in hits:
            hits.append(task_type)
    return hits


def _build_strategy_bundle(problem_types: list[str]) -> list[str]:
    strategies: list[str] = []
    for task_type in problem_types:
        for item in TASK_STRATEGY_LIBRARY.get(task_type, []):
            if item not in strategies:
                strategies.append(item)
    return strategies[:6]


def suggest_rework(
    *,
    evaluation_result: dict[str, Any] | None = None,
    project_id: str = "",
    output_name: str = "",
    manual_feedback: str = "",
) -> dict[str, Any]:
    evaluation_result = evaluation_result or {}
    normalized_project_id = str(project_id or evaluation_result.get("project_id", "")).strip()
    normalized_output_name = str(output_name or evaluation_result.get("output_name", "")).strip()

    problem_types = _normalize_problem_types(evaluation_result.get("problem_types", []))
    weakest_dimension = str(evaluation_result.get("weakest_dimension", "")).strip().lower()
    if weakest_dimension and weakest_dimension not in problem_types:
        problem_types.insert(0, weakest_dimension)

    inferred = _infer_problem_from_feedback(manual_feedback)
    for item in inferred:
        if item not in problem_types:
            problem_types.append(item)

    if not problem_types:
        problem_types = ["structure"]

    primary_problem = problem_types[0]
    primary_task = DIMENSION_TO_TASK.get(primary_problem, "structure")
    override = TASK_TO_FILTER_OVERRIDE.get(primary_task, TASK_TO_FILTER_OVERRIDE["structure"])
    recommendation = recommend_mode(
        task_type=primary_task,
        project_id=normalized_project_id,
        query=manual_feedback,
        manual_preset_key=override["preset_key"],
        manual_filter_mode=override["filter_mode"],
        manual_filter_value=override["filter_value"],
    )

    run_summary = explain_run(normalized_project_id, limit=20) if normalized_project_id else {
        "records": [],
        "summary": {"total_records": 0, "message": ""},
    }
    trace_records = load_trace_records(normalized_project_id, limit=20) if normalized_project_id else []
    latest_preset = ""
    latest_success_status = ""
    for item in reversed(trace_records):
        preset_key = str(item.get("preset_key", "")).strip()
        if preset_key and not latest_preset:
            latest_preset = preset_key
        status = str(item.get("status", "")).strip()
        if status and not latest_success_status:
            latest_success_status = status
        if latest_preset and latest_success_status:
            break

    strategy_bundle = _build_strategy_bundle(problem_types)
    review_notes = evaluation_result.get("review_notes", []) or []
    if manual_feedback:
        review_notes = list(review_notes) + [f"\u8fd4\u4fee\u53cd\u9988\uff1a{manual_feedback}"]

    switch_reason = ""
    if latest_preset and latest_preset != recommendation.get("preset_key", ""):
        switch_reason = (
            f"\u4e0a\u4e00\u8f6e\u4e3b\u8981\u4f7f\u7528\u9884\u8bbe {latest_preset}\uff0c"
            f"\u8fd9\u4e00\u8f6e\u5efa\u8bae\u5207\u5230 {recommendation.get('preset_key', '')}\uff0c"
            "\u5148\u9488\u5bf9\u6700\u5f31\u9879\u96c6\u4e2d\u8fd4\u4fee\u3002"
        )
    else:
        switch_reason = "\u5f53\u524d\u5efa\u8bae\u7ee7\u7eed\u5728\u5bf9\u5e94\u9884\u8bbe\u5185\u805a\u7126\u5f31\u9879\u8fd4\u4fee\u3002"

    tool_order = recommendation.get("tool_order", []) or []
    if primary_task == "shot" and "\u8fd4\u5de5\u4fee\u6b63\u94fe" not in tool_order:
        tool_order = list(tool_order) + ["\u8fd4\u5de5\u4fee\u6b63\u94fe"]

    total_score = int(evaluation_result.get("total_score", 0) or 0)
    if total_score >= 75:
        rework_priority = "medium"
    elif total_score >= 60:
        rework_priority = "high"
    else:
        rework_priority = "critical"

    return {
        "project_id": normalized_project_id,
        "output_name": normalized_output_name,
        "problem_type": primary_problem,
        "problem_label": PROBLEM_LABELS.get(primary_problem, primary_problem),
        "problem_types": problem_types,
        "problem_labels": [PROBLEM_LABELS.get(item, item) for item in problem_types],
        "rework_priority": rework_priority,
        "rework_strategy": strategy_bundle,
        "suggested_task_type": primary_task,
        "suggested_task_label": PROBLEM_LABELS.get(primary_task, primary_task),
        "suggested_preset_key": recommendation.get("preset_key", ""),
        "suggested_filter_mode": recommendation.get("filter_mode", ""),
        "suggested_filter_value": recommendation.get("filter_value", ""),
        "secondary_recommendations": recommendation.get("secondary_recommendations", []),
        "tool_order": tool_order,
        "switch_reason": switch_reason,
        "trace_summary": run_summary.get("summary", {}),
        "review_notes": review_notes,
        "suggestion_summary": (
            f"\u672c\u8f6e\u8fd4\u4fee\u4f18\u5148\u89e3\u51b3\u300c{PROBLEM_LABELS.get(primary_problem, primary_problem)}\u300d\uff0c"
            f"\u5efa\u8bae\u5207\u5230 {recommendation.get('preset_key', '')} / "
            f"{recommendation.get('filter_mode', '')}={recommendation.get('filter_value', '')}\u8fdb\u884c\u5b9a\u5411\u8fd4\u5de5\u3002"
        ),
    }
