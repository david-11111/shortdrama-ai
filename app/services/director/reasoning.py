from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import json

from .evolution_index import get_evolution_index
from .presets import resolve_director_preset


ROOT_DIR = Path(__file__).resolve().parents[3]
GENRE_TOPOLOGY_FILE = ROOT_DIR / "data" / "prompt_libs" / "director_genre_topology.json"
GENRE_BASELINE_FILE = ROOT_DIR / "data" / "prompt_libs" / "genre_coverage_baseline.json"

TASK_PRIORITY = {
    "structure": 4,
    "character": 3,
    "emotion": 2,
    "shot": 1,
}

TASK_LABELS = {
    "structure": "结构问题",
    "character": "人物问题",
    "shot": "镜头问题",
    "emotion": "情绪问题",
}

TASK_RULES = {
    "structure": {
        "keywords": [
            "结构", "节奏", "叙事", "场次", "剧情推进", "逻辑", "对白功能", "铺垫", "反转", "伏笔", "长线", "三段式",
            "剧情", "不顺", "推进", "逻辑断", "故事不成立", "节奏散",
        ],
        "preset_key": "core_engineering",
        "filter_mode": "library_family",
        "filter_value": "核心工程库",
        "tool_order": ["豆包文案链", "导演标注链", "导演调库", "Seedance生成链"],
        "secondary_recommendations": ["人格内核库", "高级情绪库"],
        "reason": "当前任务核心在故事结构、对白功能或推进逻辑，优先回到核心工程库稳住骨架。",
    },
    "character": {
        "keywords": [
            "人设", "角色", "女主", "男主", "性格", "灵魂", "眼神", "神态", "仪态", "气质", "清冷", "狠人", "温柔", "宿命感人物",
            "人物", "不灵", "眼神不对", "不像她", "不像他", "前后不一致",
        ],
        "preset_key": "character_soul",
        "filter_mode": "parent_library",
        "filter_value": "人物灵魂库群",
        "tool_order": ["导演标注链", "导演调库", "豆包文案链", "Seedance生成链"],
        "secondary_recommendations": ["眼神眼睛库", "微神态仪态库", "人格内核库", "终极灵魂库"],
        "reason": "当前任务核心在角色是否活起来，优先调用人物灵魂库群修人物层。",
    },
    "shot": {
        "keywords": [
            "镜头", "运镜", "构图", "景别", "开场", "卡点", "爆款", "抓人", "转场", "特写", "推拉摇移", "分镜",
            "画面", "不抓人", "开头", "前三秒", "拍法", "机位", "镜头语言", "seedance",
        ],
        "preset_key": "viral_shot",
        "filter_mode": "parent_library",
        "filter_value": "镜头与拍法库群",
        "tool_order": ["导演调库", "参考图链", "Seedance生成链", "返工修正链"],
        "secondary_recommendations": ["镜头基准库", "短视频爆款拍法库", "镜头禁忌库"],
        "reason": "当前任务核心在怎么拍更抓人，优先进入镜头与拍法库群和 Seedance 执行链。",
    },
    "emotion": {
        "keywords": [
            "情绪", "氛围", "留白", "破碎感", "隐忍", "克制", "暧昧", "宿命", "疏离", "遗憾", "拉扯", "释怀", "对冲", "渐变",
            "不够虐", "没有感觉", "氛围感", "不够细", "太表面", "暗流",
        ],
        "preset_key": "destiny_cinematic",
        "filter_mode": "parent_library",
        "filter_value": "人物灵魂库群",
        "tool_order": ["导演标注链", "导演调库", "豆包文案链", "Seedance生成链"],
        "secondary_recommendations": ["高级情绪库", "终极灵魂库", "眼神眼睛库", "微神态仪态库"],
        "reason": "当前任务核心在情绪层次和氛围调性，优先调用人物灵魂库群中的情绪专题。",
    },
}

VALID_TASK_TYPES = set(TASK_RULES.keys())
_genre_topology_cache: dict[str, Any] | None = None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_genre_topology() -> dict[str, Any]:
    global _genre_topology_cache
    if _genre_topology_cache is None:
        topology = _load_json(GENRE_TOPOLOGY_FILE)
        baseline = _load_json(GENRE_BASELINE_FILE)
        topology_genres = topology.get("genres", []) if isinstance(topology.get("genres", []), list) else []
        baseline_genres = baseline.get("genres", []) if isinstance(baseline.get("genres", []), list) else []
        keyed = {
            str(item.get("key", "")).strip(): item
            for item in topology_genres
            if str(item.get("key", "")).strip()
        }
        for genre in baseline_genres:
            key = str(genre.get("key", "")).strip()
            if not key or key in keyed:
                continue
            aliases = [str(item).strip() for item in genre.get("aliases", []) if str(item).strip()]
            name = str(genre.get("name", "")).strip() or key
            keyed[key] = {
                "key": key,
                "name": name,
                "aliases": aliases,
                "task_weights": {"structure": 3, "character": 3, "emotion": 3, "shot": 2},
                "preset_candidates": ["core_engineering", "character_soul", "destiny_cinematic", "viral_shot"],
                "tool_order": ["导演标注链", "导演调库", "豆包文案链", "Seedance生成链"],
                "conflict_motifs": [f"{name}核心冲突", f"{name}身份阻力"],
                "relationship_patterns": [f"{name}关系推进", f"{name}对抗关系"],
                "emotion_arcs": [f"{name}情绪递进", f"{name}情绪反转"],
                "shot_preferences": [f"{name}氛围镜头", f"{name}人物反应镜头"],
                "library_gap_note": f"{name}题材已进入母结构识别，但仍缺专属题材库条目。",
            }
        topology["genres"] = list(keyed.values())
        _genre_topology_cache = topology
    return _genre_topology_cache or {}


