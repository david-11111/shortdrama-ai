from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FINAL_EDIT_KEYWORDS = ("剪辑", "剪輯", "成片", "导出", "導出", "配音", "字幕", "音乐", "音樂", "bgm", "final cut", "export")
MISSING_OR_QUESTION_KEYWORDS = (
    "为什么",
    "为何",
    "怎么",
    "咋",
    "没",
    "沒有",
    "没有",
    "不见",
    "在哪",
    "呢",
    "why",
    "missing",
    "where",
)


@dataclass(frozen=True)
class ControlIntent:
    intent_type: str
    tool_name: str
    action: str
    dispatch_ready: bool
    reason: str


def classify_control_intent(instruction: str) -> ControlIntent | None:
    text = str(instruction or "").strip().lower()
    if not text:
        return None
    if _contains_any(text, FINAL_EDIT_KEYWORDS):
        if _contains_any(text, MISSING_OR_QUESTION_KEYWORDS):
            return ControlIntent(
                intent_type="ui_diagnostic",
                tool_name="diagnose_outputs",
                action="status_query",
                dispatch_ready=True,
                reason="用户在追问剪辑/成片产物，应先读取视频素材、剪辑任务、最终产物和写回证据。",
            )
        return ControlIntent(
            intent_type="production_action",
            tool_name="plan_final_edit",
            action="plan_final_edit",
            dispatch_ready=True,
            reason="用户明确要求剪辑、配音、字幕、音乐或成片导出，应使用现有剧本和视频素材进入剪辑成片。",
        )
    if _contains_any(
        text,
        (
            "图片池",
            "候选图",
            "多角度",
            "多做几张图",
            "多生成几张图",
            "几张关键帧",
            "批量关键帧",
            "keyframe pool",
            "keyframe batch",
            "candidate image",
        ),
    ):
        return ControlIntent(
            intent_type="keyframe_pool_diagnostic",
            tool_name="diagnose_keyframe_pool",
            action="status_query",
            dispatch_ready=True,
            reason="用户在处理一个镜头的多张关键帧/候选图，应先读取图片池证据，再决定扩展 prompt、批量生成、选择候选或生成视频。",
        )
    if _contains_any(
        text,
        (
            "剧本",
            "脚本",
            "分镜",
            "台词",
            "对白",
            "旁白",
            "前三秒",
            "钩子",
            "冲突",
            "节奏",
            "卖点",
            "人设",
            "开头",
            "结尾",
            "story",
            "script",
            "storyboard",
            "dialogue",
            "hook",
        ),
    ):
        return ControlIntent(
            intent_type="script_diagnostic",
            tool_name="diagnose_script",
            action="status_query",
            dispatch_ready=True,
            reason="用户在处理剧本、分镜、台词或叙事节奏问题，应先读取当前剧本/镜头证据，再决定由 DeepSeek 直接答复还是派发 generate_story_plan。",
        )
    if _contains_any(text, ("补上", "補上", "补齐", "補齊", "修复缺失", "重新补", "repair missing")):
        return ControlIntent(
            intent_type="production_action",
            tool_name="repair_missing_images",
            action="generate_keyframes",
            dispatch_ready=True,
            reason="用户要求补齐缺失图片，应进入关键帧/参考图补齐动作。",
        )
    if _contains_any(text, ("写回", "回写", "selected_image", "selected_video", "provider", "seedream", "seedance", "kling")):
        return ControlIntent(
            intent_type="provider_diagnostic",
            tool_name="diagnose_provider_writeback",
            action="status_query",
            dispatch_ready=True,
            reason="用户在追问 provider 或写回链路，应检查任务结果、写回事件和 shot_rows 字段。",
        )
    if _contains_any(text, ("任务", "卡住", "失败", "报错", "队列", "进度", "running", "queued", "failed", "stuck")):
        return ControlIntent(
            intent_type="task_diagnostic",
            tool_name="diagnose_tasks",
            action="status_query",
            dispatch_ready=True,
            reason="用户在追问任务状态，应检查活动任务、失败任务和推荐恢复动作。",
        )
    if _contains_any(
        text,
        (
            "没显示",
            "沒有顯示",
            "不显示",
            "不顯示",
            "显示不了",
            "顯示不了",
            "没出来",
            "沒有出來",
            "看不到",
            "破图",
            "破圖",
            "加载失败",
            "載入失敗",
            "missing image",
            "not showing",
            "not visible",
            "broken image",
        ),
    ):
        return ControlIntent(
            intent_type="ui_diagnostic",
            tool_name="diagnose_outputs",
            action="status_query",
            dispatch_ready=True,
            reason="用户在报告成果区图片/产物显示问题，应先查快照、写回字段和 URL 可访问性。",
        )
    return None


