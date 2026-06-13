from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from typing import Any

from .normalizer import filter_visual_sources, normalize_sources_to_slots, render_normalized_prose
from .engine import compose_prompt_with_libraries, retrieve_prompt_matches


PROMPT_MODES = {"raw", "normalized", "compiled"}


SCENE_PATTERN = re.compile(r"^场次\s*\d+.*?(?=^场次\s*\d+|\Z)", re.M | re.S)
TIME_SEGMENT_PATTERN = re.compile(r"^\d+[-–—]\d+秒.*?(?=^\d+[-–—]\d+秒|\Z)", re.M | re.S)
SHOT_PATTERN = re.compile(r"【镜头】\s*(.*?)(?:\n人物：|\n人物:|$)", re.S)
CHARACTER_PATTERN = re.compile(r"人物[：:](.*?)(?:\n|$)")
ENDING_SHOT_PATTERN = re.compile(r"【结尾镜头】\s*(.*)$", re.S)
SPEAKER_INLINE_PATTERN = re.compile(r"^([^：:]{1,16})[：:](.+)$")
PUNCTUATION_PATTERN = re.compile(r"[，。！？；、“”‘’：:\-—…·（）()\[\]{}<>《》、,.;!?]")
TITLE_TERM_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,6}")


def _merge_parts(*parts: str) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = str(part or "").strip()
        if value and value not in seen:
            seen.add(value)
            merged.append(value)
    return "\n".join(merged)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip())


def _normalize_prompt_mode(mode: str) -> str:
    value = str(mode or "compiled").strip().lower()
    return value if value in PROMPT_MODES else "compiled"


def _clip(text: str, limit: int = 160) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _extract_global_setting(raw_text: str) -> str:
    """Extract character/style/scene settings from script header sections."""
    text = (raw_text or "").replace("\r\n", "\n")
    setting_parts: list[str] = []
    patterns = [
        re.compile(r"【人物设定】\s*(.*?)(?=\n【|\n分镜|\Z)", re.S),
        re.compile(r"【风格】\s*(.*?)(?=\n【|\n分镜|\Z)", re.S),
        re.compile(r"【场景】\s*(.*?)(?=\n【|\n分镜|\Z)", re.S),
        re.compile(r"【BGM】\s*(.*?)(?=\n【|\n分镜|\Z)", re.S),
        re.compile(r"【视频时长】\s*(.*?)(?=\n【|\n分镜|\Z)", re.S),
    ]
    for pat in patterns:
        m = pat.search(text)
        if m:
            setting_parts.append(m.group(0).strip())
    return "\n".join(setting_parts)


def _split_blocks(raw_text: str) -> tuple[str, list[str]]:
    text = (raw_text or "").replace("\r\n", "\n").strip()
    if not text:
        return "", []
    lines = [line.rstrip() for line in text.split("\n")]
    title = _clean_line(lines[0]) if lines else ""
    body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    blocks = [match.group(0).strip() for match in SCENE_PATTERN.finditer(body)]
    if not blocks:
        blocks = [match.group(0).strip() for match in TIME_SEGMENT_PATTERN.finditer(body)]
    if not blocks:
        full_text = body if body else title
        if full_text.strip():
            blocks = [full_text.strip()]
            title = title or "未命名场次"
    return title, blocks


def _extract_scene(block: str) -> dict[str, Any]:
    lines = [line.rstrip() for line in block.split("\n")]
    heading = _clean_line(lines[0]) if lines else ""
    content = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

    shot_block = ""
    shot_match = SHOT_PATTERN.search(content)
    if shot_match:
        shot_block = shot_match.group(1).strip()

    characters = ""
    characters_match = CHARACTER_PATTERN.search(content)
    if characters_match:
        characters = _clean_line(characters_match.group(1))

    ending_shot = ""
    ending_match = ENDING_SHOT_PATTERN.search(content)
    if ending_match:
        ending_shot = ending_match.group(1).strip()

    dialogue_lines: list[str] = []
    current_speaker = ""
    for raw_line in lines[1:]:
        line = _clean_line(raw_line)
        if not line:
            continue
        if line.startswith("【镜头】") or line.startswith("【结尾镜头】"):
            continue
        if line.startswith("人物：") or line.startswith("人物:"):
            continue
        if line.startswith("场次"):
            continue

        speaker_match = SPEAKER_INLINE_PATTERN.match(line)
        if speaker_match:
            current_speaker = _clean_line(speaker_match.group(1))
            content_part = _clean_line(speaker_match.group(2))
            if current_speaker and content_part:
                dialogue_lines.append(f"{current_speaker}：{content_part}")
            continue

        if len(line) <= 12 and not PUNCTUATION_PATTERN.search(line):
            current_speaker = line
            continue

        if current_speaker:
            dialogue_lines.append(f"{current_speaker}：{line}")
        else:
            dialogue_lines.append(line)

    return {
        "heading": heading,
        "raw_text": block.strip(),
        "body": content,
        "shot_block": shot_block,
        "ending_shot": ending_shot,
        "characters": characters,
        "dialogue_lines": dialogue_lines,
    }


