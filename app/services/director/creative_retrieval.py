from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


CASE_BANK_FILE = Path(__file__).resolve().parent / "rules" / "case_bank_v1.json"

_ID_HINTS: dict[str, tuple[str, ...]] = {
    "ad-eyelash-realism": ("睫毛", "种草", "美妆", "真实感", "反差"),
    "ad-gold-recycle-trust": ("黄金", "回收", "门店", "到店", "信任", "报价", "检测"),
    "drama-short-reversal": ("短剧", "反转", "冲突", "剧情", "情绪"),
}


@dataclass(frozen=True)
class CaseEntry:
    id: str
    title: str
    tags: tuple[str, ...]
    hook: str
    beat_template: str
    dialogue_style: str
    camera_style: str
    risk_notes: str


def _tokenize(text: str) -> list[str]:
    clean = str(text or "").lower()
    chunks = re.split(r"[\s,，。；;、:：\n\r\t]+", clean)
    return [c.strip() for c in chunks if c.strip()]


@lru_cache(maxsize=1)
def load_case_bank() -> dict[str, Any]:
    with CASE_BANK_FILE.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    entries: list[CaseEntry] = []
    for item in raw.get("entries", []):
        entries.append(
            CaseEntry(
                id=str(item.get("id", "")).strip(),
                title=str(item.get("title", "")).strip(),
                tags=tuple(str(t).strip() for t in item.get("tags", []) if str(t).strip()),
                hook=str(item.get("hook", "")).strip(),
                beat_template=str(item.get("beat_template", "")).strip(),
                dialogue_style=str(item.get("dialogue_style", "")).strip(),
                camera_style=str(item.get("camera_style", "")).strip(),
                risk_notes=str(item.get("risk_notes", "")).strip(),
            ),
        )
    return {"version": str(raw.get("version", "case_bank_v1")), "entries": entries}


def _score_case(query: str, entry: CaseEntry, content_type: str = "") -> float:
    q = str(query or "").lower()
    tokens = _tokenize(q)
    score = 0.0

    fields = [entry.title, " ".join(entry.tags), entry.hook, entry.beat_template]
    for tk in tokens:
        if len(tk) <= 1:
            continue
        if tk in fields[0]:
            score += 3.0
        if tk in fields[1]:
            score += 2.0
        if tk in fields[2]:
            score += 1.5
        if tk in fields[3]:
            score += 1.0

    if content_type and (content_type in entry.title or any(content_type in t for t in entry.tags)):
        score += 2.0
    for hint in _ID_HINTS.get(entry.id, ()):
        if hint and hint in q:
            score += 2.4
    if score > 0:
        score += min(len(entry.tags), 6) * 0.1
    return score


def retrieve_case_context(
    query: str,
    top_k: int = 3,
    min_score: float = 1.0,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bank = load_case_bank()
    entries: list[CaseEntry] = bank.get("entries", [])
    content_type = str((content_profile or {}).get("content_type", "") or "")

    scored: list[tuple[CaseEntry, float]] = []
    for e in entries:
        s = _score_case(query, e, content_type=content_type)
        if s >= min_score:
            scored.append((e, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        fallback: list[tuple[CaseEntry, float]] = []
        for e in entries:
            fh = _ID_HINTS.get(e.id, ())
            fallback_score = sum(1.0 for h in fh if h and h in str(query or ""))
            if fallback_score > 0:
                fallback.append((e, fallback_score))
        fallback.sort(key=lambda x: x[1], reverse=True)
        scored = fallback
    top = scored[: max(1, int(top_k))]

    matched = [
        {
            "id": e.id,
            "title": e.title,
            "score": round(s, 2),
            "tags": list(e.tags),
            "hook": e.hook,
            "beat_template": e.beat_template,
            "dialogue_style": e.dialogue_style,
            "camera_style": e.camera_style,
            "risk_notes": e.risk_notes,
        }
        for e, s in top
    ]

    return {
        "version": bank.get("version", "case_bank_v1"),
        "query": str(query or ""),
        "matched": matched,
    }


def build_case_retrieval_block(matches: list[dict[str, Any]], max_items: int = 3) -> str:
    if not matches:
        return ""
    lines: list[str] = []
    for i, item in enumerate(matches[: max(1, int(max_items))], 1):
        title = str(item.get("title", "")).strip()
        hook = str(item.get("hook", "")).strip()
        beat = str(item.get("beat_template", "")).strip()
        camera = str(item.get("camera_style", "")).strip()
        risk = str(item.get("risk_notes", "")).strip()
        lines.append(f"{i}. {title}")
        if hook:
            lines.append(f"   - 钩子参考: {hook}")
        if beat:
            lines.append(f"   - 节拍参考: {beat}")
        if camera:
            lines.append(f"   - 镜头参考: {camera}")
        if risk:
            lines.append(f"   - 风险提示: {risk}")
    return "\n".join(lines)