def diagnose_outputs_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {
            "tool_name": "diagnose_outputs",
            "summary": {"image_count": 0, "video_count": 0, "shot_count": 0},
            "images": [],
            "videos": [],
            "broken_images": [],
            "risky_images": [],
            "broken_videos": [],
            "risky_videos": [],
            "empty_image_rows": [],
            "empty_video_rows": [],
            "zero_duration_video_rows": [],
            "likely_cause": "snapshot_missing",
            "recommended_action": "reload_snapshot",
        }
    outputs = snapshot.get("outputs") if isinstance(snapshot.get("outputs"), dict) else {}
    images = outputs.get("images") if isinstance(outputs.get("images"), list) else []
    videos = outputs.get("videos") if isinstance(outputs.get("videos"), list) else []
    shots = outputs.get("shots") if isinstance(outputs.get("shots"), list) else []
    normalized_images = [_diagnostic_image(item) for item in images if isinstance(item, dict)]
    normalized_videos = [_diagnostic_video(item) for item in videos if isinstance(item, dict)]
    broken = [item for item in normalized_images if item.get("issue") == "missing_url"]
    risky = [item for item in normalized_images if item.get("issue") in {"signed_url", "external_url", "local_reference"}]
    broken_videos = [item for item in normalized_videos if item.get("issue") == "missing_url"]
    risky_videos = [item for item in normalized_videos if item.get("issue") in {"signed_url", "external_url", "local_reference"}]
    empty = [
        {
            "shot_index": shot.get("shot_index"),
            "status": shot.get("status") or "",
            "reason": "selected_image 为空",
        }
        for shot in shots
        if isinstance(shot, dict) and not str(shot.get("selected_image") or "").strip()
    ]
    empty_videos = [
        {
            "shot_index": shot.get("shot_index"),
            "status": shot.get("status") or "",
            "reason": "selected_video 为空",
        }
        for shot in shots
        if isinstance(shot, dict)
        and str(shot.get("selected_image") or "").strip()
        and not str(shot.get("selected_video") or "").strip()
    ]
    zero_duration_videos = [
        {
            "shot_index": shot.get("shot_index"),
            "duration": shot.get("duration") or 0,
            "reason": "视频时长为 0 或未写入时长",
        }
        for shot in shots
        if isinstance(shot, dict)
        and str(shot.get("selected_video") or "").strip()
        and _safe_float(shot.get("duration")) <= 0
    ]
    return {
        "tool_name": "diagnose_outputs",
        "summary": outputs.get("summary") if isinstance(outputs.get("summary"), dict) else {},
        "images": normalized_images,
        "videos": normalized_videos,
        "broken_images": broken,
        "risky_images": risky,
        "broken_videos": broken_videos,
        "risky_videos": risky_videos,
        "empty_image_rows": empty,
        "empty_video_rows": empty_videos,
        "zero_duration_video_rows": zero_duration_videos,
        "likely_cause": _output_likely_cause(
            broken=broken,
            risky=risky,
            empty=empty,
            broken_videos=broken_videos,
            risky_videos=risky_videos,
            empty_videos=empty_videos,
            zero_duration_videos=zero_duration_videos,
        ),
        "recommended_action": _output_recommended_action(
            broken=broken,
            risky=risky,
            empty=empty,
            broken_videos=broken_videos,
            risky_videos=risky_videos,
            empty_videos=empty_videos,
            zero_duration_videos=zero_duration_videos,
        ),
    }


def diagnose_tasks_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    tasks = snapshot.get("tasks") if isinstance((snapshot or {}).get("tasks"), list) else []
    normalized = [_diagnostic_task(task) for task in tasks if isinstance(task, dict)]
    active = [task for task in normalized if task["status"] in {"pending", "queued", "retrying", "running", "worker_started", "provider_requesting", "provider_waiting", "downloading", "uploading", "writing_back", "dispatching"}]
    failed = [task for task in normalized if task["status"] in {"failed", "dead_letter", "cancelled"}]
    provider_waiting = [task for task in active if task["status"] in {"provider_requesting", "provider_waiting"} or task.get("provider")]
    return {
        "tool_name": "diagnose_tasks",
        "task_count": len(normalized),
        "active_tasks": active,
        "failed_tasks": failed,
        "provider_waiting_tasks": provider_waiting,
        "likely_cause": _task_likely_cause(active=active, failed=failed, provider_waiting=provider_waiting),
        "recommended_action": _task_recommended_action(active=active, failed=failed),
    }


def diagnose_provider_writeback_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    tasks = snapshot.get("tasks") if isinstance((snapshot or {}).get("tasks"), list) else []
    outputs = snapshot.get("outputs") if isinstance((snapshot or {}).get("outputs"), dict) else {}
    shots = outputs.get("shots") if isinstance(outputs.get("shots"), list) else []
    events = _flatten_events((snapshot or {}).get("events"))
    media_tasks = [_diagnostic_task(task) for task in tasks if isinstance(task, dict) and str(task.get("task_type") or "") in {"image_gen", "video_gen"}]
    image_result_shots = {task.get("shot_index") for task in media_tasks if task.get("task_type") == "image_gen" and task.get("result_url_count")}
    video_result_shots = {task.get("shot_index") for task in media_tasks if task.get("task_type") == "video_gen" and task.get("result_url_count")}
    selected_image_shots = {shot.get("shot_index") for shot in shots if isinstance(shot, dict) and str(shot.get("selected_image") or "").strip()}
    selected_video_shots = {shot.get("shot_index") for shot in shots if isinstance(shot, dict) and str(shot.get("selected_video") or "").strip()}
    missing_image_writeback = sorted(item for item in image_result_shots - selected_image_shots if item not in (None, ""))
    missing_video_writeback = sorted(item for item in video_result_shots - selected_video_shots if item not in (None, ""))
    writeback_events = [
        {
            "phase": event.get("phase") or "",
            "status": event.get("status") or "",
            "summary": event.get("summary") or event.get("detail") or "",
        }
        for event in events
        if "writeback" in str(event.get("phase") or "").lower() or event.get("event_type") == "writeback"
    ][-10:]
    return {
        "tool_name": "diagnose_provider_writeback",
        "media_task_count": len(media_tasks),
        "image_result_shots": sorted(item for item in image_result_shots if item not in (None, "")),
        "video_result_shots": sorted(item for item in video_result_shots if item not in (None, "")),
        "selected_image_shots": sorted(item for item in selected_image_shots if item not in (None, "")),
        "selected_video_shots": sorted(item for item in selected_video_shots if item not in (None, "")),
        "missing_image_writeback": missing_image_writeback,
        "missing_video_writeback": missing_video_writeback,
        "writeback_events": writeback_events,
        "likely_cause": _provider_likely_cause(missing_image_writeback, missing_video_writeback),
        "recommended_action": _provider_recommended_action(missing_image_writeback, missing_video_writeback),
    }


