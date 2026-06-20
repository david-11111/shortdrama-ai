from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.director_input_protocol import (
    DIRECTOR_PROTOCOL_VERSION,
    director_protocol_prompt_block,
)
from app.services.visual_quality_rules import apply_video_motion_controls, apply_visual_quality_controls

_ADAPTER_MARKER = "[agent_control_constraints_v1]"

# text_only provider 集合（注册表初始化后填充）
_TEXT_ONLY_PROVIDERS: set[str] = set()


def _is_text_only(provider_name: str) -> bool:
    """查 provider 是否纯文本输入（复用注册表数据，避免循环导入）。"""
    if _TEXT_ONLY_PROVIDERS:
        return provider_name in _TEXT_ONLY_PROVIDERS
    # 懒加载：从 video_provider 注册表读
    from app.services.video_provider import get_config
    cfg = get_config(provider_name)
    return cfg.text_only if cfg else False


def _warm_text_only_cache() -> None:
    """开机时调用：把注册表中的 text_only provider 名全部缓存。"""
    from app.services.video_provider import get_config, list_all_names
    _TEXT_ONLY_PROVIDERS.clear()
    for name in list_all_names():
        cfg = get_config(name)
        if cfg and cfg.text_only:
            _TEXT_ONLY_PROVIDERS.add(name)