def _merge_text(*parts: str) -> str:
    return "\n".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _count_keyword_hits(text: str, keywords: list[str]) -> list[str]:
    normalized_text = str(text or "").lower()
    hits: list[str] = []
    for keyword in keywords:
        normalized_keyword = str(keyword or "").strip().lower()
        if not normalized_keyword:
            continue
        if normalized_keyword in normalized_text and keyword not in hits:
            hits.append(keyword)
    return hits


def _count_text_cues(text: str, cues: list[str]) -> int:
    normalized_text = str(text or "").lower()
    count = 0
    for cue in cues:
        normalized_cue = str(cue or "").strip().lower()
        if normalized_cue and normalized_cue in normalized_text:
            count += 1
    return count


def _is_visual_brief(text: str) -> bool:
    normalized = str(text or "").lower()
    if not normalized.strip():
        return False
    request_terms = ["视频", "剧本", "分镜", "画面", "镜头", "拍", "短片"]
    subject_terms = [
        "美女", "女生", "女孩子", "女孩", "女人", "男生", "男人", "长发", "短发", "骑", "自行车", "裙子", "外景", "街头",
    ]
    narrative_terms = [
        "分手", "重逢", "误会", "反转", "剧情", "对白", "台词", "冲突", "挽留", "告白", "职场", "宫斗", "复仇", "悬疑",
    ]
    has_request = any(term in normalized for term in request_terms)
    has_subject = any(term in normalized for term in subject_terms)
    has_narrative = any(term in normalized for term in narrative_terms)
    return has_request and has_subject and not has_narrative


def _apply_visual_brief_heuristics(text: str, rule_hits: dict[str, list[str]], rule_scores: dict[str, int]) -> None:
    if not _is_visual_brief(text):
        return
    normalized = str(text or "")
    if any(term in normalized for term in ("长发", "美女", "女生", "女孩子", "男生", "男人")):
        rule_scores["character"] += 160
        rule_hits["character"] = _unique_list(rule_hits.get("character", []) + ["visual_brief_subject"])
    if any(term in normalized for term in ("骑", "自行车", "街头", "外景", "镜头", "画面", "视频", "拍")):
        rule_scores["shot"] += 260
        rule_hits["shot"] = _unique_list(rule_hits.get("shot", []) + ["visual_brief_shot"])
    if "剧本" in normalized or "分镜" in normalized:
        rule_scores["structure"] += 80
        rule_hits["structure"] = _unique_list(rule_hits.get("structure", []) + ["visual_brief_script_request"])


def _apply_opening_hook_heuristics(text: str, rule_hits: dict[str, list[str]], rule_scores: dict[str, int]) -> None:
    normalized = str(text or "")
    opening_terms = ["开场", "开头", "前三秒", "钩子", "抓人", "主线推进", "信息排序", "主线"]
    shot_terms = ["镜头", "镜头语言", "运镜", "拍法", "景别"]
    if any(term in normalized for term in opening_terms) and any(term in normalized for term in shot_terms):
        rule_scores["structure"] += 220
        rule_scores["shot"] += 120
        rule_hits["structure"] = _unique_list(rule_hits.get("structure", []) + ["opening_hook_structure_first"])
        rule_hits["shot"] = _unique_list(rule_hits.get("shot", []) + ["opening_hook_shot_support"])
    if any(term in normalized for term in ("主线推进", "信息排序", "关系线", "拍散", "别把人物关系线拍散")):
        rule_scores["structure"] += 240
        rule_scores["shot"] = max(0, int(rule_scores.get("shot", 0) or 0) - 80)
        rule_hits["structure"] = _unique_list(rule_hits.get("structure", []) + ["opening_hook_keep_mainline"])


