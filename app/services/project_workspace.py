"""File-backed production workspace for short-drama projects.

The database stores operational rows. This module stores the durable project
brief, story plan, scene plan, shot plan, and memory files that an agent should
read before continuing work on a project.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

STORAGE = Path(__file__).resolve().parents[2] / "storage" / "projects"

BOOTSTRAP_FILES = (
    "PROJECT.md",
    "story/characters.md",
    "story/episodes.md",
    "scenes/episode-01-scene-01.md",
    "shots/episode-01-scene-01.json",
    "memory/decisions.md",
    "memory/failures.md",
    "memory/constraints.md",
)

ALLOWED_EXACT_WRITE_PATHS = set(BOOTSTRAP_FILES)
AUTO_DECISION_SKIP_PATHS = {"memory/decisions.md", "memory/failures.md"}
WRITE_MODES = {"append", "replace"}
MANAGED_PLAN_WRITE_PATHS = {
    "story/characters.md",
    "story/episodes.md",
    "scenes/episode-01-scene-01.md",
}
MANAGED_SECTION_MARKERS = {
    "story/characters.md": "## Director Lock",
    "story/episodes.md": "## Director Plan",
    "scenes/episode-01-scene-01.md": "## Director Scene Plan",
}


def init_project_workspace(project_id: str, *, name: str = "", force: bool = False) -> dict[str, Any]:
    root = project_workspace_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    kept: list[str] = []

    for relative_path in BOOTSTRAP_FILES:
        path = _safe_child(root, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not force:
            kept.append(relative_path)
            continue
        path.write_text(_template(relative_path, project_id=project_id, name=name), encoding="utf-8")
        created.append(relative_path)

    manifest = _build_manifest(project_id, root)
    return {
        "project_id": project_id,
        "workspace_root": str(root),
        "created": created,
        "kept": kept,
        **manifest,
    }


def read_project_workspace(project_id: str, *, ensure: bool = True, name: str = "") -> dict[str, Any]:
    if ensure:
        init_project_workspace(project_id, name=name)
    root = project_workspace_root(project_id)
    manifest = _build_manifest(project_id, root)
    return {
        "project_id": project_id,
        "workspace_root": str(root),
        **manifest,
        "bootstrap": {
            relative_path: _read_text(root, relative_path)
            for relative_path in BOOTSTRAP_FILES
            if _safe_child(root, relative_path).exists()
        },
    }


def write_project_workspace_file(
    project_id: str,
    *,
    relative_path: str,
    content: str,
    mode: str = "append",
    source: str = "director_agent",
    reason: str = "",
    force: bool = False,
    name: str = "",
) -> dict[str, Any]:
    """Write model output into a controlled project workspace file.

    The model may propose content, but this service owns validation, path
    allow-listing, overwrite protection, and durable decision logging.
    """
    root = project_workspace_root(project_id)
    if not root.exists():
        init_project_workspace(project_id, name=name)

    normalized_path = normalize_workspace_path(relative_path)
    if not is_allowed_workspace_write_path(normalized_path):
        raise ValueError(f"Workspace path is not writable: {relative_path}")

    write_mode = str(mode or "append").strip().lower()
    if write_mode not in WRITE_MODES:
        raise ValueError(f"Unsupported workspace write mode: {mode}")

    text_content = str(content or "")
    if not text_content.strip():
        raise ValueError("Workspace write content cannot be empty")

    target = _safe_child(root, normalized_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    previous_size = target.stat().st_size if existed else 0

    if normalized_path.endswith(".json"):
        if write_mode != "replace":
            raise ValueError("JSON workspace files only support replace mode")
        _validate_json_content(text_content)

    if write_mode == "replace":
        if existed and previous_size > 0 and not force:
            raise ValueError("Replacing an existing workspace file requires force=true")
        target.write_text(_ensure_trailing_newline(text_content), encoding="utf-8")
    else:
        prefix = "\n" if existed and previous_size > 0 else ""
        target.write_text(
            (target.read_text(encoding="utf-8") if existed else "")
            + prefix
            + _ensure_trailing_newline(text_content),
            encoding="utf-8",
        )

    decision_entry = ""
    if normalized_path not in AUTO_DECISION_SKIP_PATHS:
        decision_entry = _build_decision_entry(
            relative_path=normalized_path,
            mode=write_mode,
            source=source,
            reason=reason,
        )
        decisions = _safe_child(root, "memory/decisions.md")
        decisions.parent.mkdir(parents=True, exist_ok=True)
        existing = decisions.read_text(encoding="utf-8") if decisions.exists() else _decisions_template()
        decisions.write_text(existing.rstrip() + "\n\n" + decision_entry, encoding="utf-8")

    return {
        "project_id": project_id,
        "write": {
            "path": normalized_path,
            "mode": write_mode,
            "source": source,
            "reason": reason,
            "force": force,
            "existed": existed,
            "previous_size": previous_size,
            "size": target.stat().st_size,
            "decision_recorded": bool(decision_entry),
            "written_at": datetime.now(timezone.utc).isoformat(),
        },
        "workspace": read_project_workspace(project_id, ensure=False, name=name),
    }


def persist_director_result_to_workspace(
    project_id: str,
    result: dict[str, Any],
    *,
    source: str = "director_agent",
    reason: str = "director result persisted",
    name: str = "",
) -> dict[str, Any]:
    """Persist a director chat/script result into the file-backed workspace."""
    if not project_id or not isinstance(result, dict):
        return {"project_id": project_id, "writes": [], "skipped": "empty result"}

    init_project_workspace(project_id, name=name)
    writes: list[dict[str, Any]] = []

    def _write(relative_path: str, content: str, mode: str = "append", force: bool = False) -> None:
        clean = str(content or "").strip()
        if not clean:
            return
        payload = write_project_workspace_file(
            project_id,
            relative_path=relative_path,
            content=clean,
            mode=mode,
            source=source,
            reason=reason,
            force=force,
            name=name,
        )
        writes.append(payload["write"])

    continuity = result.get("continuity") if isinstance(result.get("continuity"), dict) else {}
    execution_plan = result.get("execution_plan") if isinstance(result.get("execution_plan"), dict) else {}
    reply = str(result.get("reply") or result.get("script_text") or "").strip()
    shot_rows = result.get("shot_rows") if isinstance(result.get("shot_rows"), list) else []

    characters_doc = _build_characters_workspace_section(continuity, execution_plan)
    episodes_doc = _build_episodes_workspace_section(result, reply)
    scene_doc = _build_scene_workspace_section(result, reply, shot_rows)
    shots_doc = _build_shots_workspace_json(project_id, shot_rows, continuity, execution_plan)

    for path, content in (
        ("story/characters.md", characters_doc),
        ("story/episodes.md", episodes_doc),
        ("scenes/episode-01-scene-01.md", scene_doc),
    ):
        mode = "replace" if path in MANAGED_PLAN_WRITE_PATHS else "append"
        _write(path, content, mode=mode, force=mode == "replace")
    if shot_rows:
        _write("shots/episode-01-scene-01.json", shots_doc, mode="replace", force=True)

    return {
        "project_id": project_id,
        "writes": writes,
        "workspace": read_project_workspace(project_id, ensure=False, name=name),
    }


def compact_project_workspace(project_id: str, *, name: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Compact managed markdown files to their latest generated section.

    This is an explicit repair operation for older workspaces that accumulated
    repeated Director sections through append-only writes.
    """
    init_project_workspace(project_id, name=name)
    root = project_workspace_root(project_id)
    planned: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []

    for relative_path, marker in MANAGED_SECTION_MARKERS.items():
        target = _safe_child(root, relative_path)
        if not target.exists():
            continue
        original = target.read_text(encoding="utf-8")
        compacted = _latest_marked_section(original, marker)
        if not compacted or compacted.strip() == original.strip():
            continue
        planned.append({
            "path": relative_path,
            "marker": marker,
            "previous_chars": len(original),
            "next_chars": len(compacted),
            "saved_chars": max(0, len(original) - len(compacted)),
        })
        if dry_run:
            continue
        payload = write_project_workspace_file(
            project_id,
            relative_path=relative_path,
            content=compacted,
            mode="replace",
            source="workspace_compactor",
            reason="compact repeated managed Director sections",
            force=True,
            name=name,
        )
        writes.append(payload["write"])

    return {
        "project_id": project_id,
        "dry_run": dry_run,
        "planned": planned,
        "writes": writes,
        "workspace": read_project_workspace(project_id, ensure=False, name=name),
    }