def diagnose_script_from_snapshot(snapshot: dict[str, Any] | None, *, instruction: str = "") -> dict[str, Any]:
    outputs = snapshot.get("outputs") if isinstance((snapshot or {}).get("outputs"), dict) else {}
    script = outputs.get("script") if isinstance(outputs.get("script"), dict) else {}
    notes = outputs.get("director_notes") if isinstance(outputs.get("director_notes"), list) else []
    shots = outputs.get("shots") if isinstance(outputs.get("shots"), list) else []
    script_items = script.get("items") if isinstance(script.get("items"), list) else []
    content = str(script.get("content") or "").strip()
    if not content and script_items and isinstance(script_items[-1], dict):
        content = str(script_items[-1].get("content") or "").strip()
    normalized_shots = [
        {
            "shot_index": shot.get("shot_index"),
            "prompt": str(shot.get("prompt") or "").strip(),
            "duration": shot.get("duration") or 0,
            "status": shot.get("status") or "",
        }
        for shot in shots
        if isinstance(shot, dict)
    ]
    requirements = _extract_script_requirements(instruction)
    missing = []
    if not content:
        missing.append("script_content")
    if not normalized_shots:
        missing.append("shot_rows")
    return {
        "tool_name": "diagnose_script",
        "summary": {
            "has_script": bool(content),
            "script_item_count": len(script_items),
            "shot_count": len(normalized_shots),
            "director_note_count": len([item for item in notes if isinstance(item, dict)]),
        },
        "script_excerpt": _truncate_text(content, 500),
        "shots": normalized_shots[:12],
        "director_notes": [
            {
                "title": str(item.get("title") or "").strip(),
                "content": _truncate_text(str(item.get("content") or "").strip(), 240),
                "source": str(item.get("source") or "").strip(),
            }
            for item in notes[:8]
            if isinstance(item, dict)
        ],
        "extracted_requirements": requirements,
        "missing": missing,
        "likely_cause": _script_likely_cause(content=content, shots=normalized_shots, requirements=requirements),
        "recommended_action": _script_recommended_action(content=content, shots=normalized_shots, requirements=requirements),
    }


def diagnose_keyframe_pool_from_snapshot(snapshot: dict[str, Any] | None, *, instruction: str = "") -> dict[str, Any]:
    outputs = snapshot.get("outputs") if isinstance((snapshot or {}).get("outputs"), dict) else {}
    pools_source = outputs.get("keyframe_pool") if isinstance(outputs.get("keyframe_pool"), list) else []
    shots = outputs.get("shots") if isinstance(outputs.get("shots"), list) else []
    images = outputs.get("images") if isinstance(outputs.get("images"), list) else []
    pools = pools_source or _keyframe_pools_from_outputs(shots=shots, images=images)
    target_shots = _extract_target_shots(instruction)
    if target_shots:
        pools = [pool for pool in pools if pool.get("shot_index") in target_shots]
    total_candidates = sum(int((pool.get("summary") or {}).get("candidate_count") or 0) for pool in pools if isinstance(pool, dict))
    selected_count = sum(int((pool.get("summary") or {}).get("selected_count") or 0) for pool in pools if isinstance(pool, dict))
    running_count = sum(int((pool.get("summary") or {}).get("running_count") or 0) for pool in pools if isinstance(pool, dict))
    failed_count = sum(int((pool.get("summary") or {}).get("failed_count") or 0) for pool in pools if isinstance(pool, dict))
    strategy = _keyframe_variation_strategy(instruction)
    return {
        "tool_name": "diagnose_keyframe_pool",
        "summary": {
            "shot_pool_count": len(pools),
            "candidate_count": total_candidates,
            "selected_count": selected_count,
            "running_count": running_count,
            "failed_count": failed_count,
            "target_shots": target_shots,
            "variation_strategy": strategy,
        },
        "pools": pools[:12],
        "draft_prompts": _draft_keyframe_prompts(pools[:3], strategy=strategy, instruction=instruction),
        "likely_cause": _keyframe_pool_likely_cause(pools=pools, total_candidates=total_candidates, selected_count=selected_count, running_count=running_count),
        "recommended_action": _keyframe_pool_recommended_action(
            instruction=instruction,
            pools=pools,
            total_candidates=total_candidates,
            selected_count=selected_count,
            running_count=running_count,
        ),
    }


