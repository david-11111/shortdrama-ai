from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READ_ONLY_ACTIONS = {"inspect_outputs", "inspect_tasks", "inspect_provider_writeback", "inspect_script", "inspect_keyframe_pool"}
SAFE_WRITE_ACTIONS = {"generate_story_plan", "plan_visual_assets", "generate_keyframes", "generate_videos", "plan_final_edit"}
AUTO_FOLLOWUP_ACTIONS = {"generate_keyframes", "generate_videos", "generate_story_plan"}
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
QUESTION_OR_PROGRESS_KEYWORDS = (
    "?",
    "？",
    "吗",
    "嗎",
    "呢",
    "为什么",
    "為什麼",
    "为何",
    "為何",
    "怎么",
    "怎麼",
    "咋",
    "什么情况",
    "什麼情況",
    "到哪",
    "哪一步",
    "进度",
    "進度",
    "多久",
    "这么久",
    "這麼久",
    "怎么还",
    "怎麼還",
    "是不是",
    "卡住",
    "没在",
    "沒有在",
    "没生成",
    "沒有生成",
    "没剪辑",
    "沒剪輯",
    "why",
    "where",
    "status",
    "progress",
)
COMMAND_KEYWORDS = (
    "开始",
    "開始",
    "生成",
    "補",
    "补",
    "补齐",
    "補齊",
    "多做",
    "多生成",
    "修复",
    "修復",
    "重试",
    "重試",
    "重新",
    "重写",
    "重寫",
    "润色",
    "潤色",
    "修饰",
    "修飾",
    "加强",
    "調整",
    "调整",
    "剪辑",
    "剪輯",
    "导出",
    "導出",
    "执行",
    "執行",
    "继续",
    "繼續",
    "直接进入",
    "直接進入",
    "直接用",
    "跳过",
    "跳過",
    "redo",
    "regenerate",
    "retry",
    "fix",
)
CONFIRM_KEYWORDS = ("好的", "好", "可以", "确认", "確認", "执行吧", "執行吧", "继续吧", "繼續吧", "对", "對", "yes", "ok")


@dataclass(frozen=True)
class UtteranceFrame:
    utterance_type: str
    action_ceiling: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "utterance_type": self.utterance_type,
            "action_ceiling": self.action_ceiling,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ControllerIntent:
    intent_type: str
    tool_name: str
    action: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "tool_name": self.tool_name,
            "action": self.action,
            "dispatch_ready": True,
            "reason": self.reason,
        }


def classify_target_domain(instruction: str, *, action: str = "") -> str:
    text = str(instruction or "").strip().lower()
    action_value = str(action or "").strip()
    if action_value == "generate_story_plan" or _has_any(text, ("剧本", "腳本", "脚本", "分镜", "分鏡", "台词", "对白", "story", "script", "storyboard")):
        return "story"
    if action_value == "plan_visual_assets" or _has_any(text, ("参考图", "參考圖", "视觉资产", "视觉", "seedream", "reference", "asset")):
        return "visual_asset"
    if action_value == "plan_final_edit" or _has_any(text, FINAL_EDIT_KEYWORDS):
        return "final_edit"
    if action_value == "generate_keyframes" or _has_any(text, ("关键帧", "關鍵幀", "出图", "圖片", "图片", "首帧", "尾帧", "keyframe", "image")):
        return "keyframe"
    if action_value == "generate_videos" or _has_any(text, ("视频", "視頻", "seedance", "kling", "video")):
        return "video"
    if _has_any(text, ("任务", "队列", "卡住", "进度", "task", "queue", "stuck", "running", "failed")):
        return "task"
    if _has_any(text, ("provider", "写回", "回写", "selected_image", "selected_video")):
        return "provider"
    return "output"