def _filter_group(items: list[dict[str, Any]], group: str, limit: int = 3) -> list[dict[str, Any]]:
    selected = [item for item in items if item.get("group") == group]
    if selected:
        return selected[:limit]
    return items[:limit]


def _flatten_dimensions(item: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for dim_name, values in (item.get("dimensions") or {}).items():
        for value in values or []:
            if value:
                pairs.append((str(dim_name), str(value)))
    return pairs


def _collect_hit_reasons(item: dict[str, Any], *, query: str, global_context: str, local_context: str) -> list[str]:
    combined = _merge_parts(query, global_context, local_context)
    reasons: list[str] = []

    matched_tags = [tag for tag in item.get("tags", []) if tag and tag in combined][:4]
    if matched_tags:
        reasons.append("标签匹配：" + " / ".join(matched_tags))

    dimension_hits: list[str] = []
    for dim_name, value in _flatten_dimensions(item):
        if value in combined:
            dimension_hits.append(f"{dim_name}:{value}")
        if len(dimension_hits) >= 3:
            break
    if dimension_hits:
        reasons.append("维度命中：" + " / ".join(dimension_hits))

    title_terms = []
    for term in TITLE_TERM_PATTERN.findall(item.get("name", "")):
        if term in {"工程", "模式", "模板", "标准", "体系", "台词", "剧本", "专属"}:
            continue
        if term in combined and term not in title_terms:
            title_terms.append(term)
        if len(title_terms) >= 3:
            break
    if title_terms:
        reasons.append("标题语义：" + " / ".join(title_terms))

    if not reasons:
        reasons.append(f"{item.get('group', 'specialized')} 组高分命中")

    return reasons[:4]


def _build_seedance_base_prompt(scene: dict[str, Any]) -> str:
    return _merge_parts(
        scene.get("heading", ""),
        scene.get("shot_block", ""),
        scene.get("ending_shot", ""),
        f"人物：{scene['characters']}" if scene.get("characters") else "",
        "画面统一、角色稳定、镜头自然、情绪准确、电影感古风仙侠短剧质感。",
    )


def _build_ref_base_prompt(scene: dict[str, Any]) -> str:
    return _merge_parts(
        scene.get("heading", ""),
        scene.get("shot_block", ""),
        f"人物：{scene['characters']}" if scene.get("characters") else "",
        "生成参考图，强调构图、服化道、人物关系、场景氛围、光影色调统一。",
    )


def _describe_matches(
    items: list[dict[str, Any]],
    *,
    query: str,
    global_context: str,
    local_context: str,
) -> list[dict[str, Any]]:
    described: list[dict[str, Any]] = []
    for item in items:
        enriched = dict(item)
        enriched["hit_reasons"] = _collect_hit_reasons(
            item,
            query=query,
            global_context=global_context,
            local_context=local_context,
        )
        described.append(enriched)
    return described


def _dedupe_library_names(*groups: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            name = str(item.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _extract_prompt_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        sources.append(
            {
                "name": name,
                "group": item.get("group", ""),
                "score": item.get("score", 0),
                "prompt_text": item.get("prompt_text", ""),
                "hit_reasons": item.get("hit_reasons", []),
            }
        )
    return sources


def _append_unique(target: list[str], *values: str) -> None:
    for value in values:
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)


def _clean_sentence_piece(text: str) -> str:
    value = str(text or "").strip().strip("。；;，,")
    return value


def _join_prompt_parts(parts: list[str]) -> str:
    cleaned = [_clean_sentence_piece(part) for part in parts if _clean_sentence_piece(part)]
    return "。".join(cleaned) + ("。" if cleaned else "")


def _line_from_slots(slots: dict[str, list[str]], *keys: str, limit: int = 3) -> str:
    merged: list[str] = []
    for key in keys:
        for phrase in slots.get(key, []) or []:
            phrase = _clean_sentence_piece(phrase)
            if phrase and phrase not in merged:
                merged.append(phrase)
            if len(merged) >= limit:
                return "，".join(merged)
    return "，".join(merged)


def _line_from_slot_caps(slots: dict[str, list[str]], caps: list[tuple[str, int]], *, total_limit: int) -> str:
    merged: list[str] = []
    for key, cap in caps:
        count = 0
        for phrase in slots.get(key, []) or []:
            phrase = _clean_sentence_piece(phrase)
            if not phrase or phrase in merged:
                continue
            merged.append(phrase)
            count += 1
            if len(merged) >= total_limit or count >= cap:
                break
        if len(merged) >= total_limit:
            break
    return "，".join(merged)


def _select_prompt_by_mode(*, mode: str, raw: str, normalized: str, compiled: str) -> str:
    selected_mode = _normalize_prompt_mode(mode)
    if selected_mode == "raw":
        return raw
    if selected_mode == "normalized":
        return normalized
    return compiled


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _collect_seedance_phrase_buckets(sources: list[dict[str, Any]]) -> dict[str, list[str]]:
    buckets = {
        "style": [],
        "camera": [],
        "mood": [],
        "character": [],
        "constraint": [],
    }
    for source in sources:
        combined = " ".join(
            [
                str(source.get("name", "")),
                str(source.get("prompt_text", "")),
                " ".join(source.get("hit_reasons", []) or []),
            ]
        )
        if _contains_any(combined, ["古风", "仙侠"]):
            _append_unique(buckets["style"], "古风仙侠电影感")
        if _contains_any(combined, ["文艺", "留白"]):
            _append_unique(buckets["style"], "克制留白的文艺气质")
        if _contains_any(combined, ["文旅", "风景", "大片", "山河"]):
            _append_unique(buckets["style"], "大景别山水电影质感")
        if _contains_any(combined, ["镜头", "运镜", "推", "拉", "摇", "移"]):
            _append_unique(buckets["camera"], "运镜稳定连贯", "推拉摇移服务叙事")
        if _contains_any(combined, ["转场", "过渡"]):
            _append_unique(buckets["camera"], "镜头转场自然顺滑")
        if _contains_any(combined, ["氛围", "意境", "宿命", "空灵", "清冷", "肃杀"]):
            _append_unique(buckets["mood"], "氛围浓郁", "情绪递进清晰")
        if _contains_any(combined, ["音效", "环境"]):
            _append_unique(buckets["mood"], "环境氛围感强")
        if _contains_any(combined, ["人物", "表情", "微表情", "人设"]):
            _append_unique(buckets["character"], "人物五官稳定", "微表情准确克制")
        if _contains_any(combined, ["反派", "权谋", "压迫", "狠厉"]):
            _append_unique(buckets["character"], "人物气场压迫感明确")
        if _contains_any(combined, ["旁白", "独白", "内心"]):
            _append_unique(buckets["mood"], "带内心独白与宿命感")
        if _contains_any(combined, ["光", "光影", "照明"]):
            _append_unique(buckets["constraint"], "光影层次统一")
        if _contains_any(combined, ["色", "色调", "调色"]):
            _append_unique(buckets["constraint"], "色调统一稳定")
        if _contains_any(combined, ["构图", "空间", "透视", "场景"]):
            _append_unique(buckets["constraint"], "构图清晰，空间透视稳定")
        if _contains_any(combined, ["连贯", "稳定", "防崩", "一致"]):
            _append_unique(buckets["constraint"], "角色与场景连续稳定")
    return buckets


FUSION_SYSTEM_PROMPT = """你是一位顶级 AI 视频提示词工程师。你的任务是将用户的剧本场景描述与工程库提示词融合，生成可以直接发给 Seedance 视频生成模型的最终提示词。

规则：
1. 提示词开头必须描述人物主体（外貌、身高、发型、服装、气质），让视频模型知道画面里是谁
2. 保留剧本中所有具体的画面细节（动作、表情、场景、运镜）
3. 必须将工程库提示词中的技法融入最终提示词，不能忽略。具体做法：
   - 把库中的拍法描述（如"侧逆光勾边"、"跟拍"）转化为具体的镜头指令写进去
   - 把库中的约束（如"运镜稳定连贯"、"人物五官锚定"）作为画面约束附加在末尾
4. 最终提示词末尾必须附加一行工程约束，格式如：「工程约束：运镜匀速稳定，人物五官锚定不崩坏，光影层次统一不跳变，跨帧特征守恒」
5. 输出长度跟随剧本长度，不要人为压缩或截断
6. 只输出最终提示词，不要任何解释、前缀、标签"""

FUSION_REF_SYSTEM_PROMPT = """你是一位顶级 AI 参考图提示词工程师。你的任务是将用户的剧本场景描述与工程库提示词融合，生成可以直接用于生成参考图的提示词。

规则：
1. 开头必须描述人物主体（外貌、身高、发型、服装、气质、年龄），这是最重要的信息
2. 然后描述这张静态画面：姿态、表情、环境、光线、色调
3. 如果剧本已有详细人物和场景描述，保留所有细节，补充构图、光影、色彩约束
4. 如果剧本描述简短，则扩写成完整的参考图描述
5. 输出长度跟随内容复杂度，不要人为压缩
6. 只输出最终提示词，不要任何解释"""


def _fuse_prompt_with_llm(scene_text: str, compiled_prompt: str, mode: str = "video", global_context: str = "") -> str:
    """Use LLM to fuse script content with library prompts. Falls back to compiled if LLM fails."""
    try:
        from .doubao import _call_doubao
        system = FUSION_SYSTEM_PROMPT if mode == "video" else FUSION_REF_SYSTEM_PROMPT
        parts = []
        if global_context:
            parts.append(f"【全局设定（人物/风格/场景）】\n{global_context}")
        parts.append(f"【本场次剧本】\n{scene_text}")
        parts.append(f"【工程库提示词】\n{compiled_prompt}")
        user_text = "\n\n".join(parts)
        result = _call_doubao([
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
        ], timeout=30)
        fused = result.strip().strip('"').strip("'")
        return fused if fused else compiled_prompt
    except Exception:
        return compiled_prompt


def _compile_seedance_video_prompt(
    scene: dict[str, Any],
    *,
    style_hint: str = "",
    context_hint: str = "",
    sources: list[dict[str, Any]],
    normalized_slots: dict[str, list[str]] | None = None,
) -> str:
    slots = normalized_slots or {}
    buckets = _collect_seedance_phrase_buckets(sources)
    visual_core = _merge_parts(scene.get("heading", ""), scene.get("shot_block", ""), scene.get("ending_shot", ""))
    parts: list[str] = []
    if visual_core:
        parts.append(visual_core)
    if scene.get("characters"):
        parts.append(f"人物：{scene['characters']}")
    if style_hint or context_hint:
        parts.append(_merge_parts(style_hint, context_hint).replace("\n", "，"))
    style_line = _line_from_slots(slots, "style", limit=3) or "，".join(buckets["style"][:3])
    if style_line:
        parts.append(f"整体风格：{style_line}")
    camera_line = _line_from_slots(slots, "camera", limit=3) or "，".join(buckets["camera"][:3])
    if camera_line:
        parts.append(f"镜头要求：{camera_line}")
    mood_line = _line_from_slots(slots, "mood", limit=2) or "，".join(buckets["mood"][:2])
    if mood_line:
        parts.append(f"氛围情绪：{mood_line}")
    character_line = _line_from_slots(slots, "character", limit=2) or "，".join(buckets["character"][:2])
    if character_line:
        parts.append(f"人物表现：{character_line}")
    constraint_line = _line_from_slot_caps(slots, [("lighting", 1), ("color", 2), ("constraint", 2)], total_limit=5) or "，".join(buckets["constraint"][:5])
    if constraint_line:
        parts.append(f"画面约束：{constraint_line}")
    parts.append("9:16竖屏短剧视频，电影级质感，画面高级，动作自然，避免崩坏、跳变和突兀转场")
    return _join_prompt_parts(parts)


def _compile_seedance_ref_prompt(
    scene: dict[str, Any],
    *,
    style_hint: str = "",
    context_hint: str = "",
    sources: list[dict[str, Any]],
    normalized_slots: dict[str, list[str]] | None = None,
) -> str:
    slots = normalized_slots or {}
    buckets = _collect_seedance_phrase_buckets(sources)
    visual_core = _merge_parts(scene.get("heading", ""), scene.get("shot_block", ""))
    parts: list[str] = []
    if visual_core:
        parts.append(visual_core)
    if scene.get("characters"):
        parts.append(f"人物造型：{scene['characters']}")
    if style_hint or context_hint:
        parts.append(_merge_parts(style_hint, context_hint).replace("\n", "，"))
    style_line = _line_from_slots(slots, "style", "mood", limit=5) or "，".join((buckets["style"] + buckets["mood"])[:5])
    if style_line:
        parts.append(f"参考图风格：{style_line}")
    constraint_line = _line_from_slot_caps(slots, [("character", 2), ("lighting", 1), ("color", 2), ("constraint", 2)], total_limit=6) or "，".join((buckets["character"] + buckets["constraint"])[:6])
    if constraint_line:
        parts.append(f"参考图要求：{constraint_line}")
    parts.append("用于视频参考图，强调构图、服化道、人物站位、光影色调统一，高清电影感静帧")
    return _join_prompt_parts(parts)


def _build_scene_report(scene: dict[str, Any]) -> dict[str, Any]:
    annotations = scene.get("annotations", {})
    seedance = scene.get("seedance", {})
    fused_names = _dedupe_library_names(
        annotations.get("script_base", []),
        annotations.get("script_matches", []),
        annotations.get("shot_base", []),
        annotations.get("shot_matches", []),
        seedance.get("video_base", []),
        seedance.get("video_matches", []),
        seedance.get("ref_image_base", []),
        seedance.get("ref_image_matches", []),
    )
    return {
        "scene_index": scene.get("index", 0),
        "heading": scene.get("heading", ""),
        "characters": scene.get("characters", ""),
        "comparison": {
            "original_text": scene.get("raw_text", ""),
            "original_shot_text": scene.get("shot_block", ""),
            "selected_video_prompt_sources": seedance.get("video_prompt_sources", []),
            "selected_ref_prompt_sources": seedance.get("ref_image_prompt_sources", []),
            "selected_video_engineering_block": seedance.get("video_engineering_block", ""),
            "selected_ref_engineering_block": seedance.get("ref_image_engineering_block", ""),
            "normalized_video_prose": seedance.get("video_normalized_prose", ""),
            "normalized_ref_prose": seedance.get("ref_image_normalized_prose", ""),
            "raw_video_prompt": seedance.get("video_raw_prompt", ""),
            "raw_ref_image_prompt": seedance.get("ref_image_raw_prompt", ""),
            "annotated_video_prompt": seedance.get("video_prompt", ""),
            "annotated_ref_image_prompt": seedance.get("ref_image_prompt", ""),
            "active_video_prompt": seedance.get("video_prompt_active", ""),
            "active_ref_image_prompt": seedance.get("ref_image_prompt_active", ""),
            "prompt_mode": seedance.get("prompt_mode", "compiled"),
        },
        "script_hits": annotations.get("script_matches", []),
        "shot_hits": annotations.get("shot_matches", []),
        "dialogue_hits": annotations.get("dialogue_matches", []),
        "style_hits": annotations.get("style_matches", []),
        "video_hits": seedance.get("video_matches", []),
        "ref_image_hits": seedance.get("ref_image_matches", []),
        "final_fused_libraries": fused_names,
        "fusion_summary": " + ".join(fused_names[:10]),
        "comparison_summary": {
            "original_preview": _clip(scene.get("raw_text", ""), 220),
            "video_prompt_preview": _clip(seedance.get("video_prompt", ""), 220),
            "ref_image_prompt_preview": _clip(seedance.get("ref_image_prompt", ""), 220),
        },
        "video_prompt_preview": _clip(seedance.get("video_prompt", ""), 220),
        "ref_image_prompt_preview": _clip(seedance.get("ref_image_prompt", ""), 220),
    }


def _build_package_report(package: dict[str, Any]) -> dict[str, Any]:
    scene_reports = [_build_scene_report(scene) for scene in package.get("scenes", [])]
    library_counter: Counter[str] = Counter()
    group_counter: Counter[str] = Counter()
    for scene in package.get("scenes", []):
        for section in (
            scene.get("annotations", {}).get("script_matches", []),
            scene.get("annotations", {}).get("shot_matches", []),
            scene.get("seedance", {}).get("video_matches", []),
            scene.get("seedance", {}).get("ref_image_matches", []),
        ):
            for item in section:
                if item.get("name"):
                    library_counter[str(item["name"])] += 1
                if item.get("group"):
                    group_counter[str(item["group"])] += 1
    return {
        "summary": {
            "title": package.get("title", ""),
            "scene_count": package.get("scene_count", 0),
            "unique_library_count": len(library_counter),
            "top_libraries": [{"name": name, "hits": count} for name, count in library_counter.most_common(12)],
            "group_distribution": [{"group": name, "hits": count} for name, count in group_counter.most_common()],
        },
        "scenes": scene_reports,
    }


def annotate_clean_script(raw_text: str, *, style_hint: str = "", context_hint: str = "") -> dict[str, Any]:
    return annotate_clean_script_with_mode(raw_text, style_hint=style_hint, context_hint=context_hint, prompt_mode="compiled")


def annotate_clean_script_with_mode(
    raw_text: str,
    *,
    style_hint: str = "",
    context_hint: str = "",
    prompt_mode: str = "compiled",
    library_ids: set[str] | None = None,
) -> dict[str, Any]:
    selected_prompt_mode = _normalize_prompt_mode(prompt_mode)
    title, blocks = _split_blocks(raw_text)
    scenes: list[dict[str, Any]] = []
    character_setting = _extract_global_setting(raw_text)
    episode_context = _merge_parts(title, style_hint, context_hint, character_setting)

    for idx, block in enumerate(blocks, start=1):
        scene = _extract_scene(block)
        scene["index"] = idx

        local_context = _merge_parts(scene["heading"], scene["shot_block"], scene["ending_shot"], scene["characters"])
        dialogue_context = "\n".join(scene.get("dialogue_lines", [])[:12])
        scene_query = _merge_parts(scene["heading"], scene["shot_block"], dialogue_context, scene["ending_shot"])
        shot_query = _merge_parts(scene["heading"], scene["shot_block"], scene["ending_shot"])
        script_local_context = _merge_parts(local_context, dialogue_context)

        script_pkg = retrieve_prompt_matches(
            scene_query,
            stage="script",
            top_k=6,
            global_context=episode_context,
            local_context=script_local_context,
            include_base=True,
            library_ids=library_ids,
        )
        shot_pkg = retrieve_prompt_matches(
            shot_query,
            stage="shot",
            top_k=5,
            global_context=episode_context,
            local_context=local_context,
            include_base=True,
            library_ids=library_ids,
        )
        ref_pkg = compose_prompt_with_libraries(
            _build_ref_base_prompt(scene),
            query=_merge_parts(title, shot_query, scene.get("characters", "")),
            stage="ref_image",
            global_context=episode_context,
            local_context=local_context,
            library_ids=library_ids,
        )
        seedance_pkg = compose_prompt_with_libraries(
            _build_seedance_base_prompt(scene),
            query=_merge_parts(title, shot_query, dialogue_context),
            stage="shot",
            global_context=episode_context,
            local_context=script_local_context,
            library_ids=library_ids,
        )

        script_base = _describe_matches(
            script_pkg.get("base", []),
            query=scene_query,
            global_context=episode_context,
            local_context=script_local_context,
        )
        script_matches = _describe_matches(
            script_pkg.get("matched", []),
            query=scene_query,
            global_context=episode_context,
            local_context=script_local_context,
        )
        shot_base = _describe_matches(
            shot_pkg.get("base", []),
            query=shot_query,
            global_context=episode_context,
            local_context=local_context,
        )
        shot_matches = _describe_matches(
            shot_pkg.get("matched", []),
            query=shot_query,
            global_context=episode_context,
            local_context=local_context,
        )
        video_base = _describe_matches(
            seedance_pkg.get("base", []),
            query=shot_query,
            global_context=episode_context,
            local_context=script_local_context,
        )
        video_matches = _describe_matches(
            seedance_pkg.get("matched", []),
            query=shot_query,
            global_context=episode_context,
            local_context=script_local_context,
        )
        ref_base = _describe_matches(
            ref_pkg.get("base", []),
            query=shot_query,
            global_context=episode_context,
            local_context=local_context,
        )
        ref_matches = _describe_matches(
            ref_pkg.get("matched", []),
            query=shot_query,
            global_context=episode_context,
            local_context=local_context,
        )

        scene["annotations"] = {
            "script_base": script_base,
            "script_matches": script_matches,
            "shot_base": shot_base,
            "shot_matches": shot_matches,
            "dialogue_matches": _filter_group(script_matches, "dialogue"),
            "style_matches": _filter_group(script_matches, "style", limit=2),
        }
        video_prompt_sources = _extract_prompt_sources(video_base + video_matches)
        ref_prompt_sources = _extract_prompt_sources(ref_base + ref_matches)
        filtered_video_sources = filter_visual_sources(video_prompt_sources, target="video")
        filtered_ref_sources = filter_visual_sources(ref_prompt_sources, target="ref")
        normalized_video_slots = normalize_sources_to_slots(
            filtered_video_sources,
            scene_heading=scene.get("heading", ""),
            shot_text=scene.get("shot_block", ""),
            target="video",
        )
        normalized_ref_slots = normalize_sources_to_slots(
            filtered_ref_sources,
            scene_heading=scene.get("heading", ""),
            shot_text=scene.get("shot_block", ""),
            target="ref",
        )
        normalized_video_prose = render_normalized_prose(normalized_video_slots, target="video")
        normalized_ref_prose = render_normalized_prose(normalized_ref_slots, target="ref")
        seedance_friendly_video_prompt = _compile_seedance_video_prompt(
            scene,
            style_hint=style_hint,
            context_hint=context_hint,
            sources=filtered_video_sources,
            normalized_slots=normalized_video_slots,
        )
        seedance_friendly_ref_prompt = _compile_seedance_ref_prompt(
            scene,
            style_hint=style_hint,
            context_hint=context_hint,
            sources=filtered_ref_sources,
            normalized_slots=normalized_ref_slots,
        )

        scene_raw_text = _merge_parts(scene.get("heading", ""), scene.get("shot_block", ""), scene.get("ending_shot", ""), "\n".join(scene.get("dialogue_lines", [])[:6]))
        seedance_friendly_video_prompt = _fuse_prompt_with_llm(scene_raw_text, seedance_friendly_video_prompt, mode="video", global_context=episode_context)
        seedance_friendly_ref_prompt = _fuse_prompt_with_llm(scene_raw_text, seedance_friendly_ref_prompt, mode="ref", global_context=episode_context)

        active_video_prompt = _select_prompt_by_mode(
            mode=selected_prompt_mode,
            raw=seedance_pkg.get("prompt", ""),
            normalized=normalized_video_prose,
            compiled=seedance_friendly_video_prompt,
        )
        active_ref_prompt = _select_prompt_by_mode(
            mode=selected_prompt_mode,
            raw=ref_pkg.get("prompt", ""),
            normalized=normalized_ref_prose,
            compiled=seedance_friendly_ref_prompt,
        )

        scene["seedance"] = {
            "prompt_mode": selected_prompt_mode,
            "video_prompt": seedance_friendly_video_prompt,
            "video_raw_prompt": seedance_pkg.get("prompt", ""),
            "video_normalized_prose": normalized_video_prose,
            "video_normalized_slots": normalized_video_slots,
            "video_prompt_active": active_video_prompt,
            "video_engineering_block": seedance_pkg.get("block", ""),
            "video_base": video_base,
            "video_matches": video_matches,
            "video_prompt_sources": video_prompt_sources,
            "video_filtered_sources": filtered_video_sources,
            "ref_image_prompt": seedance_friendly_ref_prompt,
            "ref_image_raw_prompt": ref_pkg.get("prompt", ""),
            "ref_image_normalized_prose": normalized_ref_prose,
            "ref_image_normalized_slots": normalized_ref_slots,
            "ref_image_prompt_active": active_ref_prompt,
            "ref_image_engineering_block": ref_pkg.get("block", ""),
            "ref_image_base": ref_base,
            "ref_image_matches": ref_matches,
            "ref_image_prompt_sources": ref_prompt_sources,
            "ref_image_filtered_sources": filtered_ref_sources,
        }
        scene["comparison"] = {
            "original_text": scene.get("raw_text", ""),
            "original_shot_text": scene.get("shot_block", ""),
            "selected_video_prompt_sources": video_prompt_sources,
            "selected_ref_prompt_sources": ref_prompt_sources,
            "filtered_video_prompt_sources": filtered_video_sources,
            "filtered_ref_prompt_sources": filtered_ref_sources,
            "normalized_video_prose": normalized_video_prose,
            "normalized_ref_prose": normalized_ref_prose,
            "selected_video_engineering_block": seedance_pkg.get("block", ""),
            "selected_ref_engineering_block": ref_pkg.get("block", ""),
            "annotated_video_prompt": seedance_friendly_video_prompt,
            "annotated_ref_image_prompt": seedance_friendly_ref_prompt,
            "annotated_video_raw_prompt": seedance_pkg.get("prompt", ""),
            "annotated_ref_raw_prompt": ref_pkg.get("prompt", ""),
            "active_video_prompt": active_video_prompt,
            "active_ref_image_prompt": active_ref_prompt,
            "prompt_mode": selected_prompt_mode,
            "fused_libraries": _dedupe_library_names(
                script_base,
                script_matches,
                shot_base,
                shot_matches,
                video_base,
                video_matches,
                ref_base,
                ref_matches,
            ),
        }
        scenes.append(scene)

    package = {
        "title": title,
        "style_hint": style_hint,
        "context_hint": context_hint,
        "prompt_mode": selected_prompt_mode,
        "scene_count": len(scenes),
        "scenes": scenes,
    }
    package["report"] = _build_package_report(package)
    return package


def export_annotation_report(package: dict[str, Any], export_format: str = "csv") -> str:
    fmt = (export_format or "csv").strip().lower()
    if fmt == "json":
        return json.dumps(package.get("report", {}), ensure_ascii=False, indent=2)
    if fmt == "markdown":
        blocks: list[str] = []
        blocks.append(f"# {package.get('title', '剧本标注对比')}\n")
        for scene in package.get("scenes", []):
            comparison = scene.get("comparison", {})
            blocks.append(f"## 场次 {scene.get('index', 0)} {scene.get('heading', '')}")
            blocks.append(f"**当前模式** `{comparison.get('prompt_mode', package.get('prompt_mode', 'compiled'))}`")
            blocks.append("")
            blocks.append("**原文**")
            blocks.append(comparison.get("original_text", ""))
            blocks.append("")
            blocks.append("**融合库**")
            blocks.append(" / ".join(comparison.get("fused_libraries", [])))
            blocks.append("")
            blocks.append("**从96库中选中的视频提示词原文**")
            blocks.append(comparison.get("selected_video_engineering_block", ""))
            blocks.append("")
            blocks.append("**整理成文中间稿（视频）**")
            blocks.append(comparison.get("normalized_video_prose", ""))
            blocks.append("")
            blocks.append("**Seedance 视频提示词**")
            blocks.append(comparison.get("annotated_video_prompt", ""))
            blocks.append("")
            blocks.append("**当前启用视频提示词**")
            blocks.append(comparison.get("active_video_prompt", ""))
            blocks.append("")
            blocks.append("**从96库中选中的参考图提示词原文**")
            blocks.append(comparison.get("selected_ref_engineering_block", ""))
            blocks.append("")
            blocks.append("**整理成文中间稿（参考图）**")
            blocks.append(comparison.get("normalized_ref_prose", ""))
            blocks.append("")
            blocks.append("**参考图提示词**")
            blocks.append(comparison.get("annotated_ref_image_prompt", ""))
            blocks.append("")
            blocks.append("**当前启用参考图提示词**")
            blocks.append(comparison.get("active_ref_image_prompt", ""))
            blocks.append("")
        return "\n".join(blocks).strip() + "\n"

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "scene_index",
            "heading",
            "characters",
            "original_text",
            "script_hit_libraries",
            "shot_hit_libraries",
            "dialogue_hit_libraries",
            "video_hit_libraries",
            "ref_image_hit_libraries",
            "final_fused_libraries",
            "prompt_mode",
            "video_raw_prompt",
            "video_normalized_prose",
            "video_prompt",
            "video_prompt_active",
            "ref_image_raw_prompt",
            "ref_image_normalized_prose",
            "ref_image_prompt",
            "ref_image_prompt_active",
        ]
    )
    for scene in package.get("scenes", []):
        annotations = scene.get("annotations", {})
        seedance = scene.get("seedance", {})
        fused_names = _dedupe_library_names(
            annotations.get("script_base", []),
            annotations.get("script_matches", []),
            annotations.get("shot_base", []),
            annotations.get("shot_matches", []),
            seedance.get("video_base", []),
            seedance.get("video_matches", []),
            seedance.get("ref_image_base", []),
            seedance.get("ref_image_matches", []),
        )
        writer.writerow(
            [
                scene.get("index", 0),
                scene.get("heading", ""),
                scene.get("characters", ""),
                scene.get("comparison", {}).get("original_text", ""),
                " | ".join(item.get("name", "") for item in annotations.get("script_matches", [])),
                " | ".join(item.get("name", "") for item in annotations.get("shot_matches", [])),
                " | ".join(item.get("name", "") for item in annotations.get("dialogue_matches", [])),
                " | ".join(item.get("name", "") for item in seedance.get("video_matches", [])),
                " | ".join(item.get("name", "") for item in seedance.get("ref_image_matches", [])),
                " | ".join(fused_names),
                seedance.get("prompt_mode", package.get("prompt_mode", "compiled")),
                seedance.get("video_raw_prompt", ""),
                seedance.get("video_normalized_prose", ""),
                seedance.get("video_prompt", ""),
                seedance.get("video_prompt_active", ""),
                seedance.get("ref_image_raw_prompt", ""),
                seedance.get("ref_image_normalized_prose", ""),
                seedance.get("ref_image_prompt", ""),
                seedance.get("ref_image_prompt_active", ""),
            ]
        )
    return buffer.getvalue()
