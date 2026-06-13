from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


RECIPE_DIR = Path("data") / "final_cut_recipes"
RECIPE_FILES = ("editing_thinking_rules.json", "effect_recipes.json")


@lru_cache(maxsize=1)
def load_final_cut_recipes() -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    for file_name in RECIPE_FILES:
        path = RECIPE_DIR / file_name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            continue
        normalized_items = [_normalize_recipe_item(item) for item in items if isinstance(item, dict)]
        groups.append(
            {
                "id": path.stem,
                "version": payload.get("version", 1),
                "updated_at": payload.get("updated_at"),
                "count": len(normalized_items),
                "items": normalized_items,
            }
        )
        all_items.extend(normalized_items)

    categories = sorted({str(item.get("category") or "other") for item in all_items})
    return {
        "version": 1,
        "count": len(all_items),
        "categories": categories,
        "groups": groups,
        "items": all_items,
    }


def get_final_cut_recipe(recipe_id: str) -> dict[str, Any] | None:
    recipe_id = str(recipe_id or "").strip()
    if not recipe_id:
        return None
    for item in load_final_cut_recipes()["items"]:
        if item.get("id") == recipe_id:
            return item
    return None


def _normalize_recipe_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized.setdefault("commercial_value", "medium")
    normalized.setdefault("difficulty", "medium")
    normalized.setdefault("ffmpeg_feasibility", "planning_rule")
    normalized.setdefault("needs_ai", [])
    normalized.setdefault("needs_assets", [])
    normalized.setdefault("user_controls", [])
    return normalized
