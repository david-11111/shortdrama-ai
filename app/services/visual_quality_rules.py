from __future__ import annotations

import re
from typing import Any


_LIGHTING_HINTS = ("光", "光影", "逆光", "顶光", "侧光", "柔光", "自然光", "阴影", "色温")
_DEPTH_HINTS = ("景深", "透视", "前景", "中景", "后景", "背景", "虚化", "大光圈", "空间关系", "层次")
_MOOD_HINTS = ("氛围", "情绪", "色调", "冷峻", "温暖", "治愈", "压抑", "高级", "清冷", "紧张")
_PLASTIC_HINTS = ("塑料感", "假", "生硬", "僵硬", "AI感", "机器感")
_FACIAL_HINTS = ("嘴角", "眼神", "眼底", "面部", "微表情", "表情", "神态")
_BODY_HINTS = ("肢体", "手", "肩膀", "头部", "视线", "动作", "姿态", "转身", "抬头", "低头")
_SHOT_TYPE_HINTS = ("中景", "近景", "特写", "全景", "远景", "半身", "过肩", "俯拍", "仰拍")
_CAMERA_MOTION_HINTS = ("推进", "推镜", "拉远", "后拉", "横移", "环绕", "摇镜", "跟拍", "平移", "变焦", "dolly", "pan")
_MOTION_SPEED_HINTS = ("缓慢", "快速", "匀速", "稳定", "顺滑", "慢推", "快切", "停顿", "节奏")


def build_visual_quality_controls(prompt: str, *, refs_pack: dict[str, Any] | None = None) -> list[str]:
    """Return deterministic visual controls that reduce obvious AI stiffness.

    These controls are intentionally short and provider-neutral. They are
    injected into Seedream keyframe prompts and Seedance video prompts through
    ref_resolver, so the rule applies at the image/video generation boundary.
    """
    text = str(prompt or "")
    refs_pack = refs_pack if isinstance(refs_pack, dict) else {}
    controls: list[str] = []

    if not _contains_any(text, _LIGHTING_HINTS):
        controls.append("自然光影：避免全画面均匀打光，保留主光方向、明暗层次和真实阴影，可使用逆光、顶光或侧光。")
    else:
        controls.append("光影连续：主光方向明确，人物与场景共享同一套可信光照，不忽明忽暗。")

    if not _contains_any(text, _DEPTH_HINTS):
        controls.append("空间层次：明确前景、中景、背景和透视关系，主体与背景有景深分离，避免平面贴图感。")
    else:
        controls.append("景深透视：前后景关系稳定，透视不变形，背景适度虚化以突出主体。")

    if not _contains_any(text, _MOOD_HINTS):
        controls.append("情绪色调：根据剧情氛围统一冷暖色彩，不让场景和人物情绪脱节。")
    else:
        controls.append("氛围统一：色调、光影和表演情绪匹配同一主题，避免冷暖调性冲突。")

    if _contains_any(text, _PLASTIC_HINTS) or _has_reference_assets(refs_pack):
        controls.append("去AI感：降低过饱和和过度磨皮，保留真实皮肤、材质纹理和轻微环境瑕疵。")
    else:
        controls.append("真实质感：不过饱和，不过度精修，保留材质纹理，避免廉价塑料感。")

    controls.extend(build_human_performance_controls(text))
    return controls


def apply_visual_quality_controls(prompt: str, *, refs_pack: dict[str, Any] | None = None) -> str:
    base = str(prompt or "").strip()
    controls = build_visual_quality_controls(base, refs_pack=refs_pack)
    if not controls:
        return base
    block = "；".join(_dedupe_controls(controls))
    if not base:
        return f"画面质感控制：{block}。"
    if "画面质感控制" in base:
        return base
    return f"{base}\n画面质感控制：{block}。"


def build_human_performance_controls(prompt: str) -> list[str]:
    """Return short controls that keep AI characters emotionally believable."""
    text = str(prompt or "")
    controls: list[str] = []
    if not _contains_any(text, _FACIAL_HINTS):
        controls.append("真人表演：把大情绪拆成嘴角、眼神和面部微表情，避免咧嘴大笑、痛哭等夸张表演。")
    else:
        controls.append("微表情执行：嘴角、眼神和面部肌肉变化克制细腻，不做夸张表演。")

    if not _contains_any(text, _BODY_HINTS):
        controls.append("肢体联动：给情绪配合轻微手部、肩膀、头部或视线动作，让情绪有真实落点。")
    else:
        controls.append("肢体同步：视线方向、手部动作、肩颈姿态与面部情绪一致。")
    return controls


def build_video_motion_controls(prompt: str) -> list[str]:
    """Return short camera-motion controls for Seedance video prompts."""
    text = str(prompt or "")
    controls: list[str] = []
    if not _contains_any(text, _SHOT_TYPE_HINTS):
        controls.append("景别：默认中景或中近景，主体清楚可辨，避免无目的远景。")
    else:
        controls.append("景别执行：按提示词指定景别构图，主体始终是画面焦点。")

    if not _contains_any(text, _CAMERA_MOTION_HINTS):
        controls.append("运镜：镜头缓慢向前推进或轻微跟拍，运动稳定顺滑，不像PPT平移。")
    else:
        controls.append("运镜执行：按指定方向运动，轨迹连续，避免突然跳动、抽帧和卡顿。")

    if not _contains_any(text, _MOTION_SPEED_HINTS):
        controls.append("速度节奏：慢速、匀速、带轻微停顿，情绪递进清楚。")
    else:
        controls.append("速度节奏：移动快慢与情绪一致，起落点明确。")

    controls.append("主体配合：运镜始终围绕主体动作和面部神态，不让背景抢戏。")
    controls.append("环境配合：背景光影、前后景和氛围随镜头运动保持连续。")
    return controls


def apply_video_motion_controls(prompt: str) -> str:
    base = str(prompt or "").strip()
    if "视频运镜控制" in base:
        return base
    controls = "；".join(_dedupe_controls(build_video_motion_controls(base)))
    if not base:
        return f"视频运镜控制：{controls}。"
    return f"{base}\n视频运镜控制：{controls}。"


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    normalized = re.sub(r"\s+", "", text)
    return any(hint in normalized for hint in hints)


def _has_reference_assets(pack: dict[str, Any]) -> bool:
    for role in ("character", "scene", "prop", "costume", "style"):
        if pack.get(role, {}).get("resolved_urls"):
            return True
    return False


def _dedupe_controls(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = item.strip(" ；;。")
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result
