# -*- coding: utf-8 -*-
"""Structured prompt-library retrieval and prompt assembly."""



from __future__ import annotations



import json

import os

import re

import threading

from dataclasses import asdict, dataclass, field

from datetime import datetime

from pathlib import Path





ROOT_DIR = Path(__file__).resolve().parents[2]

PROMPT_LIB_DIR = ROOT_DIR / "data" / "prompt_libs"

PROMPT_LIB_INDEX_FILE = PROMPT_LIB_DIR / "index.json"

PROMPT_LIB_METADATA_FILE = PROMPT_LIB_DIR / "metadata.json"

PROMPT_LIB_CATALOG_FILE = PROMPT_LIB_DIR / "catalog.generated.json"

PROMPT_LIB_QUICK_INDEX_FILE = PROMPT_LIB_DIR / "quick_index.md"

PROMPT_LIB_CONTEXT_VOCAB_FILE = PROMPT_LIB_DIR / "context_vocab.json"

PROMPT_LIB_LOCAL_ENTRIES_FILE = PROMPT_LIB_DIR / "local_entries.json"

PROMPT_LIB_BENCHMARK_ENTRIES_FILE = PROMPT_LIB_DIR / "shot_benchmark_entries.json"

PROMPT_LIB_BENCHMARK_TABOO_ENTRIES_FILE = PROMPT_LIB_DIR / "shot_benchmark_taboo_entries_31_50.json"

PROMPT_LIB_SHORT_VIDEO_ENTRIES_FILE = PROMPT_LIB_DIR / "short_video_viral_shot_entries.json"

PROMPT_LIB_SHORT_VIDEO_ENTRIES_FILE_61_90 = PROMPT_LIB_DIR / "short_video_viral_shot_entries_61_90.json"

PROMPT_LIB_EYE_EXPRESSION_ENTRIES_FILE = PROMPT_LIB_DIR / "eye_expression_entries.json"

PROMPT_LIB_DEMEANOR_EXPRESSION_ENTRIES_FILE = PROMPT_LIB_DIR / "demeanor_expression_entries.json"

PROMPT_LIB_INNER_CORE_ENTRIES_FILE = PROMPT_LIB_DIR / "inner_core_entries.json"

PROMPT_LIB_EMOTION_EXPRESSION_ENTRIES_FILE = PROMPT_LIB_DIR / "emotion_expression_entries.json"

PROMPT_LIB_ULTIMATE_SOUL_ENTRIES_FILE = PROMPT_LIB_DIR / "ultimate_soul_entries.json"

PROMPT_LIB_NINE_LAYER_SOUL_ENTRIES_FILE = PROMPT_LIB_DIR / "nine_layer_soul_entries.json"

PROMPT_RETRIEVAL_LOG_FILE = ROOT_DIR / "storage" / "prompt_retrieval_logs.jsonl"



LEGACY_MEMORY_DIR = Path(

    os.getenv(

        "PROMPT_LIBRARY_MEMORY_DIR",

        r"C:\Users\福星1号\.claude\projects\E--shortdrama-ai\memory",

    )

)

LEGACY_SCENE_FILE = Path(

    os.getenv(

        "PROMPT_LIBRARY_FILE",

        str(LEGACY_MEMORY_DIR / "project_scene_engineering.md"),

    )

)



DEFAULT_TOP_K = {

    "script": 5,

    "shot": 4,

    "ref_image": 3,

    "repair": 4,

}



DEFAULT_BASE_LIMITS = {

    "script": 6,

    "shot": 3,

    "ref_image": 3,

    "repair": 3,

}



DEFAULT_GROUP_LIMITS = {

    "style": 2,

    "shot": 3,

    "dialogue": 3,

}



DEFAULT_STAGE_WEIGHTS = {

    "script": {"query": 1.25, "global": 1.8, "local": 1.0, "failure": 0.8, "style": 1.9},

    "shot": {"query": 1.1, "global": 1.2, "local": 1.9, "failure": 1.0, "style": 1.3},

    "ref_image": {"query": 1.0, "global": 1.35, "local": 1.85, "failure": 0.8, "style": 1.5},

    "repair": {"query": 0.9, "global": 0.8, "local": 1.2, "failure": 2.4, "style": 0.9},

}



BASE_PROMPT_LIBRARY = [

    {

        "id": "base-1",

        "title": "运镜工程",

        "group": "base",

        "always_on": True,

        "priority": 10,

        "stages": ["script", "shot", "repair"],

        "tags": ["运镜", "镜头", "机位", "节奏", "调度"],

        "triggers": ["运镜", "推拉摇移", "镜头运动", "镜头语言", "分镜"],

        "negative_rules": ["镜头乱", "运镜飘", "节奏乱", "跳轴"],

        "prompt_text": "锁定镜头语言、机位逻辑与运动节奏，推拉摇移服务剧情，不突兀、不跳轴、不乱晃，确保镜头切换有叙事逻辑与电影感。",

    },

    {

        "id": "base-2",

        "title": "光线光影工程",

        "group": "base",

        "always_on": True,

        "priority": 10,

        "stages": ["script", "shot", "ref_image", "repair"],

        "tags": ["光线", "光影", "照明", "氛围", "层次"],

        "triggers": ["光线", "氛围", "ҹ", "逆光", "电影感"],

        "negative_rules": ["光影跳", "亮度乱", "忽明忽暗", "打光不统一"],

        "prompt_text": "统一主光、辅光与环境光逻辑，保持光比、方向、亮度和质感稳定，让人物与环境共享同一套可信的光影关系。",

    },

    {

        "id": "base-3",

        "title": "色彩色调影调工程",

        "group": "base",

        "always_on": True,

        "priority": 10,

        "stages": ["script", "shot", "ref_image", "repair"],

        "tags": ["ɫ", "ɫ", "Ӱ", "风格", "高级感"],

        "triggers": ["ɫ", "调色", "冷暖", "质感", "高级感"],

        "negative_rules": ["ɫ", "肤色飘", "串色", "影调不统一"],

        "prompt_text": "锁定整体色调、冷暖关系和影调层次，保持角色肤色、服装与场景配色统一，不出现突兀串色或风格跳变。",

    },

    {

        "id": "base-4",

        "title": "场景空间拓扑工程",

        "group": "base",

        "always_on": True,

        "priority": 9,

        "stages": ["script", "shot", "ref_image", "repair"],

        "tags": ["场景", "空间", "构图", "͸", "拓扑"],

        "triggers": ["场景", "构图", "空间关系", "͸", "布景"],

        "negative_rules": ["͸", "场景崩", "背景乱变", "空间不连贯"],

        "prompt_text": "保证场景空间关系、构图重心和透视逻辑稳定，前中后景清晰分层，背景不会无故变化，环境与人物始终处在同一世界观里。",

    },

    {

        "id": "base-5",

        "title": "人物面部体态工程",

        "group": "base",

        "always_on": True,

        "priority": 9,

        "stages": ["script", "shot", "ref_image", "repair"],

        "tags": ["人物", "面部", "体态", "表演", "神态"],

        "triggers": ["人物", "表情", "眼神", "神态", "演技"],

        "negative_rules": ["人物崩", "表情假", "五官畸变", "体态僵硬"],

        "prompt_text": "保持人物五官、脸型、眼神、姿态和情绪表达稳定可信，让角色的体态、视线和微表情与剧情心境一致，不僵硬、不崩坏。",

    },

    {

        "id": "base-6",

        "title": "单人/多人服化道工程",

        "group": "base",

        "always_on": True,

        "priority": 8,

        "stages": ["script", "shot", "ref_image", "repair"],

        "tags": ["服装", "造型", "道具", "人物一致性", "Ⱥ"],

        "triggers": ["服装", "造型", "道具", "多人", "ͬ"],

        "negative_rules": ["服装乱变", "造型跳", "道具消失", "多人抢戏"],

        "prompt_text": "锁定角色造型、服装、妆造和关键道具，多人同框时主次清晰、身份分明，避免造型跳变、道具错位和群像失控。",

    },

]



