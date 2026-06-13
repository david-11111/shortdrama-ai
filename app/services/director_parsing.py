from __future__ import annotations

import json
from typing import Any


def parse_shot_rows(text: str, expected_count: int) -> list[dict[str, Any]]:
    if expected_count <= 0:
        return []

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "[":
            continue
        try:
            rows, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(rows, list):
            return rows[:expected_count]
    return [{"shot_number": i + 1, "raw_text": text} for i in range(expected_count)]
