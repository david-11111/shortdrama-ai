from __future__ import annotations

import re
from typing import Any


_AI_CLICHES: tuple[tuple[str, str], ...] = (
    ("在当今这个快节奏的时代", "现在"),
    ("随着时代的发展", "这几年"),
    ("毋庸置疑", "说到底"),
    ("总而言之", "最后"),
    ("综上所述", "回到重点"),
    ("值得注意的是", "要注意"),
    ("不可否认的是", "确实"),
    ("提供了全新的解决方案", "给了一个新解法"),
    ("赋能", "帮到"),
    ("打造", "做出"),
)

_FORMAL_TO_NATURAL: tuple[tuple[str, str], ...] = (
    ("因此", "所以"),
    ("然而", "但"),
    ("此外", "另外"),
    ("与此同时", "同时"),
    ("用户", "观众"),
    ("进行", ""),
    ("实现", "做到"),
    ("能够", "能"),
    ("需要注意的是，", ""),
)

_FILLER_SENTENCES = (
    "这一点很关键。",
    "别把它想复杂。",
    "问题就出在这里。",
    "真正影响结果的是细节。",
)


def humanize_generated_copy(text: str, *, strength: str = "light", platform: str = "") -> dict[str, Any]:
    """Make generated copy less templated while preserving its structure.

    This is a deterministic post-processing layer. It improves readability and
    style variety; it does not claim to bypass platform review or originality
    checks.
    """
    original = str(text or "").strip()
    mode = normalize_strength(strength)
    if not original:
        return _result("", mode, [], platform)

    changed: list[str] = []
    rewritten = _replace_terms(original, _AI_CLICHES, changed, "cliche")

    if mode in {"medium", "deep"}:
        rewritten = _replace_terms(rewritten, _FORMAL_TO_NATURAL, changed, "natural_wording")
        rewritten = _break_long_sentences(rewritten, changed)

    if mode == "deep":
        rewritten = _vary_section_openers(rewritten, changed)
        rewritten = _add_light_human_rhythm(rewritten, changed)

    rewritten = _clean_spacing(rewritten)
    return _result(rewritten, mode, changed, platform)


def normalize_strength(value: str) -> str:
    value = str(value or "").strip().lower()
    aliases = {
        "轻度": "light",
        "轻": "light",
        "light": "light",
        "中度": "medium",
        "中": "medium",
        "medium": "medium",
        "深度": "deep",
        "深": "deep",
        "deep": "deep",
    }
    return aliases.get(value, "light")


def _replace_terms(text: str, pairs: tuple[tuple[str, str], ...], changed: list[str], label: str) -> str:
    result = text
    for src, dst in pairs:
        if src not in result:
            continue
        result = result.replace(src, dst)
        changed.append(f"{label}:{src}->{dst}")
    return result


def _break_long_sentences(text: str, changed: list[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        sentence = match.group(0)
        if len(sentence) < 30:
            return sentence
        for marker in ("但是", "所以", "因为", "如果", "尤其是", "比如"):
            index = sentence.find(marker)
            if 8 <= index <= len(sentence) - 8:
                changed.append("sentence_rhythm:split_long_sentence")
                return f"{sentence[:index]}。{sentence[index:]}"
        return sentence

    return re.sub(r"[^。！？\n]{24,}[。！？]", repl, text)


def _vary_section_openers(text: str, changed: list[str]) -> str:
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^[一二三四五六七八九十][、.．]", stripped):
            result.append(re.sub(r"^[一二三四五六七八九十][、.．]\s*", "", line, count=1))
            changed.append("structure:vary_numbered_opener")
            continue
        result.append(line)
    return "\n".join(result)


def _add_light_human_rhythm(text: str, changed: list[str]) -> str:
    paragraphs = text.split("\n\n")
    result: list[str] = []
    filler_index = 0
    for paragraph in paragraphs:
        result.append(paragraph)
        compact = re.sub(r"\s+", "", paragraph)
        if 60 <= len(compact) <= 220 and filler_index < len(_FILLER_SENTENCES):
            result.append(_FILLER_SENTENCES[filler_index])
            filler_index += 1
            changed.append("rhythm:add_short_sentence")
    return "\n\n".join(result)


def _clean_spacing(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _result(text: str, strength: str, changed: list[str], platform: str) -> dict[str, Any]:
    return {
        "text": text,
        "strength": strength,
        "platform": str(platform or "").strip(),
        "changed_rules": changed,
        "changed_count": len(changed),
        "note": "deterministic readability rewrite; no platform-review guarantee",
    }