STAGE_SECTION_TITLES = {

    "script": "导演脚本提示词库",

    "shot": "镜头生成提示词库",

    "ref_image": "参考图提示词库",

    "repair": "返工修复提示词库",

}



KEYWORD_TAGS = {

    "运镜": ["运镜", "镜头", "机位", "调度"],

    "镜头": ["镜头", "分镜", "景别", "转场"],

    "转场": ["转场", "镜头", "节奏"],

    "色彩": ["色彩", "色调", "影调", "调色"],

    "氛围": ["氛围", "意境", "情绪", "沉浸感"],

    "天气": ["天气", "时辰", "季节", "环境"],

    "时空": ["时空", "连贯", "continuity", "场景"],

    "角色": ["角色", "人设", "人物", "一致性"],

    "人物": ["人物", "表演", "体态", "情绪"],

    "表情": ["表情", "眼神", "微表情", "神态"],

    "配音": ["配音", "口型", "声音", "对白"],

    "字幕": ["字幕", "版式", "排版", "信息层级"],

    "画面": ["画面", "帧间", "连贯", "稳定"],

    "广告": ["广告", "TVC", "商业", "转化"],

    "台词": ["台词", "对白", "说话风格", "表达"],

    "反派": ["反派", "压迫感", "威胁", "对峙"],

    "冲突": ["冲突", "对峙", "高能对白", "拉扯"],

    "国运": ["家国", "国运", "能力", "责任"],

}



STAGE_HINTS = {

    "script": {"台词", "对白", "剧情", "节奏", "分镜", "运镜", "角色", "伏笔", "广告", "合辑"},

    "shot": {"镜头", "运镜", "画面", "角色", "转场", "场景", "光影", "连贯", "人物"},

    "ref_image": {"构图", "场景", "人物", "角色", "色彩", "光影", "服装", "造型"},

    "repair": {"修", "返工", "崩", "乱", "跳", "畸变", "不稳", "合辑"},

}



_lock = threading.Lock()

_config_cache: dict | None = None

_library_cache: list["PromptLibrary"] | None = None

_quick_index_cache: dict | None = None

_context_vocab_cache: dict | None = None





@dataclass

class PromptLibrary:

    id: str

    title: str

    prompt_text: str

    trigger: str = ""

    manage: str = ""

    tags: list[str] = field(default_factory=list)

    triggers: list[str] = field(default_factory=list)

    route_tags: list[str] = field(default_factory=list)

    route_triggers: list[str] = field(default_factory=list)

    route_negative_terms: list[str] = field(default_factory=list)

    stages: list[str] = field(default_factory=lambda: ["script", "shot", "ref_image", "repair"])

    priority: int = 3

    negative_rules: list[str] = field(default_factory=list)

    group: str = "specialized"

    always_on: bool = False

    enabled: bool = True

    source: str = "legacy"

    source_file: str = ""

    library_family: str = ""

    library_cluster: str = ""

    parent_library: str = ""

    governance_level: str = ""

    dimensions: dict[str, list[str]] = field(default_factory=dict)

    slot_hints: dict[str, list[str]] = field(default_factory=dict)

    search_profile: dict[str, object] = field(default_factory=dict)

    render_profile: dict[str, object] = field(default_factory=dict)



    def __post_init__(self) -> None:

        self.route_tags = _merge_terms(self.route_tags or self.tags)

        self.route_triggers = _merge_terms(self.route_triggers or self.triggers)

        self.route_negative_terms = _merge_terms(self.route_negative_terms)



    def to_dict(self) -> dict:

        return asdict(self)





def _normalize_stage(stage: str | None) -> str:

    stage_name = (stage or "script").strip().lower()

    if stage_name not in DEFAULT_TOP_K:

        return "script"

    return stage_name





def _load_config() -> dict:

    global _config_cache

    if _config_cache is not None:

        return _config_cache

    if PROMPT_LIB_INDEX_FILE.exists():

        _config_cache = json.loads(PROMPT_LIB_INDEX_FILE.read_text(encoding="utf-8"))

    else:

        _config_cache = {}

    return _config_cache





def _settings() -> dict:

    return _load_config().get("settings", {})





def _load_context_vocab() -> dict:

    global _context_vocab_cache

    if _context_vocab_cache is not None:

        return _context_vocab_cache

    if PROMPT_LIB_CONTEXT_VOCAB_FILE.exists():

        _context_vocab_cache = json.loads(PROMPT_LIB_CONTEXT_VOCAB_FILE.read_text(encoding="utf-8"))

    else:

        _context_vocab_cache = {"format_order": [], "max_items_per_dimension": 2, "vocab": {}, "failure_mode_map": {}}

    return _context_vocab_cache





def get_context_vocab() -> dict:

    return _load_context_vocab()