def adapt_provider_payload(
    payload: dict[str, Any],
    *,
    task_type: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Apply controller semantic constraints to the actual provider request."""
    next_payload = deepcopy(payload or {})
    provider_name = str(provider or next_payload.get("provider") or "").strip().lower()
    task_name = str(task_type or next_payload.get("task_type") or "").strip().lower()

    if task_name == "video_gen":
        _inject_continuity_reference(next_payload, provider_name=provider_name)
        _inject_temporal_position(next_payload)

    if provider_name == "doubao" or task_name in {"director_script", "story_plan", "generate_story_plan"}:
        return adapt_doubao_payload(next_payload)
    if provider_name == "seedream" or task_name == "image_gen":
        return adapt_seedream_payload(next_payload)

    # 视频 provider：从注册表查适配器（延迟 import 打破循环）
    from app.services.video_provider import get_config as _vp_get_config
    vp_cfg = _vp_get_config(provider_name)
    if vp_cfg and vp_cfg.adapter:
        adapter_fn = globals().get(vp_cfg.adapter)
        if adapter_fn:
            return adapter_fn(next_payload)

    # 未知 provider 的 video_gen 任务走 seedance 通用适配器
    if task_name == "video_gen":
        return adapt_seedance_payload(next_payload)

    return _attach_adapter_meta(next_payload, applied=False, provider=provider_name, task_type=task_name)


def adapt_doubao_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = _semantic(payload)
    block = _constraint_block(semantic, target="storyboard")
    if not block:
        return _attach_adapter_meta(payload, applied=False, provider="doubao", task_type="story_plan")
    payload["system_prompt"] = _append_once(str(payload.get("system_prompt") or ""), block)
    payload["prompt"] = _append_once(str(payload.get("prompt") or ""), _raw_instruction_block(semantic))
    return _attach_adapter_meta(payload, applied=True, provider="doubao", task_type="story_plan")


def adapt_seedream_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = _semantic(payload)
    director_applied = _inject_director_protocol(payload, target="seedream")
    block = _constraint_block(semantic, target="keyframe")
    if not block:
        payload["prompt"] = apply_visual_quality_controls(str(payload.get("prompt") or ""))
        return _attach_adapter_meta(payload, applied=director_applied, provider="seedream", task_type="image_gen")
    payload["prompt"] = apply_visual_quality_controls(_append_once(str(payload.get("prompt") or ""), block))
    _merge_negative_prompt(payload, semantic)
    return _attach_adapter_meta(payload, applied=True, provider="seedream", task_type="image_gen")


def adapt_seedance_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = _semantic(payload)
    director_applied = _inject_director_protocol(payload, target="video")
    block = _constraint_block(semantic, target="video")
    if not block:
        payload["prompt"] = apply_video_motion_controls(str(payload.get("prompt") or ""))
        return _attach_adapter_meta(payload, applied=director_applied, provider="seedance", task_type="video_gen")
    payload["prompt"] = apply_video_motion_controls(_append_once(str(payload.get("prompt") or ""), block))
    _merge_negative_prompt(payload, semantic)
    return _attach_adapter_meta(payload, applied=True, provider="seedance", task_type="video_gen")


def adapt_ltx_payload(payload: dict[str, Any]) -> dict[str, Any]:
    director_applied = _inject_director_protocol(payload, target="video")
    return _attach_adapter_meta(payload, applied=director_applied, provider="ltx2.3", task_type="video_gen")


def adapt_joy_echo_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = _semantic(payload)
    director_applied = _inject_director_protocol(payload, target="joy-echo")
    block = _constraint_block(semantic, target="video")
    if not block:
        payload["prompt"] = apply_video_motion_controls(str(payload.get("prompt") or ""))
        return _attach_adapter_meta(payload, applied=director_applied, provider="joy-echo", task_type="video_gen")
    payload["prompt"] = apply_video_motion_controls(_append_once(str(payload.get("prompt") or ""), block))
    _merge_negative_prompt(payload, semantic)
    return _attach_adapter_meta(payload, applied=True, provider="joy-echo", task_type="video_gen")


def _semantic(payload: dict[str, Any]) -> dict[str, Any]:
    routing = payload.get("human_routing") if isinstance(payload.get("human_routing"), dict) else {}
    nested = routing.get("semantic") if isinstance(routing.get("semantic"), dict) else {}
    brief = payload.get("intent_brief") if isinstance(payload.get("intent_brief"), dict) else nested.get("intent_brief")
    constraints = payload.get("constraint_packet") if isinstance(payload.get("constraint_packet"), dict) else nested.get("constraint_packet")
    plan = payload.get("semantic_plan") if isinstance(payload.get("semantic_plan"), dict) else nested.get("semantic_plan")
    verification = payload.get("verification_plan") if isinstance(payload.get("verification_plan"), dict) else nested.get("verification_plan")
    return {
        "brief": brief if isinstance(brief, dict) else {},
        "constraints": constraints if isinstance(constraints, dict) else {},
        "plan": plan if isinstance(plan, dict) else {},
        "verification": verification if isinstance(verification, dict) else {},
    }


def _constraint_block(semantic: dict[str, Any], *, target: str) -> str:
    brief = semantic.get("brief") or {}
    constraints = semantic.get("constraints") or {}
    if not brief and not constraints:
        return ""
    must_keep = _clean_list(constraints.get("must_keep") or brief.get("must_keep"))
    must_avoid = _clean_list(constraints.get("must_avoid") or brief.get("must_avoid"))
    tone = _clean_list(constraints.get("tone") or brief.get("tone"))
    quality_bar = _clean_list(constraints.get("quality_bar"))
    visual_language = constraints.get("visual_language") or brief.get("visual_language") or {}
    raw_instruction = str(brief.get("raw_instruction") or "").strip()
    category = str(brief.get("category") or "").strip()
    duration = brief.get("duration_sec")

    lines = [_ADAPTER_MARKER, f"target={target}"]
    if raw_instruction:
        lines.append(f"raw_user_intent={raw_instruction}")
    if category:
        lines.append(f"category={category}")
    if duration:
        lines.append(f"target_duration_sec={duration}")
    if tone:
        lines.append("tone=" + "; ".join(tone))
    if must_keep:
        lines.append("must_keep=" + "; ".join(must_keep))
    if must_avoid:
        lines.append("must_avoid=" + "; ".join(must_avoid))
    if isinstance(visual_language, dict) and visual_language:
        lines.append("visual_language=" + "; ".join(f"{key}: {value}" for key, value in visual_language.items() if value))
    if quality_bar:
        lines.append("quality_bar=" + "; ".join(quality_bar))
    if target == "storyboard":
        lines.append("provider_instruction=Write script and storyboard to serve the user intent; do not drift into generic short-drama conflict if the user asked for a brand film or ad.")
    elif target == "keyframe":
        lines.append("provider_instruction=Generate a single usable cinematic keyframe that preserves subject, brand tone, material detail, lighting and composition constraints.")
    elif target == "video":
        lines.append("provider_instruction=Animate from the selected keyframe while preserving identity, material, lighting continuity and shot purpose.")
    return "\n".join(lines)


def _raw_instruction_block(semantic: dict[str, Any]) -> str:
    raw_instruction = str((semantic.get("brief") or {}).get("raw_instruction") or "").strip()
    if not raw_instruction:
        return _ADAPTER_MARKER
    return f"{_ADAPTER_MARKER}\nraw_user_intent={raw_instruction}"


def _append_once(base: str, block: str) -> str:
    base = str(base or "").strip()
    block = str(block or "").strip()
    if not block:
        return base
    if _ADAPTER_MARKER in base:
        return base
    if not base:
        return block
    return f"{base}\n\n{block}"


def _inject_director_protocol(payload: dict[str, Any], *, target: str) -> bool:
    protocol = payload.get("director_input_protocol")
    if not isinstance(protocol, dict):
        return False
    prompt = str(payload.get("prompt") or "")
    if f"[{DIRECTOR_PROTOCOL_VERSION}]" in prompt:
        return False
    payload["prompt"] = _append_director_block(prompt, director_protocol_prompt_block(protocol, target=target))
    return True


def _append_director_block(base: str, block: str) -> str:
    base = str(base or "").strip()
    block = str(block or "").strip()
    if not block:
        return base
    if not base:
        return block
    return f"{base}\n\n{block}"


def _merge_negative_prompt(payload: dict[str, Any], semantic: dict[str, Any]) -> None:
    constraints = semantic.get("constraints") or {}
    brief = semantic.get("brief") or {}
    negatives = _clean_list(constraints.get("must_avoid") or brief.get("must_avoid"))
    if not negatives:
        return
    existing = str(payload.get("negative_prompt") or "").strip()
    merged = _dedupe([*([existing] if existing else []), *negatives])
    payload["negative_prompt"] = "; ".join(merged)


def _attach_adapter_meta(payload: dict[str, Any], *, applied: bool, provider: str, task_type: str) -> dict[str, Any]:
    meta = payload.get("provider_adapter") if isinstance(payload.get("provider_adapter"), dict) else {}
    payload["provider_adapter"] = {
        **meta,
        "version": "provider_prompt_adapter_v1",
        "provider": provider,
        "task_type": task_type,
        "constraints_applied": bool(applied),
    }
    return payload


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return _dedupe(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _inject_continuity_reference(payload: dict[str, Any], *, provider_name: str = "") -> None:
    """Inject previous shot's output as continuity reference.

    If prev_shot_reference is present in the payload:
    1. Add it to ref_images list (for providers that support reference images)
    2. Append a continuity hint to the prompt (for temporal coherence)
    """
    prev_ref = str(payload.pop("prev_shot_reference", "") or "").strip()
    if not prev_ref:
        return

    # Add to ref_images only for providers that accept image/video references.
    if not _is_text_only(provider_name):
        ref_images = payload.get("ref_images")
        if isinstance(ref_images, list):
            if prev_ref not in ref_images:
                ref_images.append(prev_ref)
        else:
            payload["ref_images"] = [prev_ref]

    # Append continuity hint to prompt
    prompt = str(payload.get("prompt") or "")
    continuity_hint = "镜头衔接控制：延续上一个镜头的画面构图、人物位置和光线方向，保持视觉连贯。"
    if continuity_hint not in prompt:
        payload["prompt"] = f"{prompt}\n{continuity_hint}" if prompt else continuity_hint


def _inject_temporal_position(payload: dict[str, Any]) -> None:
    """Inject shot position hint to adjust motion strategy.

    Opening shots: start from stillness, gradual motion onset.
    Middle shots: maintain established rhythm, smooth continuity.
    Closing shots: decelerate, settle into final composition.
    """
    shot_row = payload.get("shot_row") if isinstance(payload.get("shot_row"), dict) else {}
    shot_index = shot_row.get("shot_index")
    if shot_index is None:
        shot_index = payload.get("shot_index")
    if shot_index is None:
        return

    shot_index = int(shot_index)

    # Determine total shots from shot_row metadata or use a heuristic
    total_shots = int(shot_row.get("total_shots") or payload.get("total_shots") or 0)
    if total_shots <= 0:
        # Can't determine position without total — skip
        return

    # Determine position category
    position_ratio = shot_index / total_shots
    if shot_index <= 1 or position_ratio <= 0.15:
        position_hint = "时序位置：开场镜头。画面从静止缓慢启动，运动从零加速，建立场景氛围。"
    elif position_ratio >= 0.85 or shot_index >= total_shots:
        position_hint = "时序位置：结尾镜头。运动逐渐减速收束，画面趋于稳定，留下余韵。"
    else:
        position_hint = "时序位置：中段镜头。保持已建立的运动节奏，动作连贯自然。"

    prompt = str(payload.get("prompt") or "")
    if "时序位置" not in prompt:
        payload["prompt"] = f"{prompt}\n{position_hint}" if prompt else position_hint