def classify_utterance(instruction: str, *, explicit_action: bool = False) -> UtteranceFrame:
    text = str(instruction or "").strip().lower()
    if not text:
        return UtteranceFrame("empty", "inspect_only", "空输入只能保持只读检查。")
    if explicit_action:
        return UtteranceFrame("command", "execute_allowed", "用户显式选择了执行动作。")
    if _is_confirmation(text):
        return UtteranceFrame("confirm", "pending_confirm", "用户像是在确认上一条待执行动作。")
    if _has_any(text, QUESTION_OR_PROGRESS_KEYWORDS):
        return UtteranceFrame("question", "inspect_only", "用户是在提问、质疑或催进度，不能把诊断建议自动升级为生产执行。")
    if _has_any(text, COMMAND_KEYWORDS):
        return UtteranceFrame("command", "execute_allowed", "用户明确给出生产或修复命令。")
    return UtteranceFrame("feedback", "inspect_only", "用户是反馈或评价，先检查/追问，不自动派发生产任务。")


def classify_controller_intent(instruction: str) -> ControllerIntent | None:
    text = str(instruction or "").strip().lower()
    if not text:
        return None

    if _has_any(
        text,
        (
            "为什么没生成视频",
            "为何没生成视频",
            "怎么没生成视频",
            "没有生成视频",
            "没生成视频",
            "视频为什么没有",
            "视频呢",
            "视频在哪",
            "视频为0",
            "video not generated",
            "why no video",
        ),
    ):
        return ControllerIntent(
            intent_type="ui_diagnostic",
            tool_name="diagnose_outputs",
            action="status_query",
            reason="用户询问视频未生成原因，应先检查成果、关键帧、视频写回和任务链路。",
        )

    if _has_any(
        text,
        (
            "什么任务",
            "哪些任务",
            "什么什么任务",
            "任务呢",
            "任务在干什么",
            "任务卡住",
            "任务失败",
            "任务队列",
            "task",
            "stuck",
            "queued",
            "running",
            "failed",
        ),
    ):
        return ControllerIntent(
            intent_type="task_diagnostic",
            tool_name="diagnose_tasks",
            action="status_query",
            reason="用户询问任务或进度，应检查活动任务、失败任务和可恢复动作。",
        )

    if _has_any(
        text,
        (
            "没显示",
            "没有显示",
            "不显示",
            "显示不了",
            "看不到",
            "没出来",
            "没有出来",
            "破图",
            "加载失败",
            "图没了",
            "图片没显示",
            "关键帧没显示",
            "not showing",
            "not visible",
            "broken image",
        ),
    ):
        return ControllerIntent(
            intent_type="ui_diagnostic",
            tool_name="diagnose_outputs",
            action="status_query",
            reason="用户报告成果显示问题，应检查 snapshot、写回字段、URL 和前端可见性。",
        )

    if _has_any(
        text,
        (
            "写回",
            "回写",
            "selected_image",
            "selected_video",
            "provider",
            "seedream",
            "seedance",
            "kling",
        ),
        ):
        return ControllerIntent(
            intent_type="provider_diagnostic",
            tool_name="diagnose_provider_writeback",
            action="status_query",
            reason="用户询问 provider 或写回链路，应检查任务结果和 shot_rows 字段。",
        )

    if _has_any(text, FINAL_EDIT_KEYWORDS):
        if _has_any(text, MISSING_OR_QUESTION_KEYWORDS) or _has_any(text, QUESTION_OR_PROGRESS_KEYWORDS):
            return ControllerIntent(
                intent_type="ui_diagnostic",
                tool_name="diagnose_outputs",
                action="status_query",
                reason="用户询问剪辑/成片为什么没有出现，应先检查视频素材、剪辑任务、最终产物和写回状态。",
            )
        return ControllerIntent(
            intent_type="production_action",
            tool_name="plan_final_edit",
            action="plan_final_edit",
            reason="用户明确要求剪辑、配音、字幕、音乐或成片导出，应使用现有剧本和视频素材进入剪辑成片。",
        )

    if _has_any(text, ("补上", "补齐", "修复缺失", "重新补", "缺的图", "缺失关键帧", "repair missing")):
        return ControllerIntent(
            intent_type="production_action",
            tool_name="diagnose_outputs",
            action="generate_keyframes",
            reason="用户要求补齐缺失视觉产物，先诊断缺失范围，再由中控派发补齐动作。",
        )

    if _has_any(text, ("剧本", "脚本", "分镜", "台词", "对白", "旁白", "卖点", "开头", "结尾", "story", "script", "storyboard")):
        return ControllerIntent(
            intent_type="script_diagnostic",
            tool_name="diagnose_script",
            action="status_query",
            reason="用户处理剧本/分镜/广告表达，应读取当前剧本与镜头证据再决定是否重写。",
        )

    if _has_any(text, ("图片池", "候选图", "多角度", "多做几张图", "批量关键帧", "keyframe pool", "keyframe batch")):
        return ControllerIntent(
            intent_type="keyframe_pool_diagnostic",
            tool_name="diagnose_keyframe_pool",
            action="status_query",
            reason="用户处理多图或图片池，应读取候选图、主图和运行中任务。",
        )

    return None


