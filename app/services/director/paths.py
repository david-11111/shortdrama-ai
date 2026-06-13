from __future__ import annotations

import re


INVALID_SEGMENT_PATTERN = re.compile(r'[\\/:*?"<>|]+')


def safe_path_segment(value: str, default: str = "default") -> str:
    text = str(value or "").strip()
    text = INVALID_SEGMENT_PATTERN.sub("_", text)
    text = text.replace("..", "_")
    text = text.replace("/", "_").replace("\\", "_")
    text = text.strip(" ._")
    return text or default