def _apply_script_scene_heuristics(text: str, rule_hits: dict[str, list[str]], rule_scores: dict[str, int]) -> None:
    normalized_text = str(text or "")
    if not normalized_text.strip():
        return

    speaker_turns = normalized_text.count("：") + normalized_text.count(":")
    character_cues = [
        "眼神", "神态", "眼尾", "眼底", "喉结", "嘴角", "角色", "人物", "人设", "立住",
        "停住", "没说", "不说", "说不出口", "迈了半步", "捏得发白", "人物有点假", "像空壳",
    ]
    emotion_cues = [
        "情绪", "余温", "遗憾", "平静", "发酸", "发红", "眼泪", "笑了一下", "暖意",
        "留不住", "收住情绪", "克制", "暗流", "分手", "挽留", "没说出口", "强行收住",
    ]
    shot_cues = [
        "镜头", "运镜", "构图", "特写", "推拉", "摇移", "空镜", "镜头语言", "机位",
    ]
    structure_cues = [
        "结构", "节奏", "开场", "前三秒", "主线", "推进", "钩子", "信息排序",
    ]

    character_signal = _count_text_cues(normalized_text, character_cues)
    emotion_signal = _count_text_cues(normalized_text, emotion_cues)
    shot_signal = _count_text_cues(normalized_text, shot_cues)
    structure_signal = _count_text_cues(normalized_text, structure_cues)

    is_dialogue_scene = speaker_turns >= 4
    if is_dialogue_scene and character_signal >= 2:
        rule_scores["character"] += 240
        rule_hits["character"] = _unique_list(rule_hits.get("character", []) + ["scene_dialogue_character"])
    if is_dialogue_scene and emotion_signal >= 2:
        rule_scores["emotion"] += 180
        rule_hits["emotion"] = _unique_list(rule_hits.get("emotion", []) + ["scene_dialogue_emotion"])
    if "分手" in normalized_text and ("眼神" in normalized_text or "没说" in normalized_text or "留不住" in normalized_text):
        rule_scores["character"] += 120
        rule_scores["emotion"] += 120
        rule_hits["character"] = _unique_list(rule_hits.get("character", []) + ["分手戏人物约束"])
        rule_hits["emotion"] = _unique_list(rule_hits.get("emotion", []) + ["分手戏情绪余温"])
    if shot_signal > 0 and structure_signal > 0 and character_signal == 0 and emotion_signal == 0:
        rule_scores["shot"] += shot_signal * 100
        rule_scores["structure"] += structure_signal * 100