def render_output_diagnostic_answer(
    diagnosis: dict[str, Any],
    *,
    current_status: str,
    active_tasks: dict[str, Any],
) -> str:
    images = diagnosis.get("images") if isinstance(diagnosis.get("images"), list) else []
    videos = diagnosis.get("videos") if isinstance(diagnosis.get("videos"), list) else []
    broken = diagnosis.get("broken_images") if isinstance(diagnosis.get("broken_images"), list) else []
    risky = diagnosis.get("risky_images") if isinstance(diagnosis.get("risky_images"), list) else []
    broken_videos = diagnosis.get("broken_videos") if isinstance(diagnosis.get("broken_videos"), list) else []
    risky_videos = diagnosis.get("risky_videos") if isinstance(diagnosis.get("risky_videos"), list) else []
    empty = diagnosis.get("empty_image_rows") if isinstance(diagnosis.get("empty_image_rows"), list) else []
    empty_videos = diagnosis.get("empty_video_rows") if isinstance(diagnosis.get("empty_video_rows"), list) else []
    zero_duration_videos = diagnosis.get("zero_duration_video_rows") if isinstance(diagnosis.get("zero_duration_video_rows"), list) else []

    parts = [f"我查了当前成果区快照：记录到 {len(images)} 张参考图/关键帧、{len(videos)} 个视频。"]
    if broken:
        labels = "、".join(_asset_label(item) for item in broken[:5])
        parts.append(f"有 {len(broken)} 张没有可加载 URL：{labels}。")
    if risky:
        labels = "、".join(_asset_label(item) for item in risky[:5])
        parts.append(f"有 {len(risky)} 张属于外部、签名或本地引用，可能因为过期、403、防盗链或本地引用无法解析而不显示：{labels}。")
    if empty:
        labels = "、".join(f"第 {item.get('shot_index')} 镜" if item.get("shot_index") not in (None, "") else "-" for item in empty[:8])
        parts.append(f"还有 {len(empty)} 个镜头没有写入 selected_image：{labels}。")
    if broken_videos:
        labels = "、".join(_asset_label(item) for item in broken_videos[:5])
        parts.append(f"有 {len(broken_videos)} 个视频没有可加载 URL：{labels}。")
    if risky_videos:
        labels = "、".join(_asset_label(item) for item in risky_videos[:5])
        parts.append(f"有 {len(risky_videos)} 个视频 URL 属于外部、签名或本地引用，可能过期、403 或无法解析：{labels}。")
    if empty_videos:
        labels = "、".join(f"第 {item.get('shot_index')} 镜" if item.get("shot_index") not in (None, "") else "-" for item in empty_videos[:8])
        parts.append(f"还有 {len(empty_videos)} 个镜头没有写入 selected_video：{labels}。")
    if zero_duration_videos:
        labels = "、".join(f"第 {item.get('shot_index')} 镜" if item.get("shot_index") not in (None, "") else "-" for item in zero_duration_videos[:8])
        parts.append(f"有 {len(zero_duration_videos)} 个视频字段存在但时长为 0：{labels}。")
    if not broken and not risky and not empty and not broken_videos and not risky_videos and not empty_videos and not zero_duration_videos:
        parts.append("后端快照里的图片和视频字段完整；如果页面仍不显示，下一步要看浏览器 Network 里的媒体请求状态码。")
    if int(active_tasks.get("count") or 0) > 0:
        parts.append(f"同时还有任务在跑：{_active_tasks_sentence(active_tasks)}。")
    parts.append(_recommendation_sentence(str(diagnosis.get("recommended_action") or ""), current_status=current_status))
    return "".join(parts)


def render_task_diagnostic_answer(diagnosis: dict[str, Any]) -> str:
    active = diagnosis.get("active_tasks") if isinstance(diagnosis.get("active_tasks"), list) else []
    failed = diagnosis.get("failed_tasks") if isinstance(diagnosis.get("failed_tasks"), list) else []
    provider_waiting = diagnosis.get("provider_waiting_tasks") if isinstance(diagnosis.get("provider_waiting_tasks"), list) else []
    parts = [f"我查了任务队列：共有 {diagnosis.get('task_count') or 0} 个任务。"]
    if active:
        parts.append(f"正在执行 {len(active)} 个：{_task_labels(active)}。")
    if failed:
        parts.append(f"失败/终止 {len(failed)} 个：{_task_labels(failed)}。")
    if provider_waiting:
        parts.append(f"其中 {len(provider_waiting)} 个涉及 provider 等待或请求：{_task_labels(provider_waiting)}。")
    if not active and not failed:
        parts.append("没有发现活动任务或失败任务。")
    parts.append(_task_recommendation_sentence(str(diagnosis.get("recommended_action") or "")))
    return "".join(parts)


def render_provider_writeback_answer(diagnosis: dict[str, Any]) -> str:
    missing_images = diagnosis.get("missing_image_writeback") if isinstance(diagnosis.get("missing_image_writeback"), list) else []
    missing_videos = diagnosis.get("missing_video_writeback") if isinstance(diagnosis.get("missing_video_writeback"), list) else []
    parts = [f"我查了 provider 写回链路：媒体任务 {diagnosis.get('media_task_count') or 0} 个。"]
    parts.append(f"图片结果镜头 {diagnosis.get('image_result_shots') or []}，已写入 selected_image 的镜头 {diagnosis.get('selected_image_shots') or []}。")
    parts.append(f"视频结果镜头 {diagnosis.get('video_result_shots') or []}，已写入 selected_video 的镜头 {diagnosis.get('selected_video_shots') or []}。")
    if missing_images:
        parts.append(f"疑似图片结果未写回镜头：{missing_images}。")
    if missing_videos:
        parts.append(f"疑似视频结果未写回镜头：{missing_videos}。")
    if not missing_images and not missing_videos:
        parts.append("没有发现 provider 结果和 shot_rows 写回字段之间的明显断点。")
    parts.append(_provider_recommendation_sentence(str(diagnosis.get("recommended_action") or "")))
    return "".join(parts)