def build_intent_brief(instruction: str, *, routing: dict[str, Any] | None = None, planner: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(instruction or "").strip()
    lower = text.lower()
    category = _category(lower)
    duration = _duration_seconds(lower)
    must_keep = []
    must_avoid = []
    tone = []
    visual_language: dict[str, Any] = {}

    if "黄金" in text or "gold" in lower:
        must_keep.extend(["黄金首饰是画面主角", "金属质感、反光和细节必须清晰"])
        must_avoid.extend(["廉价电商促销风", "夸张土豪金"])
        visual_language.update({"material": "gold jewelry, polished metal, fine highlights"})
    if "广告" in text or "brand" in lower:
        must_keep.append("品牌调性优先于剧情冲突")
        must_avoid.extend(["短剧冲突", "反派、证据、争吵式剧情"])
    if _has_any(lower, ("电影", "电影级", "cinematic")):
        tone.append("电影级")
        visual_language.update({"lighting": "cinematic contrast, controlled highlights, shallow depth of field"})
    if _has_any(text, ("高级", "精致", "光影", "质感")):
        tone.extend([word for word in ("高级", "精致", "光影质感") if word in text])

    return {
        "version": "intent_brief_v1",
        "raw_instruction": text,
        "category": category,
        "duration_sec": duration,
        "tone": _dedupe(tone),
        "must_keep": _dedupe(must_keep),
        "must_avoid": _dedupe(must_avoid),
        "visual_language": visual_language,
        "planner_intent": planner or {},
        "routing_source": (routing or {}).get("routing_source") or "",
    }


def compile_semantic_plan(brief: dict[str, Any], *, routing: dict[str, Any] | None = None) -> dict[str, Any]:
    action = str((routing or {}).get("resolved_action") or "")
    duration = int(brief.get("duration_sec") or 30)
    shot_count = 6 if duration >= 25 else 4
    if action == "generate_story_plan":
        steps = ["write_script", "write_storyboard", "verify_script_shots"]
    elif action == "generate_keyframes":
        steps = ["inspect_missing_keyframes", "generate_keyframes", "verify_keyframe_writeback"]
    elif action == "generate_videos":
        steps = ["inspect_selected_keyframes", "generate_videos", "verify_video_writeback"]
    elif action == "plan_final_edit":
        steps = ["inspect_video_clips", "assemble_preview", "verify_final_output"]
    else:
        steps = ["inspect_state", "decide_next_action"]
    return {
        "version": "semantic_plan_v1",
        "target_action": action or "status_query",
        "shot_count": shot_count,
        "duration_sec": duration,
        "steps": steps,
        "dependencies": _dependencies_for_steps(steps),
    }


def build_constraint_packet(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "constraint_packet_v1",
        "must_keep": brief.get("must_keep") or [],
        "must_avoid": brief.get("must_avoid") or [],
        "tone": brief.get("tone") or [],
        "visual_language": brief.get("visual_language") or {},
        "quality_bar": [
            "结果必须符合用户原始意图",
            "生产动作不得丢失品牌、主体、风格和负面约束",
            "写回产物必须能进入 snapshot 和 SSE 可见链路",
        ],
    }


def build_verification_plan(action: str, *, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    checks = ["agent_event_written", "snapshot_refreshable", "sse_visible"]
    if action == "generate_keyframes":
        checks.extend(["image_task_dispatched", "selected_image_writeback", "outputs_images_increment"])
    elif action == "generate_videos":
        checks.extend(["video_task_dispatched", "selected_video_writeback", "outputs_videos_increment"])
    elif action == "generate_story_plan":
        checks.extend(["script_content_present", "shot_rows_present"])
    elif action == "plan_final_edit":
        checks.extend(["video_clips_present", "final_preview_or_export_present"])
    return {
        "version": "verification_plan_v1",
        "action": action or "status_query",
        "checks": checks,
        "source_diagnostics": sorted((diagnostics or {}).keys()),
    }


def attach_semantic_control(
    continue_body: dict[str, Any],
    routing: dict[str, Any],
    *,
    planner: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    instruction = str(routing.get("instruction") or continue_body.get("instruction") or "")
    brief = build_intent_brief(instruction, routing=routing, planner=planner)
    plan = compile_semantic_plan(brief, routing=routing)
    constraints = build_constraint_packet(brief)
    verification = build_verification_plan(str(routing.get("resolved_action") or ""))
    semantic = {
        "intent_brief": brief,
        "semantic_plan": plan,
        "constraint_packet": constraints,
        "verification_plan": verification,
    }
    next_routing = {**routing, "semantic": semantic}
    next_body = {
        **continue_body,
        "human_routing": next_routing,
        "intent_brief": brief,
        "semantic_plan": plan,
        "constraint_packet": constraints,
        "verification_plan": verification,
    }
    return next_body, next_routing


def actionable_followup_message(*, action: str, active_count: int) -> str:
    if active_count > 0:
        return f"诊断已经给出明确动作 {action}，当前还有任务运行，我已暂存，等活动任务结束后继续。"
    labels = {
        "generate_keyframes": "诊断已经确认缺关键帧，我已派发补齐关键帧；补齐后再进入视频生成。",
        "generate_videos": "诊断已经确认关键帧具备，我已派发视频生成，并会检查写回结果。",
        "generate_story_plan": "诊断已经确认需要重建剧本/分镜，我已派发剧本分镜处理。",
    }
    return labels.get(action, f"诊断已经给出明确动作 {action}，我已交给中控执行。")


def _category(text: str) -> str:
    if _has_any(text, ("广告", "brand", "commercial")):
        return "commercial_video"
    if _has_any(text, ("短剧", "剧情", "drama")):
        return "short_drama"
    return "video_production"


def _duration_seconds(text: str) -> int:
    for marker in ("秒", "s", "sec", "second"):
        index = text.find(marker)
        if index <= 0:
            continue
        digits = ""
        cursor = index - 1
        while cursor >= 0 and text[cursor].isdigit():
            digits = text[cursor] + digits
            cursor -= 1
        if digits:
            return max(1, min(600, int(digits)))
    return 30


def _dependencies_for_steps(steps: list[str]) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {}
    previous = ""
    for step in steps:
        deps[step] = [previous] if previous else []
        previous = step
    return deps


def _has_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in value for needle in needles)


def _is_confirmation(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    confirmation_prefixes = ("好的，", "好的,", "好，", "好,", "可以，", "可以,", "确认，", "确认,", "確認，", "確認,", "对，", "对,", "對，", "對,")
    return normalized in CONFIRM_KEYWORDS or any(normalized.startswith(item) for item in confirmation_prefixes)


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result