def _unique_list(items: list[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if limit is not None and len(result) >= limit:
            break
    return result


def _format_percent(value: float) -> float:
    return round(max(0.0, float(value)), 2)


def _genre_terms(genre: dict[str, Any]) -> list[str]:
    terms: list[str] = [str(genre.get("name", "")).strip()]
    for field in ("aliases", "keywords"):
        for item in genre.get(field, []) or []:
            terms.append(str(item).strip())
    return _unique_list(terms)


def _detect_genre_matches(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    matches: list[dict[str, Any]] = []
    for genre in _load_genre_topology().get("genres", []):
        hits = _count_keyword_hits(text, _genre_terms(genre))
        if not hits:
            continue
        score = len(hits)
        name = str(genre.get("name", "")).strip()
        if name and name.lower() in text.lower():
            score += 1
        matches.append({
            "key": str(genre.get("key", "")).strip(),
            "name": name,
            "score": score,
            "hits": hits,
            "task_weights": genre.get("task_weights", {}) or {},
            "preset_candidates": genre.get("preset_candidates", []) or [],
            "tool_order": genre.get("tool_order", []) or [],
            "conflict_motifs": genre.get("conflict_motifs", []) or [],
            "relationship_patterns": genre.get("relationship_patterns", []) or [],
            "emotion_arcs": genre.get("emotion_arcs", []) or [],
            "shot_preferences": genre.get("shot_preferences", []) or [],
            "library_gap_note": str(genre.get("library_gap_note", "")).strip(),
        })
    matches.sort(key=lambda item: (item["score"], item["name"]), reverse=True)
    return matches


def _build_topology_profile(genre_matches: list[dict[str, Any]]) -> dict[str, Any]:
    dominant = genre_matches[:2]
    topology = {
        "detected_genres": [
            {
                "key": item.get("key", ""),
                "name": item.get("name", ""),
                "score": item.get("score", 0),
                "hits": item.get("hits", []),
            }
            for item in genre_matches[:4]
        ],
        "conflict_motifs": _unique_list([value for item in dominant for value in item.get("conflict_motifs", [])], limit=6),
        "relationship_patterns": _unique_list([value for item in dominant for value in item.get("relationship_patterns", [])], limit=6),
        "emotion_arcs": _unique_list([value for item in dominant for value in item.get("emotion_arcs", [])], limit=6),
        "shot_preferences": _unique_list([value for item in dominant for value in item.get("shot_preferences", [])], limit=6),
        "preset_candidates": _unique_list([value for item in dominant for value in item.get("preset_candidates", [])], limit=5),
        "tool_order": _unique_list([value for item in dominant for value in item.get("tool_order", [])], limit=6),
        "library_gap_notes": _unique_list([item.get("library_gap_note", "") for item in dominant], limit=3),
    }
    topology["enabled"] = bool(topology["detected_genres"])
    return topology


def _build_hybrid_task_profile(query: str, style_hint: str = "", context_hint: str = "") -> dict[str, Any]:
    text = _merge_text(query, style_hint, context_hint)
    rule_hits: dict[str, list[str]] = {}
    rule_scores: dict[str, int] = {}
    for task_type, rule in TASK_RULES.items():
        hits = _count_keyword_hits(text, rule["keywords"])
        rule_hits[task_type] = hits
        rule_scores[task_type] = len(hits) * 100
    _apply_visual_brief_heuristics(text, rule_hits, rule_scores)
    _apply_opening_hook_heuristics(text, rule_hits, rule_scores)

    speaker_turns = text.count("：") + text.count(":")
    character_signal = _count_text_cues(
        text,
        ["眼神", "神态", "眼尾", "眼底", "喉结", "嘴角", "角色", "人物", "人设", "立住", "停住", "没说", "不说", "说不出口", "迈了半步", "捏得发白", "人物有点假", "像空壳"],
    )
    emotion_signal = _count_text_cues(
        text,
        ["情绪", "余温", "遗憾", "平静", "发酸", "发红", "眼泪", "笑了一下", "暖意", "留不住", "收住情绪", "克制", "暗流", "分手", "挽留", "没说出口", "强行收住"],
    )
    if speaker_turns >= 4 and character_signal >= 2:
        rule_scores["character"] += 240
        rule_hits["character"] = _unique_list(rule_hits.get("character", []) + ["scene_dialogue_character"])
    if speaker_turns >= 4 and emotion_signal >= 2:
        rule_scores["emotion"] += 180
        rule_hits["emotion"] = _unique_list(rule_hits.get("emotion", []) + ["scene_dialogue_emotion"])
    if "分手" in text and ("眼神" in text or "没说" in text or "留不住" in text):
        rule_scores["character"] += 120
        rule_scores["emotion"] += 120
        rule_hits["character"] = _unique_list(rule_hits.get("character", []) + ["分手戏人物约束"])
        rule_hits["emotion"] = _unique_list(rule_hits.get("emotion", []) + ["分手戏情绪余温"])

    genre_matches = [] if _is_visual_brief(text) else _detect_genre_matches(text)
    topology_profile = _build_topology_profile(genre_matches)

    topology_scores: dict[str, int] = {task_type: 0 for task_type in VALID_TASK_TYPES}
    for item in genre_matches[:3]:
        match_score = max(1, int(item.get("score", 0) or 0))
        task_weights = item.get("task_weights", {}) or {}
        for task_type in VALID_TASK_TYPES:
            topology_scores[task_type] += int(task_weights.get(task_type, 0) or 0) * match_score * 10

    total_scores = {
        task_type: int(rule_scores.get(task_type, 0) or 0)
        for task_type in VALID_TASK_TYPES
    }
    ranked = sorted(total_scores.items(), key=lambda item: (item[1], TASK_PRIORITY[item[0]]), reverse=True)
    total_score_sum = sum(max(value, 0) for value in total_scores.values())
    weight_map = {
        task_type: _format_percent((value / total_score_sum) * 100) if total_score_sum else 0.0
        for task_type, value in total_scores.items()
    }

    mixed_candidates = []
    for task_type, value in ranked:
        mixed_candidates.append({
            "task_type": task_type,
            "task_label": TASK_LABELS[task_type],
            "score": value,
            "weight": weight_map.get(task_type, 0.0),
            "rule_score": rule_scores.get(task_type, 0),
            "topology_score": topology_scores.get(task_type, 0),
            "rule_hits": rule_hits.get(task_type, []),
        })

    blend_mode = "single_focus"
    if len(ranked) > 1:
        top_weight = float(weight_map.get(ranked[0][0], 0.0) or 0.0)
        second_weight = float(weight_map.get(ranked[1][0], 0.0) or 0.0)
        if top_weight < 45:
            blend_mode = "multi_focus"
        elif second_weight >= 24:
            blend_mode = "dual_focus"

    return {
        "text": text,
        "rule_hits": rule_hits,
        "rule_scores": rule_scores,
        "topology_scores": topology_scores,
        "total_scores": total_scores,
        "weight_map": weight_map,
        "mixed_candidates": mixed_candidates,
        "blend_mode": blend_mode,
        "genre_matches": genre_matches,
        "knowledge_topology": topology_profile,
    }


def _build_reason_tags(task_type: str, hybrid: dict[str, Any]) -> list[str]:
    tags = list((hybrid.get("rule_hits", {}) or {}).get(task_type, []))
    for item in (hybrid.get("genre_matches", []) or [])[:2]:
        genre_name = str(item.get("name", "")).strip()
        if genre_name:
            tags.append(f"题材:{genre_name}")
    return _unique_list(tags, limit=8)


def _build_supporting_tasks(diagnosis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(diagnosis, dict):
        return []
    primary = str(diagnosis.get("task_type", "")).strip().lower()
    support = []
    for item in diagnosis.get("mixed_candidates", []) or []:
        task_type = str(item.get("task_type", "")).strip().lower()
        weight = float(item.get("weight", 0.0) or 0.0)
        if not task_type or task_type == primary or weight < 18:
            continue
        support.append({
            "task_type": task_type,
            "task_label": TASK_LABELS.get(task_type, task_type),
            "weight": _format_percent(weight),
            "preset_key": TASK_RULES.get(task_type, {}).get("preset_key", ""),
        })
    return support[:3]


def _merge_tool_order(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group or []:
            value = str(item or "").strip()
            if value and value not in merged:
                merged.append(value)
    return merged


def _build_secondary_tool_orders(supporting_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bundles = []
    for item in supporting_tasks[:3]:
        task_type = str(item.get("task_type", "")).strip().lower()
        if task_type not in TASK_RULES:
            continue
        bundles.append({
            "task_type": task_type,
            "task_label": TASK_LABELS.get(task_type, task_type),
            "weight": item.get("weight", 0.0),
            "tool_order": list(TASK_RULES[task_type].get("tool_order", [])),
            "preset_key": TASK_RULES[task_type].get("preset_key", ""),
        })
    return bundles


def _build_evolution_feedback(query_text: str, *, project_id: str = "", problem_type: str = "", current_preset_key: str = "") -> dict[str, Any]:
    normalized_problem = str(problem_type or "").strip().lower()
    if not query_text.strip() or not normalized_problem:
        return {"enabled": False, "reason": "query_or_problem_missing"}

    index = get_evolution_index()
    success_cases = index.get_similar_cases(query_text, project_id=project_id, problem_type=normalized_problem, verdict_type="success", limit=3)
    if not success_cases and project_id:
        success_cases = index.get_similar_cases(query_text, problem_type=normalized_problem, verdict_type="success", limit=3)
    failure_cases = index.get_similar_cases(query_text, project_id=project_id, problem_type=normalized_problem, verdict_type="failure", limit=2)
    if not failure_cases and project_id:
        failure_cases = index.get_similar_cases(query_text, problem_type=normalized_problem, verdict_type="failure", limit=2)
    rework_cases = index.get_similar_cases(query_text, project_id=project_id, problem_type=normalized_problem, verdict_type="rework", limit=2)
    if not rework_cases and project_id:
        rework_cases = index.get_similar_cases(query_text, problem_type=normalized_problem, verdict_type="rework", limit=2)
    best_patterns = index.get_best_patterns_by_problem(normalized_problem, verdict_type="success", limit=3)

    if not success_cases and not failure_cases and not rework_cases and not best_patterns:
        return {
            "enabled": False,
            "reason": "no_similar_cases",
            "problem_type": normalized_problem,
        }

    success_votes: Counter[str] = Counter()
    failure_votes: Counter[str] = Counter()
    for item in success_cases:
        weight = max(float(item.get("score", 0.0) or 0.0), 0.05)
        for preset_key in item.get("reusable_pattern", {}).get("recommended_preset_keys", []) or []:
            normalized = str(preset_key or "").strip()
            if normalized:
                success_votes[normalized] += weight
    for item in failure_cases:
        weight = max(float(item.get("score", 0.0) or 0.0), 0.05)
        for preset_key in item.get("reusable_pattern", {}).get("recommended_preset_keys", []) or []:
            normalized = str(preset_key or "").strip()
            if normalized:
                failure_votes[normalized] += weight

    promoted_preset_key = ""
    promoted_gain = 0.0
    for preset_key, success_score in success_votes.most_common():
        gain = float(success_score) - float(failure_votes.get(preset_key, 0.0) or 0.0)
        if gain > promoted_gain:
            promoted_gain = gain
            promoted_preset_key = preset_key

    avoided = [preset_key for preset_key, _ in failure_votes.most_common(3)]
    if promoted_preset_key == str(current_preset_key or "").strip() and promoted_gain < 0.15:
        promoted_preset_key = ""

    signal_strength = "weak"
    case_count = len(success_cases) + len(failure_cases) + len(rework_cases)
    if promoted_gain >= 0.4 or case_count >= 4:
        signal_strength = "high"
    elif promoted_gain >= 0.2 or case_count >= 2:
        signal_strength = "medium"

    strategy_hints = _unique_list([
        str(item.get("pattern_summary", "")).strip()
        for item in [entry.get("reusable_pattern", {}) or {} for entry in success_cases + rework_cases]
        if str(item.get("pattern_summary", "")).strip()
    ], limit=4)
    fallback_presets = _unique_list([
        str(preset).strip()
        for pattern in best_patterns
        for preset in (pattern.get("recommended_preset_keys", []) or [])
        if str(preset).strip()
    ], limit=4)

    def _case_briefs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        briefs = []
        for item in items:
            case_record = item.get("case_record", {}) or {}
            reusable_pattern = item.get("reusable_pattern", {}) or {}
            briefs.append({
                "case_id": case_record.get("case_id", ""),
                "score": _format_percent(float(item.get("score", 0.0) or 0.0)),
                "output_name": case_record.get("output_name", ""),
                "preset_keys": reusable_pattern.get("recommended_preset_keys", []) or [],
                "pattern_summary": reusable_pattern.get("pattern_summary", ""),
            })
        return briefs

    return {
        "enabled": True,
        "problem_type": normalized_problem,
        "signal_strength": signal_strength,
        "promoted_preset_key": promoted_preset_key,
        "avoid_preset_keys": avoided,
        "fallback_preset_keys": fallback_presets,
        "strategy_hints": strategy_hints,
        "success_case_count": len(success_cases),
        "failure_case_count": len(failure_cases),
        "rework_case_count": len(rework_cases),
        "success_cases": _case_briefs(success_cases),
        "failure_cases": _case_briefs(failure_cases),
        "rework_cases": _case_briefs(rework_cases),
    }


def diagnose_task(
    query: str,
    *,
    style_hint: str = "",
    context_hint: str = "",
    manual_task_type: str = "",
) -> dict[str, Any]:
    hybrid = _build_hybrid_task_profile(query, style_hint=style_hint, context_hint=context_hint)
    score_map = hybrid["total_scores"]
    ranked = sorted(score_map.items(), key=lambda item: (item[1], TASK_PRIORITY[item[0]]), reverse=True)
    manual = str(manual_task_type or "").strip().lower()

    if manual in VALID_TASK_TYPES:
        return {
            "task_type": manual,
            "task_label": TASK_LABELS[manual],
            "confidence": "manual",
            "reason_tags": _build_reason_tags(manual, hybrid),
            "manual_override_recommended": False,
            "fallback_note": "已使用人工强制分类。",
            "scores": score_map,
            "score_breakdown": {
                task_type: {
                    "rule_score": hybrid["rule_scores"].get(task_type, 0),
                    "topology_score": hybrid["topology_scores"].get(task_type, 0),
                    "total_score": hybrid["total_scores"].get(task_type, 0),
                }
                for task_type in VALID_TASK_TYPES
            },
            "weight_map": hybrid["weight_map"],
            "mixed_candidates": hybrid["mixed_candidates"],
            "blend_mode": hybrid.get("blend_mode", "single_focus"),
            "knowledge_topology": hybrid["knowledge_topology"],
            "source": "manual_override",
        }

    top_task, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    top_weight = float(hybrid["weight_map"].get(top_task, 0.0) or 0.0)

    if top_score <= 0:
        scene_text = str(hybrid.get("text", "") or "")
        speaker_turns = scene_text.count("：") + scene_text.count(":")
        fallback_scores = {
            "structure": _count_text_cues(scene_text, ["结构", "节奏", "开场", "前三秒", "主线", "推进", "钩子", "信息排序"]) * 100,
            "character": _count_text_cues(scene_text, ["眼神", "神态", "眼尾", "眼底", "喉结", "嘴角", "角色", "人物", "人设", "立住", "停住", "没说", "不说", "说不出口", "迈了半步", "捏得发白", "人物有点假", "像空壳"]) * 100,
            "shot": _count_text_cues(scene_text, ["镜头", "运镜", "构图", "特写", "推拉", "摇移", "空镜", "镜头语言", "机位"]) * 100,
            "emotion": _count_text_cues(scene_text, ["情绪", "余温", "遗憾", "平静", "发酸", "发红", "眼泪", "笑了一下", "暖意", "留不住", "收住情绪", "克制", "暗流", "分手", "挽留", "没说出口", "强行收住"]) * 100,
        }
        if speaker_turns >= 4 and max(fallback_scores.values()) > 0:
            fallback_ranked = sorted(fallback_scores.items(), key=lambda item: (item[1], TASK_PRIORITY[item[0]]), reverse=True)
            fallback_total = sum(max(value, 0) for value in fallback_scores.values())
            fallback_weights = {
                task_type: _format_percent((value / fallback_total) * 100) if fallback_total else 0.0
                for task_type, value in fallback_scores.items()
            }
            fallback_candidates = [
                {
                    "task_type": task_type,
                    "task_label": TASK_LABELS[task_type],
                    "score": value,
                    "weight": fallback_weights.get(task_type, 0.0),
                    "rule_score": value,
                    "topology_score": hybrid["topology_scores"].get(task_type, 0),
                    "rule_hits": [],
                }
                for task_type, value in fallback_ranked
            ]
            fallback_task = fallback_ranked[0][0]
            return {
                "task_type": fallback_task,
                "task_label": TASK_LABELS[fallback_task],
                "confidence": "medium",
                "reason_tags": ["scene_script_fallback"],
                "manual_override_recommended": True,
                "fallback_note": "未命中显式规则，已按剧本场景中的人物/情绪/镜头线索回退判断，建议人工确认。",
                "scores": fallback_scores,
                "score_breakdown": {
                    task_type: {
                        "rule_score": fallback_scores.get(task_type, 0),
                        "topology_score": hybrid["topology_scores"].get(task_type, 0),
                        "total_score": fallback_scores.get(task_type, 0),
                    }
                    for task_type in VALID_TASK_TYPES
                },
                "weight_map": fallback_weights,
                "mixed_candidates": fallback_candidates,
                "blend_mode": "dual_focus" if fallback_weights.get("emotion", 0.0) >= 20 or fallback_weights.get("character", 0.0) >= 20 else "single_focus",
                "knowledge_topology": hybrid["knowledge_topology"],
                "source": "scene_script_fallback",
            }
        return {
            "task_type": "structure",
            "task_label": TASK_LABELS["structure"],
            "confidence": "low",
            "reason_tags": [],
            "manual_override_recommended": True,
            "fallback_note": "未命中明显规则，按结构问题保底，建议人工确认。",
            "scores": score_map,
            "score_breakdown": {
                task_type: {
                    "rule_score": hybrid["rule_scores"].get(task_type, 0),
                    "topology_score": hybrid["topology_scores"].get(task_type, 0),
                    "total_score": hybrid["total_scores"].get(task_type, 0),
                }
                for task_type in VALID_TASK_TYPES
            },
            "weight_map": hybrid["weight_map"],
            "mixed_candidates": hybrid["mixed_candidates"],
            "blend_mode": hybrid.get("blend_mode", "single_focus"),
            "knowledge_topology": hybrid["knowledge_topology"],
            "source": "rule_fallback",
        }

    confidence = "high"
    manual_override_recommended = False
    fallback_note = ""
    if top_score == second_score or top_weight < 45:
        confidence = "medium"
        manual_override_recommended = True
        fallback_note = "当前请求呈现多问题混合特征，建议人工确认主类。"
    elif top_score - second_score <= 40 and top_weight < 55:
        confidence = "medium"
        manual_override_recommended = True
        fallback_note = "主问题已识别，但次级问题权重仍高，建议按混合任务推进。"

    topology = hybrid["knowledge_topology"]
    if topology.get("library_gap_notes"):
        gap_note = "；".join(topology.get("library_gap_notes", [])[:2])
        fallback_note = f"{fallback_note} {gap_note}".strip()

    return {
        "task_type": top_task,
        "task_label": TASK_LABELS[top_task],
        "confidence": confidence,
        "reason_tags": _build_reason_tags(top_task, hybrid),
        "manual_override_recommended": manual_override_recommended,
        "fallback_note": fallback_note,
        "scores": score_map,
        "score_breakdown": {
            task_type: {
                "rule_score": hybrid["rule_scores"].get(task_type, 0),
                "topology_score": hybrid["topology_scores"].get(task_type, 0),
                "total_score": hybrid["total_scores"].get(task_type, 0),
            }
            for task_type in VALID_TASK_TYPES
        },
        "weight_map": hybrid["weight_map"],
        "mixed_candidates": hybrid["mixed_candidates"],
        "blend_mode": hybrid.get("blend_mode", "single_focus"),
        "knowledge_topology": topology,
        "source": "hybrid_rule_topology",
    }


def recommend_mode(
    *,
    task_type: str,
    project_id: str = "",
    query: str = "",
    style_hint: str = "",
    context_hint: str = "",
    diagnosis: dict[str, Any] | None = None,
    manual_preset_key: str = "",
    manual_filter_mode: str = "",
    manual_filter_value: str = "",
) -> dict[str, Any]:
    normalized = str(task_type or "").strip().lower()
    if normalized not in VALID_TASK_TYPES:
        normalized = "structure"

    rule = TASK_RULES[normalized]
    direct_mode = str(manual_filter_mode or "").strip()
    direct_value = str(manual_filter_value or "").strip()
    direct_preset = str(manual_preset_key or "").strip()
    hybrid = diagnosis if isinstance(diagnosis, dict) else diagnose_task(query, style_hint=style_hint, context_hint=context_hint)
    topology = hybrid.get("knowledge_topology", {}) if isinstance(hybrid, dict) else {}
    supporting_tasks = _build_supporting_tasks(hybrid if isinstance(hybrid, dict) else None)
    secondary_tool_orders = _build_secondary_tool_orders(supporting_tasks)

    preset_key = direct_preset or rule["preset_key"]
    filter_mode = direct_mode or rule["filter_mode"]
    filter_value = direct_value or rule["filter_value"]
    tool_order = _merge_tool_order(
        rule["tool_order"],
        topology.get("tool_order", []),
        *[bundle.get("tool_order", []) for bundle in secondary_tool_orders[:2]],
    )
    secondary_recommendations = _unique_list(
        list(rule["secondary_recommendations"]) + [item.get("preset_key", "") for item in supporting_tasks],
        limit=8,
    )

    evolution_feedback = _build_evolution_feedback(
        _merge_text(query, style_hint, context_hint),
        project_id=str(project_id or "").strip(),
        problem_type=normalized,
        current_preset_key=preset_key,
    )
    evolution_note = ""
    if not (direct_mode or direct_value or direct_preset):
        promoted_preset_key = str(evolution_feedback.get("promoted_preset_key", "")).strip()
        if promoted_preset_key:
            resolved = resolve_director_preset(promoted_preset_key)
            preset_key = promoted_preset_key
            filter_mode = str(resolved.get("filter_mode", "")).strip() or filter_mode
            filter_value = str(resolved.get("filter_value", "")).strip() or filter_value
            evolution_note = f"进化反哺命中相似成功案例，预设切到 {promoted_preset_key}。"
        elif evolution_feedback.get("fallback_preset_keys"):
            evolution_note = f"进化反哺暂无强命中，保留可参考预设 {' / '.join(evolution_feedback.get('fallback_preset_keys', [])[:2])}。"

    reason_parts = [rule["reason"]]
    detected_genres = [item.get("name", "") for item in topology.get("detected_genres", [])[:2] if item.get("name")]
    if detected_genres:
        reason_parts.append(f"已识别题材母结构：{' / '.join(detected_genres)}。")
    if supporting_tasks:
        support_text = " / ".join(f"{item['task_label']} {item['weight']}%" for item in supporting_tasks[:2])
        reason_parts.append(f"建议同时挂载次级判断：{support_text}。")
    if evolution_note:
        reason_parts.append(evolution_note)
    elif evolution_feedback.get("enabled") and evolution_feedback.get("avoid_preset_keys"):
        avoid_text = " / ".join(evolution_feedback.get("avoid_preset_keys", [])[:2])
        reason_parts.append(f"进化反哺提示谨慎复用：{avoid_text}。")
    if evolution_feedback.get("strategy_hints"):
        reason_parts.append(f"历史策略提示：{' / '.join(evolution_feedback.get('strategy_hints', [])[:2])}。")

    execution_mode = "single_focus"
    if isinstance(hybrid, dict):
        execution_mode = str(hybrid.get("blend_mode", "single_focus") or "single_focus")

    response = {
        "task_type": normalized,
        "task_label": TASK_LABELS[normalized],
        "preset_key": preset_key,
        "filter_mode": filter_mode,
        "filter_value": filter_value,
        "secondary_recommendations": secondary_recommendations,
        "tool_order": tool_order,
        "manual_override_allowed": True,
        "recommendation_reason": " ".join(part for part in reason_parts if part),
        "execution_mode": execution_mode,
        "weight_map": hybrid.get("weight_map", {}) if isinstance(hybrid, dict) else {},
        "supporting_tasks": supporting_tasks,
        "secondary_tool_orders": secondary_tool_orders,
        "knowledge_topology": topology,
        "evolution_feedback": evolution_feedback,
        "source": "manual_override" if (direct_mode or direct_value or direct_preset) else "hybrid_rule_topology_evolution",
    }
    if direct_mode or direct_value or direct_preset:
        response["recommendation_reason"] = "已应用人工覆盖，主干规则与进化反哺仅作为兜底参考。"
    return response


def diagnose_and_recommend(
    query: str,
    *,
    project_id: str = "",
    style_hint: str = "",
    context_hint: str = "",
    manual_task_type: str = "",
    manual_preset_key: str = "",
    manual_filter_mode: str = "",
    manual_filter_value: str = "",
) -> dict[str, Any]:
    diagnosis = diagnose_task(
        query,
        style_hint=style_hint,
        context_hint=context_hint,
        manual_task_type=manual_task_type,
    )
    recommendation = recommend_mode(
        task_type=diagnosis["task_type"],
        project_id=project_id,
        query=query,
        style_hint=style_hint,
        context_hint=context_hint,
        diagnosis=diagnosis,
        manual_preset_key=manual_preset_key,
        manual_filter_mode=manual_filter_mode,
        manual_filter_value=manual_filter_value,
    )
    return {
        "query": query,
        "diagnosis": diagnosis,
        "recommendation": recommendation,
    }