def render_script_diagnostic_answer(diagnosis: dict[str, Any]) -> str:
    summary = diagnosis.get("summary") if isinstance(diagnosis.get("summary"), dict) else {}
    requirements = diagnosis.get("extracted_requirements") if isinstance(diagnosis.get("extracted_requirements"), dict) else {}
    shots = diagnosis.get("shots") if isinstance(diagnosis.get("shots"), list) else []
    missing = diagnosis.get("missing") if isinstance(diagnosis.get("missing"), list) else []
    parts = [
        f"我先查了当前剧本链路：剧本产物 {summary.get('script_item_count') or 0} 条，分镜 {summary.get('shot_count') or len(shots)} 个，导演建议 {summary.get('director_note_count') or 0} 条。"
    ]
    if missing:
        parts.append(f"当前缺少 {', '.join(str(item) for item in missing)}，需要先生成或重建剧本/分镜。")
    else:
        excerpt = str(diagnosis.get("script_excerpt") or "").strip()
        if excerpt:
            parts.append(f"已有剧本摘要：{_truncate_text(excerpt, 160)}")
    requirement_labels = _script_requirement_labels(requirements)
    if requirement_labels:
        parts.append(f"我从你的需求里提取到：{'; '.join(requirement_labels)}。")
    if shots:
        shot_labels = []
        for shot in shots[:5]:
            if not isinstance(shot, dict):
                continue
            label = f"第 {shot.get('shot_index')} 镜" if shot.get("shot_index") not in (None, "") else "未编号镜头"
            prompt = _truncate_text(str(shot.get("prompt") or "").strip(), 48)
            shot_labels.append(f"{label}: {prompt}" if prompt else label)
        if shot_labels:
            parts.append(f"当前分镜证据：{'；'.join(shot_labels)}。")
    parts.append(_script_recommendation_sentence(str(diagnosis.get("recommended_action") or "")))
    return "".join(parts)


def render_keyframe_pool_diagnostic_answer(diagnosis: dict[str, Any]) -> str:
    summary = diagnosis.get("summary") if isinstance(diagnosis.get("summary"), dict) else {}
    pools = diagnosis.get("pools") if isinstance(diagnosis.get("pools"), list) else []
    parts = [
        f"我查了图片池：覆盖 {summary.get('shot_pool_count') or 0} 个镜头，共 {summary.get('candidate_count') or 0} 张候选图，已选 {summary.get('selected_count') or 0} 张，运行中 {summary.get('running_count') or 0} 个，失败 {summary.get('failed_count') or 0} 个。"
    ]
    if pools:
        labels = []
        for pool in pools[:5]:
            if not isinstance(pool, dict):
                continue
            shot = pool.get("shot_index")
            pool_summary = pool.get("summary") if isinstance(pool.get("summary"), dict) else {}
            labels.append(
                f"第 {shot} 镜候选 {pool_summary.get('candidate_count') or 0} 张/已选 {pool_summary.get('selected_count') or 0} 张"
                if shot not in (None, "")
                else f"未编号镜头候选 {pool_summary.get('candidate_count') or 0} 张"
            )
        if labels:
            parts.append(f"镜头概况：{'；'.join(labels)}。")
    prompts = diagnosis.get("draft_prompts") if isinstance(diagnosis.get("draft_prompts"), list) else []
    if prompts:
        parts.append(f"我可以先扩展这些关键帧方向：{'；'.join(str(item.get('prompt') or '') for item in prompts[:3] if isinstance(item, dict))}。")
    parts.append(_keyframe_pool_recommendation_sentence(str(diagnosis.get("recommended_action") or "")))
    return "".join(parts)


def _diagnostic_image(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or item.get("uri") or "").strip()
    issue = ""
    if not url:
        issue = "missing_url"
    elif url.startswith("local://") or url.startswith("file://"):
        issue = "local_reference"
    elif _looks_like_signed_url(url):
        issue = "signed_url"
    elif url.startswith("http://") or url.startswith("https://"):
        issue = "external_url"
    return {
        "shot_index": item.get("shot_index"),
        "kind": item.get("kind") or item.get("artifact_type") or "image",
        "title": item.get("title") or item.get("summary") or "图片",
        "url": url,
        "source": item.get("source") or "",
        "issue": issue,
        "reason": _image_issue_reason(issue),
    }


def _diagnostic_video(item: dict[str, Any]) -> dict[str, Any]:
    value = _diagnostic_image(item)
    value["kind"] = item.get("kind") or item.get("artifact_type") or "video"
    value["title"] = item.get("title") or item.get("summary") or "视频"
    return value