def _load_local_entries() -> list[dict]:

    entries: list[dict] = []

    for path in (

        PROMPT_LIB_LOCAL_ENTRIES_FILE,

        PROMPT_LIB_BENCHMARK_ENTRIES_FILE,

        PROMPT_LIB_BENCHMARK_TABOO_ENTRIES_FILE,

        PROMPT_LIB_SHORT_VIDEO_ENTRIES_FILE,

        PROMPT_LIB_SHORT_VIDEO_ENTRIES_FILE_61_90,

        PROMPT_LIB_EYE_EXPRESSION_ENTRIES_FILE,

        PROMPT_LIB_DEMEANOR_EXPRESSION_ENTRIES_FILE,

        PROMPT_LIB_INNER_CORE_ENTRIES_FILE,

        PROMPT_LIB_EMOTION_EXPRESSION_ENTRIES_FILE,

        PROMPT_LIB_ULTIMATE_SOUL_ENTRIES_FILE,

        PROMPT_LIB_NINE_LAYER_SOUL_ENTRIES_FILE,

    ):

        if not path.exists():

            continue

        data = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, list):

            entries.extend(item for item in data if isinstance(item, dict))

    return entries





def _context_mode() -> str:

    env_mode = os.getenv("PROMPT_CONTEXT_MODE", "").strip().lower()

    if env_mode in {"off", "strict", "enhanced"}:

        return env_mode

    return str(_settings().get("context_mode", "enhanced")).strip().lower() or "enhanced"





def _stage_weights(stage: str) -> dict:

    custom = _settings().get("stage_context_weights", {})

    merged = dict(DEFAULT_STAGE_WEIGHTS.get(stage, DEFAULT_STAGE_WEIGHTS["script"]))

    merged.update(custom.get(stage, {}))

    return merged





def _group_limit(group: str) -> int | None:

    custom = _settings().get("group_limits", {})

    merged = dict(DEFAULT_GROUP_LIMITS)

    merged.update(custom)

    limit = merged.get(group)

    return int(limit) if limit else None





def _extract_standard_context(raw_text: str) -> dict[str, list[str]]:

    vocab = _load_context_vocab()

    values = vocab.get("vocab", {})

    max_items = int(vocab.get("max_items_per_dimension", 2) or 2)

    text = str(raw_text or "")

    selected: dict[str, list[str]] = {}

    for dim_name, options in values.items():

        hits: list[str] = []

        for option in options:

            if option in text and option not in hits:

                hits.append(option)

            if len(hits) >= max_items:

                break

        if hits:

            selected[dim_name] = hits

    return selected





def build_standard_context_text(raw_text: str) -> str:

    vocab = _load_context_vocab()

    order = vocab.get("format_order", [])

    selected = _extract_standard_context(raw_text)

    blocks: list[str] = []

    for dim_name in order:

        values = selected.get(dim_name, [])

        if values:

            blocks.append("".join(values) if dim_name == "题材" else "/".join(values))

    return " + ".join(blocks)





def _normalize_context_text(raw_text: str) -> str:

    standardized = build_standard_context_text(raw_text)

    return standardized or str(raw_text or "").strip()





def _expand_failure_mode(raw_text: str) -> str:

    vocab = _load_context_vocab()

    failure_map = vocab.get("failure_mode_map", {})

    text = str(raw_text or "").strip()

    extras: list[str] = []

    for trigger, mapped in failure_map.items():

        if trigger and trigger in text:

            for item in mapped:

                if item not in extras:

                    extras.append(item)

    return "；".join([part for part in [text, " / ".join(extras)] if part])





def _parse_quick_index_markdown() -> dict:

    if not PROMPT_LIB_QUICK_INDEX_FILE.exists():

        return {"topics": [], "scenes": [], "problems": []}

    sections = {
        "按题材找库": "topics",
        "按场景找库": "scenes",
        "按常见问题找库": "problems",
    }
    current: str | None = None

    parsed = {"topics": [], "scenes": [], "problems": []}

    for raw_line in PROMPT_LIB_QUICK_INDEX_FILE.read_text(encoding="utf-8").splitlines():

        line = raw_line.strip()

        if line.startswith("## "):

            current = sections.get(line[3:])

            continue

        if not current or not line.startswith("- **"):

            continue

        match = re.match(r"- \*\*(.+?)\*\*：(.*)$", line)

        if not match:

            continue

        label = match.group(1).strip()

        libs_text = match.group(2).strip()

        library_ids: list[str] = []

        libraries: list[dict] = []

        for item in libs_text.split("；"):

            item = item.strip()

            lib_match = re.match(r"([^\.]+)\.\s+(.+)$", item)

            if not lib_match:

                continue

            library_id = lib_match.group(1).strip()

            title = lib_match.group(2).strip()

            library_ids.append(library_id)

            libraries.append({"id": library_id, "title": title})

        parsed[current].append(

            {

                "label": label,

                "count": len(library_ids),

                "library_ids": library_ids,

                "libraries": libraries,

            }

        )

    return parsed





def get_quick_index() -> dict:

    global _quick_index_cache

    if _quick_index_cache is not None:

        return _quick_index_cache

    _quick_index_cache = _parse_quick_index_markdown()

    return _quick_index_cache





def _resolve_filtered_library_ids(filter_mode: str = "", filter_value: str = "") -> set[str] | None:

    mode = (filter_mode or "").strip().lower()

    value = (filter_value or "").strip()

    if not mode or not value:

        return None

    aliases = {

        "topic": "topics",

        "topics": "topics",

        "scene": "scenes",

        "scenes": "scenes",

        "problem": "problems",

        "problems": "problems",

    }

    section = aliases.get(mode)

    if section:

        quick_index = get_quick_index()

        for item in quick_index.get(section, []):

            if item["label"] == value:

                return set(item.get("library_ids", []))



    metadata = _load_metadata_overrides()

    metadata_aliases = {

        "family": "library_family",

        "library_family": "library_family",

        "cluster": "library_cluster",

        "library_cluster": "library_cluster",

        "parent": "parent_library",

        "parent_library": "parent_library",

        "source_file": "source_file",

        "source": "source_file",

        "level": "governance_level",

        "governance_level": "governance_level",

        "group": "group",

        "stage": "stages",

        "id": "id",

        "title": "title",

    }

    field_name = metadata_aliases.get(mode)

    if not field_name:

        return None



    matched_ids: set[str] = set()

    for library_id, item in metadata.items():

        field_value = item.get(field_name)

        if isinstance(field_value, list):

            if value in {str(v).strip() for v in field_value if str(v).strip()}:

                matched_ids.add(library_id)

            continue

        if str(field_value or "").strip() == value:

            matched_ids.add(library_id)

    return matched_ids or None





def resolve_filtered_library_ids(filter_mode: str = "", filter_value: str = "") -> set[str] | None:

    return _resolve_filtered_library_ids(filter_mode, filter_value)





