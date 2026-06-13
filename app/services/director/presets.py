from __future__ import annotations

import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
PRESETS_FILE = ROOT_DIR / "data" / "prompt_libs" / "director_presets.json"
RUBRIC_FILE = ROOT_DIR / "data" / "prompt_libs" / "director_evaluation_rubric.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_director_presets() -> dict:
    return _load_json(PRESETS_FILE)


def get_director_evaluation_rubric() -> dict:
    return _load_json(RUBRIC_FILE)


def resolve_director_preset(
    preset_key: str = "",
    filter_mode: str = "",
    filter_value: str = "",
) -> dict:
    direct_mode = (filter_mode or "").strip()
    direct_value = (filter_value or "").strip()
    if direct_mode or direct_value:
        return {
            "preset_key": str(preset_key or "").strip(),
            "filter_mode": direct_mode,
            "filter_value": direct_value,
            "resolved_from": "direct_request",
            "preset": None,
        }

    key = str(preset_key or "").strip()
    presets = get_director_presets().get("presets", [])
    for item in presets:
        if str(item.get("key", "")).strip() == key:
            return {
                "preset_key": key,
                "filter_mode": str(item.get("filter_mode", "")).strip(),
                "filter_value": str(item.get("filter_value", "")).strip(),
                "resolved_from": "preset",
                "preset": item,
            }

    return {
        "preset_key": key,
        "filter_mode": "",
        "filter_value": "",
        "resolved_from": "default",
        "preset": None,
    }
