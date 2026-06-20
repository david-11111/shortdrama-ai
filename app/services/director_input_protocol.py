from __future__ import annotations

from copy import deepcopy
from typing import Any

DIRECTOR_PROTOCOL_VERSION = "director_input_protocol_v1"

DEFAULT_PROJECT_STYLE = (
    "photorealistic live-action Chinese costume drama, real skin texture, "
    "real fabric, restrained lighting, grounded set design"
)

GLOBAL_MUST_AVOID = [
    "anime",
    "manga",
    "cartoon",
    "2D illustration",
    "game CG",
    "plastic skin",
    "idol filter",
    "fantasy poster",
    "excessive golden glow",
    "generic xianxia beauty",
]


def build_director_input_protocol(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    data = deepcopy(raw or {})
    return {
        "version": DIRECTOR_PROTOCOL_VERSION,
        "project_id": str(data.get("project_id") or ""),
        "series_title": str(data.get("series_title") or ""),
        "episode": str(data.get("episode") or ""),
        "project_style": str(data.get("project_style") or DEFAULT_PROJECT_STYLE),
        "global_must_avoid": _string_list(data.get("global_must_avoid")) or list(GLOBAL_MUST_AVOID),
        "task_type": str(data.get("task_type") or ""),
        "asset_kind": str(data.get("asset_kind") or ""),
        "creative_intent": str(data.get("creative_intent") or ""),
        "subject": data.get("subject") if isinstance(data.get("subject"), dict) else {},
        "must_keep": _string_list(data.get("must_keep")),
        "must_avoid": _dedupe([*GLOBAL_MUST_AVOID, *_string_list(data.get("must_avoid"))]),
        "approval_status": str(data.get("approval_status") or "draft"),
        "allowed_next_step": bool(data.get("allowed_next_step")),
        "director_note": str(
            data.get("director_note")
            or "Do not proceed to the next generation step before human approval."
        ),
    }


def director_protocol_allows_next_step(protocol: dict[str, Any] | None) -> bool:
    data = build_director_input_protocol(protocol)
    return data["approval_status"] == "approved" and bool(data["allowed_next_step"])


def director_protocol_prompt_block(protocol: dict[str, Any] | None, *, target: str) -> str:
    data = build_director_input_protocol(protocol)
    lines = [
        f"[{DIRECTOR_PROTOCOL_VERSION}]",
        f"target={target}",
        f"project_style={data['project_style']}",
    ]
    if data["task_type"]:
        lines.append(f"task_type={data['task_type']}")
    if data["asset_kind"]:
        lines.append(f"asset_kind={data['asset_kind']}")
    if data["creative_intent"]:
        lines.append(f"creative_intent={data['creative_intent']}")
    subject = data.get("subject") or {}
    if subject.get("name"):
        lines.append(f"subject_name={subject['name']}")
    if data["must_keep"]:
        lines.append("must_keep=" + "; ".join(data["must_keep"]))
    if data["must_avoid"]:
        lines.append("must_avoid=" + "; ".join(data["must_avoid"]))
    if data["director_note"]:
        lines.append(f"director_note={data['director_note']}")
    return "\n".join(lines)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