def get_library_filters() -> dict:

    metadata = list(_load_metadata_overrides().values())



    def _sorted_values(field_name: str) -> list[dict]:

        counts: dict[str, int] = {}

        for item in metadata:

            raw = item.get(field_name)

            values = raw if isinstance(raw, list) else [raw]

            for value in values:

                normalized = str(value or "").strip()

                if not normalized:

                    continue

                counts[normalized] = counts.get(normalized, 0) + 1

        return [

            {"value": key, "count": counts[key]}

            for key in sorted(counts.keys(), key=lambda x: (-counts[x], x))

        ]



    return {

        "total": len(metadata),

        "modes": {

            "topics": get_quick_index().get("topics", []),

            "scenes": get_quick_index().get("scenes", []),

            "problems": get_quick_index().get("problems", []),

            "library_family": _sorted_values("library_family"),

            "library_cluster": _sorted_values("library_cluster"),

            "parent_library": _sorted_values("parent_library"),

            "source_file": _sorted_values("source_file"),

            "governance_level": _sorted_values("governance_level"),

            "group": _sorted_values("group"),

            "stages": _sorted_values("stages"),

        },

    }





def _load_metadata_overrides() -> dict[str, dict]:

    if not PROMPT_LIB_METADATA_FILE.exists():

        return {}

    data = json.loads(PROMPT_LIB_METADATA_FILE.read_text(encoding="utf-8"))

    if isinstance(data, list):

        return {str(item["id"]): item for item in data if isinstance(item, dict) and item.get("id") is not None}

    if isinstance(data, dict):

        entries = data.get("libraries", [])

        return {str(item["id"]): item for item in entries if isinstance(item, dict) and item.get("id") is not None}

    return {}





def _split_terms(value: str) -> list[str]:

    if not value:

        return []

    raw = re.split(r"[\s,，。；;、|：（）()\[\]【】]+", value)

    terms = []

    for item in raw:

        term = item.strip().lower()

        if len(term) >= 2:

            terms.append(term)

    return list(dict.fromkeys(terms))





def _extract_cjk_ngrams(text: str, min_len: int = 2, max_len: int = 4) -> list[str]:

    grams: list[str] = []

    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):

        limit = len(chunk)

        for size in range(min_len, min(max_len, limit) + 1):

            for start in range(0, limit - size + 1):

                gram = chunk[start:start + size]

                if gram not in grams:

                    grams.append(gram)

    return grams





def _extract_query_terms(*parts: str) -> set[str]:

    text = " ".join(part for part in parts if part).lower()

    terms = set(_split_terms(text))

    for item in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_-]{2,}", text):

        terms.add(item.lower())

    for gram in _extract_cjk_ngrams(text):

        terms.add(gram.lower())

    return terms





def _merge_terms(*groups: list[str]) -> list[str]:

    merged: list[str] = []

    for group in groups:

        for item in group:

            value = item.strip()

            if value and value not in merged:

                merged.append(value)

    return merged





def _list_terms(values: list[object] | tuple[object, ...] | None) -> list[str]:

    if not values:

        return []

    return _merge_terms([str(value).strip() for value in values if str(value).strip()])





def _is_visual_brief(*parts: str) -> bool:

    text = " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())

    if not text:

        return False

    request_terms = ("生成", "视频", "剧本", "分镜", "画面", "镜头", "短片", "拍摄", "广告", "tvc")

    subject_terms = ("美女", "女生", "女孩", "女人", "长发", "短发", "骨感", "自拍", "裙子", "外景", "街头", "人物", "场景")

    story_terms = ("分手", "重逢", "误会", "剧情", "对白", "台词", "冲突", "告白", "挽留", "悬疑", "复仇", "章节", "设定")

    detail_terms = (
        "回眸", "侧脸", "特写", "近景", "远景", "全景", "光线", "柔光", "逆光", "构图", "骑行",
        "奔跑", "长发", "风吹", "穿搭", "妆容", "裙摆", "城市", "街道", "江边", "滨江", "wink",
    )

    has_request = any(term in text for term in request_terms)
    has_subject = any(term in text for term in subject_terms)
    detail_hits = sum(1 for term in detail_terms if term in text)
    is_descriptive_visual = len(text) >= 28 and detail_hits >= 2

    return (has_request and (has_subject or detail_hits >= 1) and not any(term in text for term in story_terms)) or (is_descriptive_visual and not any(term in text for term in story_terms))





def _apply_search_profiles(merged: dict) -> dict:

    search_profile = merged.get("search_profile") if isinstance(merged.get("search_profile"), dict) else {}

    render_profile = merged.get("render_profile") if isinstance(merged.get("render_profile"), dict) else {}

    migrated_terms = set(_list_terms(render_profile.get("migrate_terms_from_search")))

    route_tags = [term for term in merged.get("route_tags") or merged.get("tags", []) if term not in migrated_terms]

    route_triggers = [term for term in merged.get("route_triggers") or merged.get("triggers", []) if term not in migrated_terms]

    positive_triggers = _list_terms(search_profile.get("positive_triggers"))

    if positive_triggers:

        route_triggers = positive_triggers

        route_tags = _merge_terms(route_tags, [term for term in positive_triggers if term not in migrated_terms])

    merged["route_tags"] = _merge_terms(route_tags or merged.get("tags", []))

    merged["route_triggers"] = _merge_terms(route_triggers or merged.get("triggers", []))

    merged["route_negative_terms"] = _merge_terms(

        merged.get("route_negative_terms", []),

        _list_terms(search_profile.get("negative_trigger_suggestions")),

    )

    return merged





def _parse_legacy_prompts() -> list[dict]:

    if not LEGACY_SCENE_FILE.exists():

        return []

    text = LEGACY_SCENE_FILE.read_text(encoding="utf-8")

    pattern = re.compile(r"##\s+(\d+)\.\s+(.+?)\n(.*?)(?=\n##\s+\d+\.|\Z)", re.DOTALL)

    prompts: list[dict] = []

    for match in pattern.finditer(text):

        number = match.group(1)

        title = match.group(2).strip()

        body = match.group(3).strip()

        code_match = re.search(r"```\n(.*?)```", body, re.DOTALL)

        prompt_text = code_match.group(1).strip() if code_match else body

        trigger_match = re.search(r"触发条件[:：]\s*(.+?)(?:\n|$)", body)

        manage_match = re.search(r"管住[:：]\s*(.+?)(?:\n|$)", body)

        trigger = trigger_match.group(1).strip() if trigger_match else ""

        manage = manage_match.group(1).strip() if manage_match else ""

        prompts.append(

            {

                "id": number,

                "title": title,

                "prompt_text": prompt_text,

                "trigger": trigger,

                "manage": manage,

            }

        )

    return prompts