def project_workspace_root(project_id: str) -> Path:
    safe_project_id = sanitize_project_id(project_id)
    root = (STORAGE / safe_project_id).resolve()
    _assert_path_within(root, STORAGE.resolve())
    return root


def sanitize_project_id(project_id: str) -> str:
    safe_project_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(project_id)).strip("._")
    return safe_project_id or "unknown_project"


def normalize_workspace_path(relative_path: str) -> str:
    raw_path = str(relative_path or "").replace("\\", "/").strip()
    if not raw_path:
        raise ValueError("Workspace path is required")
    pure_path = PurePosixPath(raw_path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise ValueError(f"Invalid workspace path: {relative_path}")
    return pure_path.as_posix()


def is_allowed_workspace_write_path(relative_path: str) -> bool:
    normalized_path = normalize_workspace_path(relative_path)
    if normalized_path in ALLOWED_EXACT_WRITE_PATHS:
        return True
    parts = PurePosixPath(normalized_path).parts
    if len(parts) != 2:
        return False
    folder, filename = parts
    if folder == "scenes" and filename.endswith(".md"):
        return True
    if folder == "shots" and filename.endswith(".json"):
        return True
    return False


def _build_characters_workspace_section(continuity: dict[str, Any], execution_plan: dict[str, Any]) -> str:
    lines: list[str] = []
    character = str(continuity.get("character_continuity") or execution_plan.get("character_master") or "").strip()
    scene = str(continuity.get("scene_continuity") or execution_plan.get("scene_master") or "").strip()
    prop = str(continuity.get("prop_continuity") or "").strip()
    if character or scene or prop:
        lines.append(f"## Director Lock {datetime.now(timezone.utc).isoformat()}")
    if character:
        lines.extend(["", "### Character Continuity", character])
    if scene:
        lines.extend(["", "### Scene Continuity", scene])
    if prop:
        lines.extend(["", "### Prop Continuity", prop])
    return "\n".join(lines).strip()


def _build_episodes_workspace_section(result: dict[str, Any], reply: str) -> str:
    score = result.get("score") if isinstance(result.get("score"), dict) else {}
    quality_gate = result.get("quality_gate") if isinstance(result.get("quality_gate"), dict) else {}
    lines = [f"## Director Plan {datetime.now(timezone.utc).isoformat()}"]
    if reply:
        lines.extend(["", "### Story / Production Draft", reply])
    if score:
        lines.extend(["", "### Director Score", json.dumps(score, ensure_ascii=False, indent=2)])
    if quality_gate:
        lines.extend(["", "### Quality Gate", json.dumps(quality_gate, ensure_ascii=False, indent=2)])
    return "\n".join(lines).strip()


def _build_scene_workspace_section(result: dict[str, Any], reply: str, shot_rows: list[Any]) -> str:
    keyframe_beats = result.get("recommended_keyframe_beats")
    locks = result.get("recommended_locks")
    lines = [f"## Director Scene Plan {datetime.now(timezone.utc).isoformat()}"]
    if reply:
        lines.extend(["", "### Scene Draft", reply])
    if locks:
        lines.extend(["", "### Recommended Locks", json.dumps(locks, ensure_ascii=False, indent=2)])
    if keyframe_beats:
        lines.extend(["", "### Keyframe Beats", json.dumps(keyframe_beats, ensure_ascii=False, indent=2)])
    if shot_rows:
        lines.extend(["", "### Shot Summary"])
        for item in shot_rows:
            if not isinstance(item, dict):
                continue
            idx = item.get("shot_index") or item.get("index") or len(lines)
            prompt = str(item.get("prompt") or item.get("scene_description") or "").strip()
            duration = item.get("duration") or item.get("duration_seconds") or 5
            lines.append(f"- Shot {idx} ({duration}s): {prompt}")
    return "\n".join(lines).strip()


def _build_shots_workspace_json(
    project_id: str,
    shot_rows: list[Any],
    continuity: dict[str, Any],
    execution_plan: dict[str, Any],
) -> str:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(shot_rows, start=1):
        if not isinstance(item, dict):
            continue
        normalized.append({
            "shot_index": int(item.get("shot_index") or item.get("index") or index),
            "prompt": str(item.get("prompt") or "").strip(),
            "ref_prompt": str(item.get("ref_prompt") or "").strip(),
            "duration": int(item.get("duration") or item.get("duration_seconds") or 5),
            "status": str(item.get("status") or "pending"),
            "continuity": item.get("continuity") if isinstance(item.get("continuity"), dict) else continuity,
            "execution_plan": item.get("execution_plan") if isinstance(item.get("execution_plan"), dict) else execution_plan,
            "director_preflight": item.get("director_preflight") if isinstance(item.get("director_preflight"), dict) else None,
        })
    payload = {
        "version": "shortdrama_shots_v1",
        "project_id": project_id,
        "episode": 1,
        "scene": "episode-01-scene-01",
        "shots": normalized,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _build_manifest(project_id: str, root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for relative_path in BOOTSTRAP_FILES:
        path = _safe_child(root, relative_path)
        files.append({
            "path": relative_path,
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() else 0,
        })
    return {
        "workspace_version": "shortdrama_workspace_v1",
        "required_files": list(BOOTSTRAP_FILES),
        "files": files,
        "ready": all(item["exists"] for item in files),
    }


def _read_text(root: Path, relative_path: str) -> str:
    try:
        return _safe_child(root, relative_path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _ensure_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else content + "\n"


def _validate_json_content(content: str) -> None:
    try:
        json.loads(content)
    except Exception as exc:
        raise ValueError(f"Invalid JSON workspace content: {exc}") from exc


def _latest_marked_section(content: str, marker: str) -> str:
    text = str(content or "")
    starts = [match.start() for match in re.finditer(rf"(?m)^{re.escape(marker)}\b.*$", text)]
    if not starts:
        return text.strip()
    return text[starts[-1]:].strip()


def _build_decision_entry(*, relative_path: str, mode: str, source: str, reason: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    reason_line = reason.strip() or "workspace write"
    source_value = (source or "director_agent").strip() or "director_agent"
    return (
        f"## {now}\n\n"
        f"- path: {relative_path}\n"
        f"- mode: {mode}\n"
        f"- source: {source_value}\n"
        f"- reason: {reason_line}\n"
    )


def _safe_child(root: Path, relative_path: str) -> Path:
    path = (root / relative_path).resolve()
    _assert_path_within(path, root.resolve())
    return path


def _assert_path_within(path: Path, root: Path) -> None:
    path_text = _compare_path(path)
    root_text = _compare_path(root)
    if path_text == root_text or path_text.startswith(root_text + os.sep):
        return
    raise ValueError(f"{str(path)!r} is not in the subpath of {str(root)!r}")


def _compare_path(path: Path) -> str:
    text = str(path)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.normpath(os.path.abspath(text)))


def _template(relative_path: str, *, project_id: str, name: str) -> str:
    project_name = (name or project_id).strip() or project_id
    now = datetime.now(timezone.utc).isoformat()
    templates = {
        "PROJECT.md": _project_template(project_id=project_id, project_name=project_name, now=now),
        "story/characters.md": _characters_template(project_name=project_name),
        "story/episodes.md": _episodes_template(project_name=project_name),
        "scenes/episode-01-scene-01.md": _scene_template(project_name=project_name),
        "shots/episode-01-scene-01.json": _shots_template(project_id=project_id),
        "memory/decisions.md": _decisions_template(),
        "memory/failures.md": _failures_template(),
        "memory/constraints.md": _constraints_template(),
    }
    return templates[relative_path]


def _project_template(*, project_id: str, project_name: str, now: str) -> str:
    return f"""# {project_name}

- project_id: {project_id}
- workspace_version: shortdrama_workspace_v1
- created_at: {now}
- project_type: 精品短剧

## 项目目标

这个项目的目标是制作具有电视剧质感的精品短剧：人物稳定、场景可信、镜头有调度、情绪能连续，最终素材可以剪成完整成片。

## 当前阶段

- stage: development
- current_episode: 1
- current_scene: episode-01-scene-01
- next_step: 完成剧本理解、场次规划、角色与资产锁定

## Agent 启动规则

每次进入这个项目，先按顺序读取：

1. PROJECT.md
2. memory/decisions.md
3. memory/failures.md
4. memory/constraints.md
5. story/characters.md
6. story/episodes.md
7. 当前 scenes/*.md
8. 当前 shots/*.json

读取后先判断当前卡点，再推进下一步。不要绕过高风险分镜、缺资产分镜或未审片素材直接生成视频。

## 制片原则

- 先想清楚，再生成。
- 先判断风险，再花钱调用 API。
- 先审关键帧，再进入视频。
- 先审视频，再进入剪辑。
- 失败经验必须写入 memory/failures.md。

## 精品短剧标准流程

### 1. 剧本理解

先判断：这是什么类型短剧？核心冲突是什么？人物关系是什么？

### 2. 剧集/场次规划

不是直接生成一堆分镜，而是先规划：

- 第几集
- 第几场
- 场景在哪里
- 本场戏的情绪目标
- 本场戏的冲突点
- 需要哪些角色

### 3. 角色与资产锁定

先锁：

- 主角脸
- 服装
- 场景
- 重要道具
- 整体视觉风格

### 4. 分镜导演

每个镜头要带：

- 镜头类型
- 景别
- 机位
- 人物数量
- 情绪
- 动作
- 台词/旁白
- 生成风险
- 参考资产

### 5. 生成前审查

判断这个镜头能不能直接生成：

- 人数是否过多
- 脸是否要求清楚
- 是否远景看脸
- 是否缺角色参考
- 是否缺场景参考
- 是否动作过载

### 6. 关键帧生成

先出关键帧，不直接出视频。关键帧过审后再进入视频。

### 7. 审关键帧

检查：

- 角色像不像
- 场景对不对
- 情绪对不对
- 构图能不能剪

### 8. 视频生成

只让通过审查的关键帧进视频。

### 9. 审视频

检查：

- 人物是否漂移
- 动作是否自然
- 镜头是否稳定
- 情绪是否连续
- 是否能剪

### 10. 剪辑成片

按场次节奏组接：

- 建立镜头
- 对话镜头
- 反应镜头
- 特写
- 情绪爆点
- 转场
- 音乐字幕
"""


def _characters_template(*, project_name: str) -> str:
    return f"""# 角色表 - {project_name}

## 主角

- 姓名：
- 年龄：
- 身份：
- 外貌锚点：
- 性格锚点：
- 情绪弧线：
- 参考资产：

## 重要角色

每个角色都需要记录身份、关系、服装、发型、参考图和不可变约束。
"""


def _episodes_template(*, project_name: str) -> str:
    return f"""# 剧集规划 - {project_name}

## 故事一句话

待填写。

## 核心冲突

待填写。

## 分集规划

### 第 1 集

- 本集目标：
- 情绪推进：
- 关键反转：
- 主要场次：
"""


def _scene_template(*, project_name: str) -> str:
    return f"""# 第 1 集 第 1 场 - {project_name}

## 场次目标

- 场景地点：
- 出场角色：
- 情绪目标：
- 冲突点：
- 剧情功能：

## 剧本正文

待填写。

## 分镜导演要求

- 建立镜头：
- 对话镜头：
- 反应镜头：
- 特写：
- 情绪爆点：
- 转场：
"""


def _shots_template(*, project_id: str) -> str:
    payload = {
        "version": "shortdrama_shots_v1",
        "project_id": project_id,
        "episode": 1,
        "scene": "episode-01-scene-01",
        "shots": [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _decisions_template() -> str:
    return """# 决策记忆

记录已经确定的项目规则、人物关系、风格选择、场次安排和不可轻易改变的判断。

## 已确认决策

- 待记录。
"""


def _failures_template() -> str:
    return """# 失败记忆

记录生成失败、审片失败、剪辑不可用的原因，以及下次如何避免。

## 失败记录

- 待记录。
"""


def _constraints_template() -> str:
    return """# 制作约束

## 精品短剧生成约束

- 重要人物必须先锁定角色参考。
- 同一场戏优先锁定场景参考。
- 需要看清脸的镜头避免远景和全景。
- 多人复杂调度优先拆成双人关系镜头、反应镜头和特写。
- 关键帧未过审，不进入视频。
- 视频未过审，不进入剪辑。
"""
