"""Director preflight checks for visually controllable image/video generation."""

from __future__ import annotations

import re
from typing import Any


EMPTY_TEMPLATE_TERMS = (
    "建立镜头",
    "关系镜头",
    "反应镜头",
    "道具特写",
    "动作推进",
    "情绪压迫",
    "对手反打",
    "转场落点",
)
GENERIC_STORYBOARD_TERMS = (
    "主角",
    "核心场景",
    "对手方",
    "关键道具",
    "关键信息",
    "明确动作",
    "情绪克制",
    "情绪变化",
    "冲突升级",
    "下一场",
    "人物关系",
    "空间关系",
)
CONCRETE_STORYBOARD_TERMS = (
    "张嘉益",
    "电视剧主角",
    "派出所",
    "调解室",
    "医院",
    "办公室",
    "街道",
    "文件袋",
    "旧文件",
    "饭盒",
    "工牌",
    "警服",
    "病历",
    "欠条",
)


RISK_BLOCKED = "blocked"
RISK_WARNING = "warning"
RISK_READY = "ready"

FACE_HINTS = ("脸", "正脸", "面部", "表情", "眼神", "微笑", "人物", "顾客", "店员", "主角", "女人", "男人")
WIDE_HINTS = ("远景", "全景", "大场景", "大厅", "街景", "航拍", "俯瞰", "广角")
CROWD_HINTS = ("很多人", "多人", "人群", "拥挤", "排队", "顾客们", "路人", "群演", "围观", "热闹")
COMMERCIAL_GOLD_HINTS = ("黄金回购", "黄金回收", "金店", "旧金", "金饰", "称重", "报价")
PROP_HINTS = ("黄金", "金饰", "戒指", "手镯", "项链", "电子秤", "报价单", "合同", "柜台", "道具")
SCENE_HINTS = ("金店", "柜台", "门店", "大厅", "办公室", "街道", "房间", "展厅", "场景")
COSTUME_HINTS = ("制服", "西装", "工装", "手套", "服装", "妆造", "造型")
STYLE_HINTS = ("电影感", "商业", "广告", "高级", "写实", "纪录片", "品牌", "质感")
ACTION_SPLIT_RE = re.compile(r"[，,；;、/]|同时|并且|然后|接着|一边|另一边")