def _infer_tags(title: str, trigger: str, manage: str) -> list[str]:

    source = f"{title} {trigger} {manage}"

    tags: list[str] = []

    for keyword, inferred in KEYWORD_TAGS.items():

        if keyword in source:

            tags = _merge_terms(tags, inferred)

    if not tags:

        tags = _merge_terms(tags, _split_terms(title))

    return tags





def _infer_stages(title: str, tags: list[str]) -> list[str]:

    source = f"{title} {' '.join(tags)}"

    stages: list[str] = []

    for stage, hints in STAGE_HINTS.items():

        if any(hint in source for hint in hints):

            stages.append(stage)

    if not stages:

        stages = ["script", "shot", "repair"]

    if "台词" not in source and "对白" not in source and "配音" not in source and "字幕" not in source:

        if "ref_image" not in stages and any(tag in source for tag in ("人物", "角色", "场景", "光影", "色彩", "服装", "造型", "镜头")):

            stages.append("ref_image")

    return list(dict.fromkeys(stages))





def _infer_group(title: str, tags: list[str]) -> str:

    source = f"{title} {' '.join(tags)}"

    if any(item in source for item in ("广告", "TVC", "风格", "影调", "色彩", "氛围")):

        return "style"

    if any(item in source for item in ("台词", "对白", "配音", "字幕")):

        return "dialogue"

    if any(item in source for item in ("角色", "人物", "表演", "人设")):

        return "character"

    if any(item in source for item in ("转场", "分镜", "运镜", "画幅", "画面", "镜头")):

        return "shot"

    return "specialized"





def _build_legacy_library(item: dict, override: dict | None = None) -> PromptLibrary:

    inferred_tags = _infer_tags(item["title"], item.get("trigger", ""), item.get("manage", ""))

    inferred_triggers = _merge_terms(_split_terms(item.get("trigger", "")), inferred_tags)

    merged = {

        "id": item["id"],

        "title": item["title"],

        "prompt_text": item["prompt_text"],

        "trigger": item.get("trigger", ""),

        "manage": item.get("manage", ""),

        "tags": inferred_tags,

        "triggers": inferred_triggers,

        "route_tags": inferred_tags,

        "route_triggers": inferred_triggers,

        "route_negative_terms": [],

        "stages": _infer_stages(item["title"], inferred_tags),

        "priority": 3,

        "negative_rules": _split_terms(item.get("manage", "")),

        "group": _infer_group(item["title"], inferred_tags),

        "always_on": False,

        "enabled": True,

        "source": "legacy_markdown",

        "source_file": str(item.get("source_file", "")).strip(),

        "library_family": str(item.get("library_family", "")).strip(),

        "library_cluster": str(item.get("library_cluster", "")).strip(),

        "parent_library": str(item.get("parent_library", "")).strip(),

        "governance_level": str(item.get("governance_level", "")).strip(),

        "dimensions": {},

        "search_profile": {},

        "render_profile": {},

    }

    if override:

        for key, value in override.items():

            if key in {"tags", "triggers", "stages", "negative_rules"}:

                merged[key] = _merge_terms(merged.get(key, []), value)

            elif key == "dimensions":

                merged[key] = value

                flattened = []

                for dim_name, dim_values in value.items():

                    if dim_name == "禁忌项":

                        merged["negative_rules"] = _merge_terms(merged.get("negative_rules", []), dim_values)

                    elif dim_name == "适用创作阶段":

                        merged["stages"] = _merge_terms(merged.get("stages", []), dim_values)

                    else:

                        flattened = _merge_terms(flattened, dim_values)

                merged["tags"] = _merge_terms(merged.get("tags", []), flattened)

            else:

                merged[key] = value

    return PromptLibrary(**_apply_search_profiles(merged))





def _build_local_library(item: dict, override: dict | None = None) -> PromptLibrary:

    merged = {

        "id": str(item["id"]),

        "title": str(item["title"]).strip(),

        "prompt_text": str(item.get("prompt_text", "")).strip(),

        "trigger": str(item.get("trigger", "")).strip(),

        "manage": str(item.get("manage", "")).strip(),

        "tags": _merge_terms([str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()]),

        "triggers": _merge_terms([str(tag).strip() for tag in item.get("triggers", []) if str(tag).strip()]),

        "route_tags": _merge_terms([str(tag).strip() for tag in item.get("route_tags", item.get("tags", [])) if str(tag).strip()]),

        "route_triggers": _merge_terms([str(tag).strip() for tag in item.get("route_triggers", item.get("triggers", [])) if str(tag).strip()]),

        "route_negative_terms": _merge_terms([str(tag).strip() for tag in item.get("route_negative_terms", []) if str(tag).strip()]),

        "stages": _merge_terms([str(stage).strip() for stage in item.get("stages", []) if str(stage).strip()]) or ["script", "shot", "ref_image", "repair"],

        "priority": int(item.get("priority", 5)),

        "negative_rules": _merge_terms([str(rule).strip() for rule in item.get("negative_rules", []) if str(rule).strip()]),

        "group": str(item.get("group", "specialized")).strip() or "specialized",

        "always_on": bool(item.get("always_on", False)),

        "enabled": bool(item.get("enabled", True)),

        "source": str(item.get("source", "local_json")).strip() or "local_json",

        "source_file": str(item.get("source_file", item.get("_source_file", ""))).strip(),

        "library_family": str(item.get("library_family", "")).strip(),

        "library_cluster": str(item.get("library_cluster", "")).strip(),

        "parent_library": str(item.get("parent_library", "")).strip(),

        "governance_level": str(item.get("governance_level", "")).strip(),

        "dimensions": {

            str(dim): [str(value).strip() for value in values if str(value).strip()]

            for dim, values in (item.get("dimensions", {}) or {}).items()

            if isinstance(values, list)

        },

        "slot_hints": {

            str(slot): [str(value).strip() for value in values if str(value).strip()]

            for slot, values in (item.get("slot_hints", {}) or {}).items()

            if isinstance(values, list)

        },

        "search_profile": dict(item.get("search_profile", {}) or {}),

        "render_profile": dict(item.get("render_profile", {}) or {}),

    }

    if override:

        for key, value in override.items():

            if key in {"tags", "triggers", "stages", "negative_rules"}:

                merged[key] = _merge_terms(merged.get(key, []), value)

            elif key in {"dimensions", "slot_hints"} and isinstance(value, dict):

                existing = dict(merged.get(key, {}))

                for name, values in value.items():

                    existing[str(name)] = _merge_terms(existing.get(str(name), []), [str(v).strip() for v in values if str(v).strip()])

                merged[key] = existing

            else:

                merged[key] = value

    return PromptLibrary(**_apply_search_profiles(merged))