def _diagnostic_task(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    provider = str(payload.get("provider") or payload.get("video_provider") or payload.get("image_provider") or payload.get("tool") or "").strip()
    return {
        "task_id": str(task.get("task_id") or ""),
        "task_type": str(task.get("task_type") or ""),
        "status": str(task.get("status") or ""),
        "progress": task.get("progress"),
        "stage_text": str(task.get("stage_text") or ""),
        "error_message": str(task.get("error_message") or ""),
        "provider": provider,
        "shot_index": payload.get("shot_index") or result.get("shot_index"),
        "result_url_count": len(_urls_from_value(result)),
    }


def _flatten_events(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        rows: list[dict[str, Any]] = []
        for items in value.values():
            if isinstance(items, list):
                rows.extend(item for item in items if isinstance(item, dict))
        return rows
    return []


def _urls_from_value(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("http://", "https://", "/storage/", "/static/", "storage/", "uploads/", "local://")):
            urls.append(stripped)
        return urls
    if isinstance(value, list):
        for item in value:
            urls.extend(_urls_from_value(item))
        return urls
    if isinstance(value, dict):
        for key in ("url", "uri", "image_url", "video_url", "selected_image", "selected_video", "oss_url", "result_url", "file_url"):
            urls.extend(_urls_from_value(value.get(key)))
    return urls


def _keyframe_pools_from_outputs(*, shots: list[Any], images: list[Any]) -> list[dict[str, Any]]:
    by_shot: dict[Any, dict[str, Any]] = {}
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        shot_index = shot.get("shot_index")
        candidates = [_pool_candidate_from_value(item, shot_index=shot_index, selected=False, source="shot_rows") for item in _candidate_values(shot.get("image_candidates"))]
        selected_image = str(shot.get("selected_image") or "").strip()
        if selected_image:
            candidates.insert(0, _pool_candidate_from_value(selected_image, shot_index=shot_index, selected=True, source="shot_rows"))
        by_shot[shot_index] = {
            "shot_index": shot_index,
            "prompt": str(shot.get("prompt") or "").strip(),
            "status": shot.get("status") or "",
            "candidates": _dedupe_candidates(candidates),
        }
    for image in images:
        if not isinstance(image, dict):
            continue
        shot_index = image.get("shot_index")
        pool = by_shot.setdefault(shot_index, {"shot_index": shot_index, "prompt": "", "status": "", "candidates": []})
        pool["candidates"].append(
            _pool_candidate_from_value(
                {"url": image.get("url"), "artifact_id": image.get("id"), "kind": image.get("kind"), "summary": image.get("summary")},
                shot_index=shot_index,
                selected=str(image.get("kind") or "") == "selected_image",
                source=str(image.get("source") or "outputs"),
            )
        )
        pool["candidates"] = _dedupe_candidates(pool["candidates"])
    result = []
    for pool in by_shot.values():
        candidates = pool.get("candidates") if isinstance(pool.get("candidates"), list) else []
        pool["summary"] = {
            "candidate_count": len(candidates),
            "selected_count": sum(1 for item in candidates if item.get("selected")),
            "running_count": 0,
            "failed_count": sum(1 for item in candidates if str(item.get("status") or "") in {"failed", "error"}),
        }
        result.append(pool)
    return sorted(result, key=lambda item: (item.get("shot_index") is None, item.get("shot_index") or 0))


def _candidate_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def _pool_candidate_from_value(value: Any, *, shot_index: Any, selected: bool, source: str) -> dict[str, Any]:
    if isinstance(value, dict):
        url = str(value.get("url") or value.get("uri") or value.get("image_url") or "").strip()
        review = value.get("review") if isinstance(value.get("review"), dict) else {}
        quality_score = value.get("quality_score", review.get("quality_score"))
        return {
            "artifact_id": str(value.get("artifact_id") or value.get("id") or ""),
            "shot_index": value.get("shot_index", shot_index),
            "url": url,
            "prompt": str(value.get("prompt") or value.get("summary") or "").strip(),
            "provider": str(value.get("provider") or value.get("source") or source).strip(),
            "status": str(value.get("status") or "ready").strip(),
            "selected": bool(value.get("selected")) or selected,
            "quality_score": quality_score,
            "source": source,
        }
    return {
        "artifact_id": "",
        "shot_index": shot_index,
        "url": str(value or "").strip(),
        "prompt": "",
        "provider": source,
        "status": "ready",
        "selected": selected,
        "quality_score": None,
        "source": source,
    }


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for candidate in candidates:
        key = str(candidate.get("url") or candidate.get("artifact_id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _keyframe_variation_strategy(instruction: str) -> str:
    text_value = str(instruction or "").lower()
    if _contains_any(text_value, ("角度", "侧脸", "全景", "特写", "angle")):
        return "angle"
    if _contains_any(text_value, ("光影", "冷色", "暖色", "lighting")):
        return "lighting"
    if _contains_any(text_value, ("动作", "过程", "分解", "action")):
        return "action_step"
    return "mixed"


def _draft_keyframe_prompts(pools: list[Any], *, strategy: str, instruction: str) -> list[dict[str, Any]]:
    prompts = []
    strategy_labels = {
        "angle": ("侧脸关系角度", "道具/手部特写", "环境全景建立"),
        "lighting": ("冷色主光版本", "暖色侧逆光版本", "高对比电影光版本"),
        "action_step": ("动作起始帧", "动作推进帧", "情绪落点帧"),
        "mixed": ("人物中近景", "关键道具特写", "环境氛围全景"),
    }
    labels = strategy_labels.get(strategy, strategy_labels["mixed"])
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        shot_index = pool.get("shot_index")
        base = str(pool.get("prompt") or "").strip() or f"第 {shot_index} 镜"
        for label in labels:
            prompts.append({"shot_index": shot_index, "variation": label, "prompt": f"{base}，{label}，不得改变原分镜中的人物身份、地点、道具和动作目标"})
    return prompts[:9]


def _keyframe_pool_likely_cause(*, pools: list[dict[str, Any]], total_candidates: int, selected_count: int, running_count: int) -> str:
    if running_count:
        return "keyframe_tasks_running"
    if not pools or total_candidates == 0:
        return "keyframe_pool_empty"
    if selected_count == 0:
        return "candidate_not_selected"
    return "keyframe_pool_ready"


def _keyframe_pool_recommended_action(*, instruction: str, pools: list[dict[str, Any]], total_candidates: int, selected_count: int, running_count: int) -> str:
    text_value = str(instruction or "").lower()
    if running_count:
        return "inspect_keyframe_pool"
    if _contains_any(text_value, ("生成视频", "做视频", "动画", "过渡", "video", "morph")) and selected_count:
        return "generate_video_from_pool"
    if _contains_any(text_value, ("多做", "多生成", "多角度", "几张", "批量", "batch")):
        return "generate_keyframe_batch" if total_candidates else "expand_shot_to_keyframe_prompts"
    if total_candidates and selected_count == 0:
        return "select_keyframe_candidate"
    return "inspect_keyframe_pool"


def _output_likely_cause(
    *,
    broken: list[dict[str, Any]],
    risky: list[dict[str, Any]],
    empty: list[dict[str, Any]],
    broken_videos: list[dict[str, Any]],
    risky_videos: list[dict[str, Any]],
    empty_videos: list[dict[str, Any]],
    zero_duration_videos: list[dict[str, Any]],
) -> str:
    if empty:
        return "selected_image_missing"
    if empty_videos:
        return "selected_video_missing"
    if zero_duration_videos:
        return "video_duration_zero"
    if broken:
        return "image_url_missing"
    if broken_videos:
        return "video_url_missing"
    if risky:
        return "signed_or_external_url_unstable"
    if risky_videos:
        return "signed_or_external_video_url_unstable"
    return "frontend_or_network_rendering"


def _output_recommended_action(
    *,
    broken: list[dict[str, Any]],
    risky: list[dict[str, Any]],
    empty: list[dict[str, Any]],
    broken_videos: list[dict[str, Any]],
    risky_videos: list[dict[str, Any]],
    empty_videos: list[dict[str, Any]],
    zero_duration_videos: list[dict[str, Any]],
) -> str:
    if empty:
        return "repair_missing_images"
    if empty_videos or zero_duration_videos:
        return "repair_missing_videos"
    if broken or risky:
        return "refresh_asset_urls"
    if broken_videos or risky_videos:
        return "refresh_asset_urls"
    return "inspect_browser_network"


def _task_likely_cause(*, active: list[dict[str, Any]], failed: list[dict[str, Any]], provider_waiting: list[dict[str, Any]]) -> str:
    if failed:
        return "task_failures"
    if provider_waiting:
        return "provider_waiting"
    if active:
        return "tasks_still_running"
    return "no_active_or_failed_tasks"


def _task_recommended_action(*, active: list[dict[str, Any]], failed: list[dict[str, Any]]) -> str:
    if any(task.get("task_type") == "video_gen" for task in failed):
        return "retry_failed_videos"
    if any(task.get("task_type") == "image_gen" for task in failed):
        return "retry_failed_keyframes"
    if active:
        return "wait_active_tasks"
    return "inspect_outputs"


def _provider_likely_cause(missing_images: list[Any], missing_videos: list[Any]) -> str:
    if missing_images or missing_videos:
        return "provider_result_not_written_back"
    return "writeback_consistent"


def _provider_recommended_action(missing_images: list[Any], missing_videos: list[Any]) -> str:
    if missing_images:
        return "repair_missing_images"
    if missing_videos:
        return "repair_missing_videos"
    return "inspect_outputs"


def _script_likely_cause(*, content: str, shots: list[dict[str, Any]], requirements: dict[str, Any]) -> str:
    if not content and not shots:
        return "script_and_shots_missing"
    if not content:
        return "script_missing"
    if not shots:
        return "shots_missing"
    if _has_script_revision_requirement(requirements):
        return "script_revision_requested"
    return "script_status_query"


def _script_recommended_action(*, content: str, shots: list[dict[str, Any]], requirements: dict[str, Any]) -> str:
    if not content or not shots:
        return "revise_story_plan"
    if _has_script_revision_requirement(requirements):
        return "revise_story_plan"
    return "inspect_script"


def _recommendation_sentence(action: str, *, current_status: str) -> str:
    if action == "repair_missing_images":
        return "结论：先补齐没有 selected_image 的镜头，再刷新成果区。"
    if action == "repair_missing_videos":
        return "结论：先补齐没有 selected_video 或 0 秒的视频镜头，再刷新成果区。"
    if action == "refresh_asset_urls":
        return "结论：先修 URL 可访问性或把图片落到可控存储，再考虑是否重生图片。"
    if action == "reload_snapshot":
        return "结论：当前没有拿到快照证据，先刷新 Run 快照再判断。"
    return f"结论：后端字段看起来完整，Run 状态是 {current_status}；下一步检查浏览器 Network 的图片请求。"


def _task_recommendation_sentence(action: str) -> str:
    return {
        "retry_failed_videos": "结论：先重试失败视频，必要时换 provider。",
        "retry_failed_keyframes": "结论：先重试失败关键帧/参考图任务。",
        "wait_active_tasks": "结论：任务仍在执行，先不要重复派发，等当前任务落库后再判断。",
        "inspect_outputs": "结论：任务层没有明显异常，下一步检查成果区和写回字段。",
    }.get(action, "结论：继续检查任务和成果区证据。")


def _provider_recommendation_sentence(action: str) -> str:
    return {
        "repair_missing_images": "结论：有图片结果未落到 selected_image，下一步应补写或补齐这些镜头。",
        "repair_missing_videos": "结论：有视频结果未落到 selected_video，下一步应补写视频字段或重试视频生成。",
        "inspect_outputs": "结论：写回链路看起来一致，下一步检查成果区渲染或 URL 可访问性。",
    }.get(action, "结论：继续检查 provider 结果和写回字段。")


def _script_recommendation_sentence(action: str) -> str:
    if action == "revise_story_plan":
        return "结论：这是可执行的剧本/分镜处理请求，下一步应派发 generate_story_plan，并把你的修改要求作为本轮约束传进去。"
    if action == "inspect_script":
        return "结论：当前更像剧本状态查询，先反馈现有剧本和分镜证据，不盲目重写。"
    return "结论：继续检查剧本、分镜和导演建议证据。"


def _keyframe_pool_recommendation_sentence(action: str) -> str:
    return {
        "inspect_keyframe_pool": "结论：当前先展示图片池证据，不重复派发生成。",
        "expand_shot_to_keyframe_prompts": "结论：下一步应先扩展多个关键帧提示词，作为批量出图的 dry-run 预览。",
        "generate_keyframe_batch": "结论：这是可执行的批量关键帧需求，下一步应进入 generate_keyframes 边界并受成本、并发和状态机 gate 控制。",
        "select_keyframe_candidate": "结论：已有候选图但还没选主图，下一步应选择候选图写入 selected_image。",
        "repair_keyframe_pool": "结论：图片池需要修复或补齐，下一步应补生成缺失关键帧。",
        "generate_video_from_pool": "结论：图片池已有可用主图，可以进入视频生成边界。",
    }.get(action, "结论：继续检查图片池证据。")


def _extract_script_requirements(instruction: str) -> dict[str, Any]:
    text_value = str(instruction or "").strip()
    lower = text_value.lower()
    return {
        "raw": text_value,
        "hook": _contains_any(lower, ("前三秒", "钩子", "开头", "hook")),
        "conflict": _contains_any(lower, ("冲突", "反转", "矛盾", "conflict")),
        "pacing": _contains_any(lower, ("节奏", "拖", "太慢", "太快", "pacing")),
        "selling_point": _contains_any(lower, ("卖点", "产品", "商品", "转化", "selling")),
        "dialogue": _contains_any(lower, ("台词", "对白", "旁白", "dialogue", "voiceover")),
        "ending": _contains_any(lower, ("结尾", "收尾", "ending")),
        "rewrite": _contains_any(lower, ("改", "重写", "润色", "优化", "加强", "不行", "弱", "rewrite", "revise")),
        "target_shots": _extract_target_shots(text_value),
    }


def _has_script_revision_requirement(requirements: dict[str, Any]) -> bool:
    if not requirements:
        return False
    keys = ("hook", "conflict", "pacing", "selling_point", "dialogue", "ending", "rewrite")
    return any(bool(requirements.get(key)) for key in keys) or bool(requirements.get("target_shots"))


def _script_requirement_labels(requirements: dict[str, Any]) -> list[str]:
    labels = []
    mapping = (
        ("hook", "开头/前三秒钩子"),
        ("conflict", "冲突或反转"),
        ("pacing", "节奏"),
        ("selling_point", "产品/卖点"),
        ("dialogue", "台词/旁白"),
        ("ending", "结尾"),
        ("rewrite", "重写/润色"),
    )
    for key, label in mapping:
        if requirements.get(key):
            labels.append(label)
    target_shots = requirements.get("target_shots")
    if target_shots:
        labels.append(f"指定镜头 {target_shots}")
    return labels


def _extract_target_shots(value: str) -> list[int]:
    digits = []
    current = ""
    for char in value:
        if char.isdigit():
            current += char
        elif current:
            digits.append(int(current))
            current = ""
    if current:
        digits.append(int(current))
    return [item for item in digits if 0 < item < 100][:8]


def _truncate_text(value: str, limit: int) -> str:
    text_value = str(value or "").strip()
    if len(text_value) <= limit:
        return text_value
    return text_value[: max(0, limit - 1)] + "…"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _task_labels(tasks: list[dict[str, Any]]) -> str:
    return "；".join(_active_task_label(task) for task in tasks[:5])


def _asset_label(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    shot = item.get("shot_index")
    title = item.get("title") or item.get("kind") or "图片"
    reason = item.get("reason") or item.get("issue") or ""
    prefix = f"第 {shot} 镜" if shot not in (None, "") else str(title)
    return f"{prefix}（{reason}）" if reason else prefix


def _active_tasks_sentence(active_tasks: dict[str, Any]) -> str:
    items = active_tasks.get("items")
    if isinstance(items, list) and items:
        return "；".join(_active_task_label(item) for item in items[:3])
    statuses = ", ".join(str(item) for item in active_tasks.get("statuses") or [])
    task_ids = ", ".join(str(item) for item in active_tasks.get("task_ids") or [])
    if task_ids:
        return f"状态 {statuses or 'unknown'}，任务 {task_ids}"
    return f"状态 {statuses or 'unknown'}"


def _active_task_label(task: Any) -> str:
    if not isinstance(task, dict):
        return str(task)
    task_type = str(task.get("task_type") or "task").strip()
    parts = [_task_type_name(task_type)]
    shot_index = task.get("shot_index")
    if shot_index not in (None, ""):
        parts.append(f"第 {shot_index} 镜")
    provider = str(task.get("provider") or "").strip()
    if provider:
        parts.append(f"provider {provider}")
    status = str(task.get("status") or "").strip()
    if status:
        parts.append(f"状态 {status}")
    progress = task.get("progress")
    if progress not in (None, ""):
        parts.append(f"进度 {progress}%")
    return "，".join(parts)


def _task_type_name(task_type: str) -> str:
    labels = {
        "video_gen": "视频生成",
        "image_gen": "图片/关键帧生成",
        "director_ref_images": "参考图生成",
        "director_script": "剧本/分镜生成",
        "director_prepare_shots": "分镜准备",
        "director_plan_edit": "剪辑规划",
        "director_export_preview": "预览导出",
        "director_export_final": "成片导出",
        "video_production_run": "生产流水线",
    }
    return labels.get(task_type, task_type or "任务")


def _looks_like_signed_url(url: str) -> bool:
    text_value = url.lower()
    return any(marker in text_value for marker in ("x-amz-", "expires=", "signature=", "token=", "ossaccesskeyid"))


def _image_issue_reason(issue: str) -> str:
    return {
        "missing_url": "没有可加载 URL",
        "local_reference": "本地/计划引用不能直接在浏览器展示",
        "signed_url": "签名 URL 可能过期或被拒绝",
        "external_url": "外部 URL 可能受 403、防盗链、CORS 或网络影响",
    }.get(issue, "")


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)