def analyze_shot_risk(shot: dict[str, Any], *, project_goal: str = "") -> dict[str, Any]:
    prompt = str(shot.get("prompt") or "")
    ref_prompt = str(shot.get("ref_prompt") or "")
    text = f"{project_goal}\n{prompt}\n{ref_prompt}"
    compact = re.sub(r"\s+", "", text)

    risks: list[dict[str, str]] = []
    suggestions: list[str] = []
    required_refs: list[str] = []

    has_face = _contains_any(compact, FACE_HINTS)
    has_wide = _contains_any(compact, WIDE_HINTS)
    has_crowd = _has_crowd_overload(compact)
    is_gold_commercial = _contains_any(compact, COMMERCIAL_GOLD_HINTS)
    empty_storyboard = _is_empty_template_storyboard(prompt)
    missing_intent_entities = _missing_intent_entities(prompt, project_goal)

    if empty_storyboard:
        # 如果 prompt 中已包含"生成控制"语句，说明安全改写已应用，降级为 warning
        severity = "warning" if "生成控制" in prompt else "blocked"
        risks.append(_risk(
            "empty_template_storyboard",
            "空模板分镜",
            "分镜只写了建立镜头/关系镜头/反应镜头等功能词，没有具体主角身份、场景语境、动作目标和情绪变化，不能进入出图。",
            severity,
        ))
        if severity != "blocked":
            suggestions.append("安全改写已应用，空模板分镜降级为警告。建议在后续迭代中丰富分镜描述。")
        else:
            suggestions.append("先回到剧本/分镜阶段，把用户核心诉求拆成具体人物、地点、动作、情绪和剧情作用。")
    if missing_intent_entities:
        risks.append(_risk(
            "intent_entity_missing",
            "用户核心实体丢失",
            f"项目目标里的关键实体没有进入分镜：{', '.join(missing_intent_entities)}。继续生成会偏离用户诉求。",
            "blocked",
        ))
        suggestions.append("重写分镜时必须逐镜保留用户核心实体，尤其是主角身份、剧集类型和目标时长。")

    if not _has_clear_subject(compact):
        risks.append(_risk("subject_unclear", "主体不明确", "镜头没有明确谁是画面第一主体，模型容易把重点分散到环境或路人。", "warning"))
        suggestions.append("补一句明确主体，例如“一位顾客”或“一位店员”，并说明其位置和动作。")

    if has_crowd:
        risks.append(_risk("crowd_overload", "多人/人群高风险", "多人、人群、排队、围观会显著增加脸糊、肢体粘连和主体丢失概率。", "blocked"))
        suggestions.append("把人群改成最多两人同框，背景明确无其他顾客入镜。")

    if has_face and has_wide:
        risks.append(_risk("face_wide_mismatch", "远景看脸风险", "提示词需要人物表情或脸部，但景别偏远景/全景，脸部细节不可控。", "blocked"))
        suggestions.append("需要看脸的镜头改成中近景、近景或特写；远景只承担环境交代。")

    action_count = _action_load(prompt)
    if action_count >= 5:
        risks.append(_risk("composition_overload", "单镜头信息过载", "一个镜头承载过多动作、人物或物件，容易生成杂乱画面。", "warning"))
        suggestions.append("拆成两个镜头：一个人物/关系镜头，一个手部/道具/交易细节镜头。")

    if is_gold_commercial:
        if has_crowd:
            suggestions.append("黄金回购商业片默认不要门店人群，可信感来自干净柜台、检测流程和清晰人物。")
        if "称重" in compact or "报价" in compact or "交易" in compact:
            required_refs.append("prop")
        required_refs.extend(["scene", "style"])
        if has_face or "顾客" in compact or "店员" in compact:
            required_refs.append("character")

    if _contains_any(compact, PROP_HINTS):
        required_refs.append("prop")
    if _contains_any(compact, SCENE_HINTS):
        required_refs.append("scene")
    if _contains_any(compact, COSTUME_HINTS):
        required_refs.append("costume")
    if _contains_any(compact, STYLE_HINTS):
        required_refs.append("style")
    if has_face:
        required_refs.append("character")

    required_refs = _unique(required_refs)
    missing_refs = _missing_refs(shot, required_refs)
    if "character" in missing_refs and has_face:
        risks.append(_risk("missing_character_ref", "缺角色参考", "镜头要求清晰人物或连续脸，但未绑定角色参考，容易跳脸。", "warning"))
        suggestions.append("先绑定角色正脸/侧脸参考，再进入关键帧或视频生成。")
    if "scene" in missing_refs and _contains_any(compact, SCENE_HINTS):
        risks.append(_risk("missing_scene_ref", "缺场景参考", "镜头依赖门店/柜台/空间关系，但未绑定场景参考。", "warning"))
        suggestions.append("补一张主场景参考，固定柜台、灯光和背景复杂度。")
    if "prop" in missing_refs and _contains_any(compact, PROP_HINTS):
        risks.append(_risk("missing_prop_ref", "缺道具参考", "镜头依赖黄金、电子秤或报价单，但未绑定道具参考。", "warning"))
        suggestions.append("交易细节镜头优先绑定黄金饰品、电子秤或报价单参考。")

    level = _level(risks)
    safe_prompt = rewrite_shot_for_generation(prompt, risks, project_goal=project_goal)
    return {
        "risk_level": level,
        "risk_count": len(risks),
        "risks": risks,
        "suggestions": _unique(suggestions),
        "required_refs": required_refs,
        "missing_refs": missing_refs,
        "safe_prompt": safe_prompt,
        "can_generate_image": level != RISK_BLOCKED,
        "can_generate_video": level == RISK_READY,
    }


def analyze_project_risk(shots: list[dict[str, Any]], *, project_goal: str = "") -> dict[str, Any]:
    items = [analyze_shot_risk(shot, project_goal=project_goal) for shot in shots]
    blocked = sum(1 for item in items if item["risk_level"] == RISK_BLOCKED)
    warning = sum(1 for item in items if item["risk_level"] == RISK_WARNING)
    ready = sum(1 for item in items if item["risk_level"] == RISK_READY)
    return {
        "items": items,
        "blocked_count": blocked,
        "warning_count": warning,
        "ready_count": ready,
        "summary": _project_summary(blocked, warning, ready),
    }