def _build_base_libraries() -> list[PromptLibrary]:

    libraries: list[PromptLibrary] = []

    for item in BASE_PROMPT_LIBRARY:

        libraries.append(PromptLibrary(**item, source="base_library"))

    return libraries





def _load_libraries() -> list[PromptLibrary]:

    global _library_cache

    if _library_cache is not None:

        return _library_cache

    with _lock:

        if _library_cache is not None:

            return _library_cache

        config = _load_config()

        overrides = config.get("overrides", {})

        metadata_overrides = _load_metadata_overrides()

        libraries = _build_base_libraries()

        for item in _parse_legacy_prompts():

            merged_override = dict(metadata_overrides.get(str(item["id"]), {}))

            merged_override.update(overrides.get(str(item["id"]), {}))

            libraries.append(_build_legacy_library(item, merged_override))

        for item in _load_local_entries():

            merged_override = dict(metadata_overrides.get(str(item["id"]), {}))

            merged_override.update(overrides.get(str(item["id"]), {}))

            libraries.append(_build_local_library(item, merged_override))

        _library_cache = [library for library in libraries if library.enabled]

        return _library_cache





def _count_phrase_hits(text: str, phrases: list[str]) -> int:

    return sum(1 for phrase in phrases if phrase and phrase.lower() in text)





DOMAIN_CATEGORY_TERMS = {

    "urban_emotion": ["都市", "写字楼", "电梯", "雨夜", "分手", "情感", "克制", "留白", "自拍", "情侣"],

    "fantasy_costume": ["古风", "仙侠", "古装", "修仙", "仙门", "江湖", "武侠", "朝堂", "后宫"],

    "family_child": ["亲子", "绘本", "儿童", "童话", "家庭温情", "母子", "父子", "宝宝"],

    "tourism_landscape": ["文旅", "风景", "航拍", "山河", "自然风光", "旅行大片", "景区"],

    "anime_comic": ["漫剧", "二次元", "动漫", "漫画", "日系", "动画感"],

    "vlog_lifestyle": ["vlog", "日常", "治愈生活", "探店", "生活", "记录"],

}





def _detect_domain_categories(text: str) -> set[str]:

    normalized_text = str(text or "").lower()

    categories: set[str] = set()

    for key, terms in DOMAIN_CATEGORY_TERMS.items():

        if any(str(term).strip().lower() in normalized_text for term in terms if str(term).strip()):

            categories.add(key)

    return categories





def _is_match_compatible(*, active_categories: set[str], blob: str, title: str = "", tags: list[str] | None = None, prompt_text: str = "") -> bool:

    candidate_blob = f"{title}{''.join(tags or [])}{prompt_text}"

    candidate_categories = _detect_domain_categories(candidate_blob)

    if active_categories and candidate_categories and active_categories.isdisjoint(candidate_categories):

        return False

    if any(term in candidate_blob for term in ("TVC", "广告", "商业广告")) and not any(term in blob for term in ("广告", "商业", "tvc", "品牌", "宣传")):

        return False

    if any(term in candidate_blob for term in ("文旅", "风景大片", "景区", "旅拍")) and "tourism_landscape" not in active_categories:

        return False

    if any(term in candidate_blob for term in ("配音", "漫剧配音", "旁白", "独白", "字幕分配")) and not any(term in blob for term in ("配音", "旁白", "独白", "字幕", "口播")):

        return False

    return True





def _stage_bonus(library: PromptLibrary, stage: str) -> float:

    if stage in library.stages:

        return 1.6

    if "all" in library.stages:

        return 1.0

    return -1.2





def _score_library(

    library: PromptLibrary,

    *,

    query: str,

    stage: str,

    context: str = "",

    global_context: str = "",

    local_context: str = "",

    failure_mode: str = "",

) -> float:

    mode = _context_mode()

    normalized_global_context = _normalize_context_text(global_context or context)

    normalized_local_context = _normalize_context_text(local_context)

    normalized_failure_mode = _expand_failure_mode(failure_mode)

    if mode in {"off", "strict"}:

        normalized_global_context = ""

        normalized_local_context = ""

        normalized_failure_mode = failure_mode if mode == "strict" else ""

    blob = " ".join(part for part in (query, normalized_global_context, normalized_local_context, normalized_failure_mode) if part).lower()

    global_blob = normalized_global_context.lower()

    local_blob = normalized_local_context.lower()

    is_visual_brief = _is_visual_brief(query, normalized_global_context, normalized_local_context)

    active_categories = _detect_domain_categories(" ".join(part for part in (query, normalized_global_context, normalized_local_context) if part))

    library_categories = _detect_domain_categories(" ".join([

        library.title,

        " ".join(library.route_tags),

        " ".join(library.route_triggers),

    ]))

    weights = _stage_weights(stage)

    query_terms = _extract_query_terms(query, normalized_global_context, normalized_local_context, normalized_failure_mode)

    score = library.priority * 0.35 + _stage_bonus(library, stage)

    score += min(_count_phrase_hits(query.lower(), library.route_triggers), 4) * 2.0 * weights["query"]

    score += min(_count_phrase_hits(query.lower(), library.route_tags), 4) * 1.0 * weights["query"]

    if global_blob:

        score += min(_count_phrase_hits(global_blob, library.route_triggers), 4) * 0.9 * weights["global"]

        score += min(_count_phrase_hits(global_blob, library.route_tags), 4) * 0.7 * weights["global"]

    if local_blob:

        score += min(_count_phrase_hits(local_blob, library.route_triggers), 4) * 0.9 * weights["local"]

        score += min(_count_phrase_hits(local_blob, library.route_tags), 4) * 0.7 * weights["local"]

    title_terms = set(_split_terms(library.title)) | set(_extract_cjk_ngrams(library.title.lower()))

    score += min(len(title_terms & query_terms), 3) * 1.3

    negative_terms = _merge_terms(library.negative_rules, _split_terms(library.manage))

    if normalized_failure_mode:

        score += min(_count_phrase_hits(normalized_failure_mode.lower(), negative_terms), 3) * weights["failure"]

    style_theme_terms = _merge_terms(library.route_tags, library.route_triggers, _split_terms(library.title))

    library_blob = f"{library.title}{''.join(library.tags)}{''.join(library.triggers)}"

    if stage == "shot" and library.group == "dialogue":

        if not any(term in blob for term in ("台词", "对白", "旁白", "口播", "说话", "配音")):

            score -= 3.2

    if stage == "shot" and is_visual_brief:

        if library.source_file in {

            "ultimate_soul_entries.json",

            "nine_layer_soul_entries.json",

            "inner_core_entries.json",

            "shot_benchmark_entries.json",

            "shot_benchmark_taboo_entries_31_50.json",

        }:

            score -= 4.8

    if stage == "shot" and "字幕" in f"{library.title}{''.join(library.tags)}":

        if not any(term in blob for term in ("字幕", "字卡", "文案", "口播")):

            score -= 1.5

    if stage == "ref_image" and library.group == "dialogue":

        if not any(term in blob for term in ("海报", "字卡", "字幕", "口播", "台词", "对白", "配音")):

            score -= 3.2

    if stage == "ref_image" and any(term in f"{library.title}{''.join(library.tags)}" for term in ("配音", "字幕", "旁白", "独白", "对白")):

        if not any(term in blob for term in ("海报", "字卡", "字幕", "口播", "台词", "对白", "配音")):

            score -= 2.4

    if library.group == "style":

        if global_blob:

            score += min(_count_phrase_hits(global_blob, style_theme_terms), 4) * weights["style"]

        if local_blob:

            score += min(_count_phrase_hits(local_blob, style_theme_terms), 4) * 0.8

        has_style_intent = any(term in blob for term in ("风格", "色调", "氛围", "广告", "tvc", "质感"))

        has_theme_context = (global_blob or local_blob) and any(term.lower() in f"{global_blob} {local_blob}" for term in style_theme_terms)

        if not has_style_intent and not has_theme_context:

            score -= 0.8

    if library.group == "dialogue" and stage == "ref_image":

        score -= 2.5

    if library.route_negative_terms:

        score -= min(_count_phrase_hits(blob, library.route_negative_terms), 3) * 2.4

    if active_categories and library_categories and active_categories.isdisjoint(library_categories):

        score -= 3.6

    if any(term in library_blob for term in ("TVC", "广告", "商业广告")):

        if not any(term in blob for term in ("广告", "商业", "tvc", "品牌", "宣传")):

            score -= 2.8

    if any(term in library_blob for term in ("文旅", "风景大片", "景区", "旅拍")):

        if "tourism_landscape" not in active_categories:

            score -= 3.2

    if any(term in library_blob for term in ("配音", "漫剧配音", "旁白", "独白", "字幕分配")):

        if not any(term in blob for term in ("配音", "旁白", "独白", "字幕", "口播")):

            score -= 3.0

    if stage == "script" and is_visual_brief:

        if any(term in library_blob for term in ("结构", "开场", "前三秒", "钩子", "推进", "节奏", "分镜")):

            score += 3.4

        if library.source_file in {

            "ultimate_soul_entries.json",

            "nine_layer_soul_entries.json",

            "inner_core_entries.json",

            "eye_expression_entries.json",

            "demeanor_expression_entries.json",

            "emotion_expression_entries.json",

        }:

            score -= 4.2

    if library.always_on:

        score += 3.0

    return round(score, 4)





