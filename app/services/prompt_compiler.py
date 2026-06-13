"""prompt_compiler — unified execution prompt compiler for Seedance.

Compiles director prompt + must_* constraints + continuity + execution_plan
into a structured execution_prompt_final (English, Seedance-ready).

Priority order (highest → lowest):
  MUST constraints (must_character/action/lighting/camera)
  > continuity (cross-shot identity locks)
  > execution_plan (full-film structure)
  > memory_ctx / character_desc

Both single-shot (director_generate_shot) and batch video generation
must call compile_execution_prompt() as the single source of truth.
"""
from __future__ import annotations

import json
from pathlib import Path


# ── Public API ────────────────────────────────────────────────────────────────

def compile_execution_prompt(
    director_prompt: str,
    *,
    project_id: str = "",
    shot_index: int | None = None,
    # MUST constraints — values
    must_character: str = "",
    must_action: str = "",
    must_lighting: str = "",
    must_camera: str = "",
    # MUST constraints — lock switches (True = inject this dimension)
    lock_character: bool = True,
    lock_action: bool = True,
    lock_lighting: bool = True,
    lock_camera: bool = True,
    # continuity三字段
    character_continuity: str = "",
    scene_continuity: str = "",
    prop_continuity: str = "",
    # execution_plan六字段
    character_master: str = "",
    scene_master: str = "",
    performance_beats: str = "",
    camera_plan: str = "",
    hook_line: str = "",
    product_focus: str = "",
    # 其他上下文
    character_desc: str = "",
    memory_ctx: str = "",
    # 输出路径（可选，用于持久化）
    persist_path: str | None = None,
) -> dict:
    """Compile all director inputs into a structured execution_prompt_final.

    Lock switches control which MUST dimensions are injected:
      lock_character / lock_action / lock_lighting / lock_camera
    A dimension is only injected when its lock is True AND its value is non-empty.

    Returns:
        {
            "director_prompt":        str,
            "execution_prompt_cn":    str,
            "execution_prompt_final": str,
            "render_strategy":        str,
            "matched_libraries":      list,
            "must_block":             str,
            "continuity_block":       str,
            "execution_plan_block":   str,
            "global_context":         str,
            "locks_applied":          bool,   # True if any lock dimension was injected
            "locked_fields":          list,   # names of injected lock dimensions
        }
    """
    from .doubao import render_seedance_prompt_en
    from .prompt.engine import compose_prompt_with_libraries

    # ── Build MUST block: only inject dimensions where lock is True ───────────
    must_block, locked_fields = _build_must_block(
        must_character, must_action, must_lighting, must_camera,
        lock_character=lock_character,
        lock_action=lock_action,
        lock_lighting=lock_lighting,
        lock_camera=lock_camera,
    )
    locks_applied = bool(must_block)

    # ── Build continuity block ────────────────────────────────────────────────
    continuity_block = _build_continuity_block(
        character_continuity, scene_continuity, prop_continuity
    )

    # ── Build execution_plan block ────────────────────────────────────────────
    execution_plan_block = _build_execution_plan_block(
        character_master, scene_master, performance_beats,
        camera_plan, hook_line, product_focus,
    )

    # ── Assemble global_context: MUST > continuity > execution_plan > memory > char ──
    global_context = _join_nonempty(
        must_block, continuity_block, execution_plan_block, memory_ctx, character_desc
    )

    # ── Layer 2: Chinese fusion draft (library retrieval + context injection) ─
    prompt_package = compose_prompt_with_libraries(
        director_prompt,
        query=director_prompt,
        stage="shot",
        global_context=global_context,
    )
    cn_prompt = prompt_package["prompt"]
    matched_names = [m["name"] for m in prompt_package.get("matched", [])]

    # Prepend character_desc if not already present (hard anchor)
    if character_desc and character_desc not in cn_prompt:
        cn_prompt = f"{character_desc}，{cn_prompt}"

    # ── Layer 3: English execution prompt (structured render or fallback) ─────
    render_result = render_seedance_prompt_en(cn_prompt, return_meta=True)
    exec_prompt = render_result["prompt"]
    render_strategy = render_result["strategy"]

    record = {
        "director_prompt": director_prompt,
        "execution_prompt_cn": cn_prompt,
        "execution_prompt_final": exec_prompt,
        "render_strategy": render_strategy,
        "matched_libraries": matched_names,
        "must_block": must_block,
        "continuity_block": continuity_block,
        "execution_plan_block": execution_plan_block,
        "global_context": global_context,
        "locks_applied": locks_applied,
        "locked_fields": locked_fields,
    }
    if project_id and shot_index is not None:
        record["project_id"] = project_id
        record["shot_index"] = shot_index

    if persist_path:
        _persist_record(persist_path, record)

    return record


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_must_block(
    must_character: str,
    must_action: str,
    must_lighting: str,
    must_camera: str,
    *,
    lock_character: bool = True,
    lock_action: bool = True,
    lock_lighting: bool = True,
    lock_camera: bool = True,
) -> tuple[str, list[str]]:
    """Build MUST constraints block, gated by lock switches.

    A dimension is injected only when its lock is True AND its value is non-empty.
    Returns (block_text, locked_field_names).
    """
    parts: list[str] = []
    locked: list[str] = []
    if lock_character and must_character and must_character.strip():
        parts.append(f"[MUST人物] {must_character.strip()}")
        locked.append("lock_character")
    if lock_action and must_action and must_action.strip():
        parts.append(f"[MUST动作] {must_action.strip()}")
        locked.append("lock_action")
    if lock_lighting and must_lighting and must_lighting.strip():
        parts.append(f"[MUST光线] {must_lighting.strip()}")
        locked.append("lock_lighting")
    if lock_camera and must_camera and must_camera.strip():
        parts.append(f"[MUST镜头] {must_camera.strip()}")
        locked.append("lock_camera")
    return "；".join(parts), locked


def _build_continuity_block(
    character_continuity: str,
    scene_continuity: str,
    prop_continuity: str,
) -> str:
    """Cross-shot identity locks."""
    parts = []
    if character_continuity:
        parts.append(f"人物：{character_continuity}")
    if scene_continuity:
        parts.append(f"场景：{scene_continuity}")
    if prop_continuity:
        parts.append(f"道具：{prop_continuity}")
    return "；".join(parts)


_EXEC_LABEL_MAP = [
    ("character_master", "主角视觉锚点"),
    ("scene_master", "场景视觉锚点"),
    ("performance_beats", "情绪节拍"),
    ("camera_plan", "镜头语言"),
    ("hook_line", "前3秒钩子"),
    ("product_focus", "产品焦点"),
]


def _build_execution_plan_block(
    character_master: str,
    scene_master: str,
    performance_beats: str,
    camera_plan: str,
    hook_line: str,
    product_focus: str,
) -> str:
    """STYLE + ACTION/CAMERA block: full-film execution structure."""
    values = [character_master, scene_master, performance_beats,
              camera_plan, hook_line, product_focus]
    parts = []
    for (_, label), val in zip(_EXEC_LABEL_MAP, values):
        if val and val.strip():
            parts.append(f"{label}：{val.strip()}")
    return "；".join(parts)


def _join_nonempty(*parts: str) -> str:
    return "\n".join(p for p in parts if p and p.strip())


def _persist_record(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