def rewrite_shot_for_generation(prompt: str, risks: list[dict[str, str]], *, project_goal: str = "") -> str:
    text = prompt.strip()
    if not text:
        return text

    risk_codes = {item.get("code") for item in risks}
    additions: list[str] = []

    if "crowd_overload" in risk_codes:
        additions.append("最多两人同框，禁止人群、排队、围观和第三人入镜")
    if "face_wide_mismatch" in risk_codes:
        additions.append("需要清晰人脸时使用中近景或近景，脸部清晰可见，背景干净虚化")
    if "subject_unclear" in risk_codes:
        additions.append("画面第一主体明确居中，动作单一清楚")
    if "composition_overload" in risk_codes:
        additions.append("单镜头只表达一个核心动作，不堆叠多个交易步骤")
    if any(code in risk_codes for code in ("missing_character_ref", "missing_scene_ref", "missing_prop_ref")):
        additions.append("优先绑定对应参考图后再生成")

    goal_text = f"{project_goal} {prompt}"
    if _contains_any(goal_text, COMMERCIAL_GOLD_HINTS):
        additions.append("黄金回购商业片风格：干净金店柜台、可信服务、一位顾客和一位店员、手部与黄金道具特写承载交易细节")

    if not additions:
        return text
    return f"{text}\n生成控制：{'；'.join(_unique(additions))}。"


def _risk(code: str, title: str, reason: str, severity: str) -> dict[str, str]:
    return {"code": code, "title": title, "reason": reason, "severity": severity}


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _has_crowd_overload(text: str) -> bool:
    normalized = str(text or "")
    normalized = normalized.replace("让观众识别", "").replace("观众能读懂", "").replace("观众快速读懂", "")
    normalized = re.sub(r"(不允许|不能|禁止)[^，。；;,.]{0,24}路人", "", normalized)
    return _contains_any(normalized, CROWD_HINTS)


def _has_clear_subject(text: str) -> bool:
    subject_hints = ("一位", "一个", "顾客", "店员", "主角", "女人", "男人", "女孩", "男孩", "手部", "黄金", "门头", "柜台")
    return _contains_any(text, subject_hints)


def _is_empty_template_storyboard(prompt: str) -> bool:
    text = str(prompt or "")
    if not _contains_any(text, EMPTY_TEMPLATE_TERMS):
        return False

    generic_hits = sum(1 for term in GENERIC_STORYBOARD_TERMS if term in text)
    concrete_hits = sum(1 for term in CONCRETE_STORYBOARD_TERMS if term in text)
    named_people = re.findall(r"[\u4e00-\u9fff]{2,4}(?:演的|饰演|主演)", text)
    concrete_action = _contains_any(
        text,
        ("推门", "坐下", "递交", "攥着", "抬眼", "转身", "停住", "走进", "拿出"),
    )
    return generic_hits >= 3 and concrete_hits == 0 and not named_people and not concrete_action


def _missing_intent_entities(prompt: str, project_goal: str) -> list[str]:
    goal = str(project_goal or "")
    if not goal.strip():
        return []

    prompt_text = str(prompt or "")
    required: list[str] = []
    if "张嘉益" in goal:
        required.append("张嘉益")
    if "电视剧" in goal and "主角" in goal:
        required.append("电视剧主角")

    missing: list[str] = []
    for item in required:
        if item == "电视剧主角":
            if "电视剧主角" not in prompt_text and not ("电视剧" in prompt_text and "主角" in prompt_text):
                missing.append(item)
        elif item not in prompt_text:
            missing.append(item)
    return missing


def _action_load(prompt: str) -> int:
    parts = [part for part in ACTION_SPLIT_RE.split(prompt) if part.strip()]
    return len(parts)


def _missing_refs(shot: dict[str, Any], required_refs: list[str]) -> list[str]:
    field_map = {
        "character": ("character_refs", "character_refs_json"),
        "scene": ("scene_refs", "scene_refs_json"),
        "prop": ("prop_refs", "prop_refs_json"),
        "costume": ("costume_refs", "costume_refs_json"),
        "style": ("style_refs", "style_refs_json"),
    }
    missing = []
    for kind in required_refs:
        fields = field_map.get(kind, ())
        if not any(_as_list(shot.get(field)) for field in fields):
            missing.append(kind)
    return missing


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    return [value]


def _level(risks: list[dict[str, str]]) -> str:
    if any(item.get("severity") == RISK_BLOCKED for item in risks):
        return RISK_BLOCKED
    if risks:
        return RISK_WARNING
    return RISK_READY


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _project_summary(blocked: int, warning: int, ready: int) -> str:
    if blocked:
        return f"{blocked} 个分镜生成前高风险，建议先修正再送入图片/视频模型。"
    if warning:
        return f"{warning} 个分镜需要补资产或收紧提示词，其余 {ready} 个可推进。"
    return "分镜前置审查通过，可进入生成。"