def _default_top_k(stage: str) -> int:

    top_k = _settings().get("default_top_k", {})

    return int(top_k.get(stage, DEFAULT_TOP_K[stage]))





def _default_base_limit(stage: str) -> int:

    limits = _settings().get("base_limits", {})

    return int(limits.get(stage, DEFAULT_BASE_LIMITS[stage]))





def _style_limit() -> int:

    return int(_settings().get("style_library_limit", 2))





def _match_to_dict(library: PromptLibrary, score: float) -> dict:

    return {

        "id": library.id,

        "name": library.title,

        "prompt_text": library.prompt_text,

        "trigger": library.trigger,

        "manage": library.manage,

        "score": score,

        "group": library.group,

        "tags": library.tags,

        "stages": library.stages,

        "always_on": library.always_on,

        "source": library.source,

        "source_file": library.source_file,

        "library_family": library.library_family,

        "library_cluster": library.library_cluster,

        "parent_library": library.parent_library,

        "governance_level": library.governance_level,

        "dimensions": library.dimensions,

        "slot_hints": library.slot_hints,

    }





def _log_retrieval(

    *,

    stage: str,

    query: str,

    global_context: str,

    local_context: str,

    failure_mode: str,

    matched: list[dict],

    near_miss: list[dict],

) -> None:

    try:

        PROMPT_RETRIEVAL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        payload = {

            "timestamp": datetime.now().isoformat(timespec="seconds"),

            "stage": stage,

            "context_mode": _context_mode(),

            "query": query,

            "global_context": global_context,

            "local_context": local_context,

            "failure_mode": failure_mode,

            "matched": [{"id": item["id"], "name": item["name"], "score": item["score"]} for item in matched[:8]],

            "near_miss": [{"id": item["id"], "name": item["name"], "score": item["score"]} for item in near_miss[:5]],

        }

        with PROMPT_RETRIEVAL_LOG_FILE.open("a", encoding="utf-8") as handle:

            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    except Exception:

        return





def retrieve_prompt_matches(

    query: str,

    *,

    stage: str = "script",

    top_k: int | None = None,

    context: str = "",

    global_context: str = "",

    local_context: str = "",

    failure_mode: str = "",

    include_base: bool = False,

    library_ids: set[str] | None = None,

) -> dict:

    stage_name = _normalize_stage(stage)

    global_context = global_context or context

    libraries = _load_libraries()

    scored: list[tuple[PromptLibrary, float]] = []

    for library in libraries:

        score = _score_library(

            library,

            query=query,

            stage=stage_name,

            context=context,

            global_context=global_context,

            local_context=local_context,

            failure_mode=failure_mode,

        )

        scored.append((library, score))

    scored.sort(key=lambda item: (item[1], item[0].priority, item[0].title), reverse=True)



    base_candidates = [item for item in scored if item[0].always_on and stage_name in item[0].stages]

    base_selected = base_candidates[: _default_base_limit(stage_name)]



    specialized_selected: list[tuple[PromptLibrary, float]] = []

    style_count = 0

    group_counts: dict[str, int] = {}

    limit = top_k if top_k is not None else _default_top_k(stage_name)

    for library, score in scored:

        if library.always_on:

            continue

        if library_ids is not None and library.id not in library_ids:

            continue

        if stage_name not in library.stages and "all" not in library.stages:

            continue

        if library.group == "style" and style_count >= _style_limit():

            continue

        group_limit = _group_limit(library.group)

        if group_limit is not None and group_counts.get(library.group, 0) >= group_limit:

            continue

        if library.group == "style":

            style_count += 1

        group_counts[library.group] = group_counts.get(library.group, 0) + 1

        specialized_selected.append((library, score))

        if len(specialized_selected) >= limit:

            break



    if not specialized_selected:

        fallback = [item for item in scored if not item[0].always_on][:limit]

        specialized_selected = fallback



    matched_list = [_match_to_dict(library, score) for library, score in specialized_selected]



    try:

        blob = " ".join(p for p in (query, global_context, local_context) if p).lower()

        active_categories = _detect_domain_categories(blob)

        is_visual_brief = _is_visual_brief(query, global_context, local_context)

        if not (stage_name == "shot" and is_visual_brief):

            from ..vector_store import search as vector_search

            vector_results = vector_search(query, top_k=limit, library_ids=library_ids)

            existing_ids = {m["id"] for m in matched_list}

            for vr in vector_results:

                min_vector_score = 4.4 if stage_name == "shot" and is_visual_brief else 4.2 if stage_name == "script" and is_visual_brief else 3.5

                if vr["id"] not in existing_ids and vr["score"] > min_vector_score:

                    if stage_name in {"script", "shot"} and is_visual_brief and str(vr.get("source_file", "")) in {

                        "ultimate_soul_entries.json",

                        "nine_layer_soul_entries.json",

                        "inner_core_entries.json",

                        "shot_benchmark_entries.json",

                        "shot_benchmark_taboo_entries_31_50.json",

                        "eye_expression_entries.json",

                        "demeanor_expression_entries.json",

                        "emotion_expression_entries.json",

                    }:

                        continue

                    if not _is_match_compatible(

                        active_categories=active_categories,

                        blob=blob,

                        title=str(vr.get("name", "")),

                        tags=vr.get("tags", []) or [],

                        prompt_text=str(vr.get("prompt_text", "")),

                    ):

                        continue

                    matched_list.append(vr)

                    existing_ids.add(vr["id"])

                    if len(matched_list) >= limit * 2:

                        break

            matched_list.sort(key=lambda x: x.get("score", 0), reverse=True)

            matched_list = matched_list[:limit]

    except Exception:

        pass



    result = {

        "stage": stage_name,

        "base": [_match_to_dict(library, score) for library, score in base_selected] if include_base else [],

        "matched": matched_list,

        "global_context": _normalize_context_text(global_context),

        "local_context": _normalize_context_text(local_context),

        "failure_mode": _expand_failure_mode(failure_mode),

    }

    _log_retrieval(

        stage=stage_name,

        query=query,

        global_context=result["global_context"],

        local_context=result["local_context"],

        failure_mode=result["failure_mode"],

        matched=result["matched"],

        near_miss=[_match_to_dict(library, score) for library, score in scored if library.id not in {item['id'] for item in result['matched'][:10]}][:5],

    )

    return result





def _format_prompt_block(title: str, matches: list[dict]) -> str:

    blocks: list[str] = []

    for item in matches:

        header = item["name"]

        if item.get("tags"):

            header = f"{header}｜{' / '.join(item['tags'][:4])}"

        blocks.append(f"【{header}】\n{item['prompt_text']}")

    if not blocks:

        return ""

    return f"## {title}\n\n" + "\n\n".join(blocks)





def build_prompt_package(

    query: str,

    *,

    stage: str = "script",

    base_prompt: str = "",

    top_k: int | None = None,

    context: str = "",

    global_context: str = "",

    local_context: str = "",

    failure_mode: str = "",

    library_ids: set[str] | None = None,

) -> dict:

    stage_name = _normalize_stage(stage)

    matches = retrieve_prompt_matches(

        query,

        stage=stage_name,

        top_k=top_k,

        context=context,

        global_context=global_context,

        local_context=local_context,

        failure_mode=failure_mode,

        include_base=True,

        library_ids=library_ids,

    )

    sections: list[str] = []

    if matches["base"]:

        sections.append(_format_prompt_block("全局基础约束", matches["base"]))

    if matches["matched"]:

        sections.append(_format_prompt_block("本阶段专项调用", matches["matched"]))

    block = "\n\n".join(section for section in sections if section)

    combined = base_prompt.strip()

    if block:

        section_title = STAGE_SECTION_TITLES[stage_name]

        if combined:

            combined = f"{combined}\n\n## {section_title}\n{block}"

        else:

            combined = f"## {section_title}\n{block}"

    return {

        "stage": stage_name,

        "prompt": combined,

        "block": block,

        "base": matches["base"],

        "matched": matches["matched"],

    }





def compose_prompt_with_libraries(

    base_prompt: str,

    *,

    query: str,

    stage: str,

    top_k: int | None = None,

    context: str = "",

    global_context: str = "",

    local_context: str = "",

    failure_mode: str = "",

    library_ids: set[str] | None = None,

) -> dict:

    effective_query = query.strip() or base_prompt.strip()

    return build_prompt_package(

        effective_query,

        stage=stage,

        base_prompt=base_prompt,

        top_k=top_k,

        context=context,

        global_context=global_context,

        local_context=local_context,

        failure_mode=failure_mode,

        library_ids=library_ids,

    )





def retrieve_prompts(query: str, top_k: int = 5, stage: str = "script") -> list[str]:

    package = retrieve_prompt_matches(query, stage=stage, top_k=top_k, include_base=False)

    return [item["prompt_text"] for item in package["matched"]]





def retrieve_prompts_with_names(

    query: str,

    top_k: int = 5,

    stage: str = "script",

    *,

    context: str = "",

    global_context: str = "",

    local_context: str = "",

    failure_mode: str = "",

    filter_mode: str = "",

    filter_value: str = "",

) -> list[dict]:

    package = retrieve_prompt_matches(

        query,

        stage=stage,

        top_k=top_k,

        context=context,

        global_context=global_context,

        local_context=local_context,

        failure_mode=failure_mode,

        include_base=True,

        library_ids=_resolve_filtered_library_ids(filter_mode, filter_value),

    )

    return package["base"] + package["matched"]





def build_full_prompt(

    query: str,

    top_k: int | None = None,

    *,

    context: str = "",

    global_context: str = "",

    local_context: str = "",

    failure_mode: str = "",

) -> str:

    package = build_prompt_package(

        query,

        stage="script",

        top_k=top_k,

        context=context,

        global_context=global_context,

        local_context=local_context,

        failure_mode=failure_mode,

    )

    return package["block"]





def export_library_catalog() -> list[dict]:

    catalog = [library.to_dict() for library in _load_libraries()]

    PROMPT_LIB_DIR.mkdir(parents=True, exist_ok=True)

    PROMPT_LIB_CATALOG_FILE.write_text(

        json.dumps(catalog, ensure_ascii=False, indent=2),

        encoding="utf-8",

    )

    return catalog





def rebuild_index() -> None:

    global _config_cache, _library_cache, _quick_index_cache, _context_vocab_cache

    with _lock:

        _config_cache = None

        _library_cache = None

        _quick_index_cache = None

        _context_vocab_cache = None

    export_library_catalog()

