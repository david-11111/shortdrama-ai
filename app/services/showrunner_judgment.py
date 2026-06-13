from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


ROOT_CAUSE_LAYERS = {
    "goal_card",
    "story",
    "shot",
    "reference",
    "prompt",
    "keyframe",
    "video",
    "edit",
    "provider",
    "technical",
    "unknown",
}

REPORT_STATUSES = {"pass", "needs_review", "regenerate", "blocked"}
DECISION_STATUSES = {"execute", "wait", "recover", "blocked", "complete"}

PROJECT_ID_RE = re.compile(
    r"\b(?:real-provider-[a-z0-9-]+|project-[a-z0-9-]+|run-[a-z0-9-]+|[0-9a-f]{8}-[0-9a-f-]{13,})\b",
    re.IGNORECASE,
)

GENERIC_PROTAGONIST_TERMS = (
    "电视剧主角",
    "短剧主角",
    "男主角",
    "女主角",
    "主角进入核心场景",
    "generic protagonist",
)

REAL_PROJECT_TERMS = (
    "工具",
    "项目",
    "立项",
    "链路",
    "测试",
    "代码",
    "文档",
    "判断",
    "AI",
    "agent",
    "Agent",
)

REAL_PROJECT_VISUAL_ANCHORS = [
    "电脑屏幕",
    "测试日志",
    "失败提示",
    "项目文档",
    "提示词草稿",
    "深夜工作场景",
    "AI生成结果",
]

PRODUCT_VISUAL_ANCHORS = [
    "古法拉丝手串",
    "竹节结构",
    "黄金质感",
    "金重9.25g",
    "实物标签",
    "手持实拍",
]

PRODUCT_DYNAMIC_VISUAL_ANCHORS = [
    "黄金项链",
    "黄金首饰",
    "黄金饰品",
    "项链",
    "首饰盒",
    "镜面台面",
    "产品微距",
    "金属高光",
    "反光细节",
    "佩戴效果",
    "佩戴首饰",
    "旋转展示",
    "展示产品细节",
    "产品质感",
    "可见效果",
]

PRODUCT_TERMS = (
    "黄金",
    "首饰",
    "饰品",
    "项链",
    "珠宝",
    "古法",
    "拉丝",
    "竹节",
    "手串",
    "金重",
    "9.25",
    "上架",
    "产品",
    "不带叶子",
)


@dataclass(frozen=True)
class ShowrunnerGoalCard:
    format: str
    source_type: str
    raw_goal: str
    core_theme: str
    main_character: str
    central_conflict: str
    emotional_arc: list[str] = field(default_factory=list)
    visual_anchors: list[str] = field(default_factory=list)
    premium_constraints: list[str] = field(default_factory=list)
    market_constraints: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    project_name: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShowrunnerJudgeReport:
    report_version: str
    stage: str
    status: str
    root_cause_layer: str
    scores: dict[str, int] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    problem_codes: list[str] = field(default_factory=list)
    suggested_action: str = "continue"
    confidence: float = 0.0
    artifact_ref: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    project_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShowrunnerDecision:
    packet_version: str
    status: str
    action: str
    reason: str
    root_cause_layer: str
    selected_lane: str
    judge_reports: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    run_id: str = ""
    stage_id: str = ""
    allowed_writes: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    failure_policy: dict[str, Any] = field(default_factory=dict)
    quality_bar: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_goal_card(
    goal: str,
    *,
    project_name: str = "",
    context: dict[str, Any] | None = None,
) -> ShowrunnerGoalCard:
    text = _join_text(goal, project_name, *(str(v) for v in (context or {}).values() if isinstance(v, str)))
    if _looks_like_product_listing_video(text):
        source_type = "product_listing_video"
    elif _looks_like_real_project_process(text):
        source_type = "real_project_process"
    else:
        source_type = "fiction_short_drama"

    if source_type == "product_listing_video":
        visual_anchors = _product_visual_anchors_for_text(text)
        main_product = visual_anchors[0] if visual_anchors else "黄金饰品"
        duration_constraint, duration_must_not = _product_duration_constraints(text)
        return ShowrunnerGoalCard(
            format="product_listing_video",
            source_type=source_type,
            raw_goal=str(goal or ""),
            core_theme="黄金饰品商业短视频",
            main_character=main_product,
            central_conflict="在指定时长内同时传达产品质感、实物可信度和购买冲动",
            emotional_arc=["看见金色质感", "识别产品细节", "确认真实佩戴或展示效果", "形成购买理由"],
            visual_anchors=visual_anchors,
            premium_constraints=["真实手持", "微距质感", "不过度失真", "干净背景", "高级但可信"],
            market_constraints=[
                f"前三秒展示{main_product}和核心质感",
                "中段给出工艺、佩戴或细节信任信息",
                "结尾形成购买记忆点",
                duration_constraint,
            ],
            must_not=[
                f"生成与{main_product}无关的普通金饰",
                "丢掉用户指定的商品形态和关键细节",
                "把标签文字乱写",
                "过度奢华导致不像实物",
                duration_must_not,
            ],
            project_name=str(project_name or ""),
        )

    if source_type == "real_project_process":
        return ShowrunnerGoalCard(
            format="premium_short_drama",
            source_type=source_type,
            raw_goal=str(goal or ""),
            core_theme="AI工具创业/开发过程中的困惑、坚持和突破",
            main_character="想做出精品爆款短剧 Agent 的工具开发者",
            central_conflict="链路能跑，但系统不会判断剧本、参考图、视频和成片质量",
            emotional_arc=["期待", "焦虑", "怀疑", "反复测试", "发现核心问题", "重建判断引擎"],
            visual_anchors=list(REAL_PROJECT_VISUAL_ANCHORS),
            premium_constraints=["真实", "克制", "高级感", "统一视觉风格", "避免廉价爽文模板"],
            market_constraints=["前三秒有问题钩子", "中段有冲突升级", "结尾有下一步悬念"],
            must_not=[
                "泛化成电视剧主角",
                "把项目ID写进创作prompt",
                "无目标空镜",
                "无剧情职责的模板分镜",
            ],
            project_name=str(project_name or ""),
        )

    return ShowrunnerGoalCard(
        format="premium_short_drama",
        source_type=source_type,
        raw_goal=str(goal or ""),
        core_theme=_compact_excerpt(goal, 80) or "精品短剧",
        main_character="围绕用户目标建立的核心人物",
        central_conflict="主角目标与阻碍之间的冲突",
        emotional_arc=["建立目标", "遭遇阻碍", "冲突升级", "留下悬念"],
        visual_anchors=[],
        premium_constraints=["真实", "克制", "视觉统一", "非模板化"],
        market_constraints=["前三秒钩子", "明确冲突", "结尾悬念"],
        must_not=["无剧情职责的模板分镜", "把项目ID写进创作prompt"],
        project_name=str(project_name or ""),
    )


def judge_story_alignment(goal_card: ShowrunnerGoalCard, story_text: str) -> ShowrunnerJudgeReport:
    text = str(story_text or "")
    problems: list[str] = []
    codes: list[str] = []
    score = 86

    if not _has_any(text, ("前三秒", "钩子", "开场", "问题", "悬念", "失败", "冲突")):
        _add_problem(problems, codes, "weak_commercial_hook", "故事没有明确前三秒钩子或可感知问题。")
        score -= 25
    if goal_card.source_type == "real_project_process" and not _has_any(text, ("链路", "判断", "测试", "文档", "项目", "工具")):
        _add_problem(problems, codes, "missing_central_conflict", "故事没有承接 Goal Card 的真实项目困境。")
        score -= 30
    if _has_any(text, GENERIC_PROTAGONIST_TERMS) and goal_card.source_type == "real_project_process":
        _add_problem(problems, codes, "generic_protagonist", "真实项目故事被泛化成普通电视剧主角。")
        score -= 25
    if len(text.strip()) < 40:
        _add_problem(problems, codes, "story_too_thin", "故事信息量不足，无法支撑短剧生产。")
        score -= 18

    status = _status_from_score(score, blocked=1, regenerate=68, review=76)
    return _report(
        stage="story",
        status=status,
        root_cause_layer="story" if problems else "unknown",
        score=score,
        problems=problems,
        codes=codes,
        suggested_action="rewrite_story" if problems else "continue",
        confidence=0.82,
        evidence=[{"kind": "text", "ref": "story_text", "summary": _compact_excerpt(text, 160)}],
    )


def judge_shot_responsibility(goal_card: ShowrunnerGoalCard, shot: dict[str, Any]) -> ShowrunnerJudgeReport:
    prompt = str((shot or {}).get("prompt") or (shot or {}).get("text") or "")
    problems, codes, score = _common_creative_text_problems(goal_card, prompt)

    if goal_card.source_type == "real_project_process" and not _has_any(prompt, ("职责", "建立", "推进", "钩子", "冲突", "情绪", "转折", "悬念")):
        _add_problem(problems, codes, "missing_dramatic_job", "分镜没有声明清楚它承担的剧情职责。")
        score -= 18
    if goal_card.source_type == "real_project_process" and not _has_any(prompt, ("开发者", "测试", "日志", "屏幕", "文档", "提示词", "失败", "链路", "判断")):
        _add_problem(problems, codes, "missing_goal_anchors", "分镜缺少真实项目过程的视觉/剧情锚点。")
        score -= 22
    if goal_card.source_type == "product_listing_video":
        if not _has_any(prompt, PRODUCT_TERMS):
            _add_problem(problems, codes, "missing_product_identity", "产品镜头没有锁定黄金手串、竹节、拉丝或克重等核心卖点。")
            score -= 35
        if not _has_any(prompt, ("特写", "微距", "旋转", "佩戴", "手持", "标签", "克重", "质感", "10秒", "镜头")):
            _add_problem(problems, codes, "missing_product_shot_job", "产品镜头没有明确展示职责。")
            score -= 15

    status = "blocked" if _has_blocking_code(codes) else _status_from_score(score, blocked=42, regenerate=68, review=76)
    return _report(
        stage="shot",
        status=status,
        root_cause_layer="shot" if problems else "unknown",
        score=score,
        problems=problems,
        codes=codes,
        suggested_action="rewrite_shots_and_prompts" if problems else "continue",
        confidence=0.86,
        artifact_ref={"type": "shot", "shot_index": (shot or {}).get("shot_index")},
        evidence=[{"kind": "text", "ref": "shot.prompt", "summary": _compact_excerpt(prompt, 180)}],
    )


def judge_prompt_fidelity(
    goal_card: ShowrunnerGoalCard,
    prompt: str,
    *,
    shot: dict[str, Any] | None = None,
) -> ShowrunnerJudgeReport:
    text = str(prompt or "")
    problems, codes, score = _common_creative_text_problems(goal_card, text)

    if goal_card.source_type in {"real_project_process", "product_listing_video"} and goal_card.visual_anchors:
        anchor_hits = sum(1 for item in goal_card.visual_anchors if item in text)
        if anchor_hits == 0:
            _add_problem(problems, codes, "missing_visual_anchors", "提示词没有带入 Goal Card 的关键视觉锚点。")
            score -= 24
    style_required = goal_card.source_type in {"real_project_process", "product_listing_video"}
    if style_required and not _has_any(text, ("真实", "克制", "高级感", "cinematic", "电影感", "统一", "冷光", "屏幕", "近景", "质感", "微距", "高级", "干净")):
        _add_problem(problems, codes, "missing_style_constraints", "提示词缺少质感和风格约束。")
        score -= 10
    if goal_card.source_type == "product_listing_video" and not _has_any(text, PRODUCT_TERMS):
        _add_problem(problems, codes, "missing_product_identity", "产品提示词没有锁定黄金手串、竹节、拉丝或克重等核心卖点。")
        score -= 30

    status = "blocked" if _has_blocking_code(codes) else _status_from_score(score, blocked=42, regenerate=70, review=78)
    return _report(
        stage="prompt",
        status=status,
        root_cause_layer="prompt" if problems else "unknown",
        score=score,
        problems=problems,
        codes=codes,
        suggested_action="rewrite_prompt" if problems else "continue",
        confidence=0.88,
        artifact_ref={"type": "prompt", "shot_index": (shot or {}).get("shot_index") if isinstance(shot, dict) else None},
        evidence=[{"kind": "text", "ref": "provider_prompt", "summary": _compact_excerpt(text, 180)}],
    )


def judge_existing_media_review(
    goal_card: ShowrunnerGoalCard,
    *,
    media_type: str,
    artifact_ref: dict[str, Any] | None,
    review: dict[str, Any] | None,
) -> ShowrunnerJudgeReport:
    review = review or {}
    media = str(media_type or "image").strip().lower()
    raw_status = str(review.get("status") or "").strip().lower()
    score = _safe_int(review.get("score"), default=0 if raw_status in {"failed", "regenerate"} else 70)
    notes = [str(item) for item in (review.get("notes") or review.get("actions") or []) if item]
    status = _normalize_review_status(raw_status, score)
    layer = "video" if media == "video" else "keyframe" if media in {"image", "keyframe"} else "unknown"

    problems: list[str] = []
    codes: list[str] = []
    if status != "pass":
        _add_problem(
            problems,
            codes,
            "existing_review_failed",
            f"现有{media}审片未通过：{'; '.join(notes) if notes else raw_status or score}",
        )
    if goal_card.source_type == "real_project_process" and notes and not _has_any(" ".join(notes), ("开发者", "测试", "日志", "屏幕", "文档", "项目")):
        _add_problem(problems, codes, "media_missing_goal_anchors", "审片证据显示画面没有服务真实项目过程。")

    suggested_action = "regenerate_video" if layer == "video" else "regenerate_keyframe" if layer == "keyframe" else "ask_showrunner"
    return _report(
        stage="video" if layer == "video" else "keyframe",
        status=status,
        root_cause_layer=layer if problems else "unknown",
        score=score,
        problems=problems,
        codes=codes,
        suggested_action=suggested_action if problems else "continue",
        confidence=0.72,
        artifact_ref=dict(artifact_ref or {}),
        evidence=[{"kind": "existing_review", "ref": media, "summary": _compact_excerpt(" ".join(notes), 180)}],
    )


def make_showrunner_decision(
    reports: list[ShowrunnerJudgeReport],
    *,
    run_id: str = "",
    stage_id: str = "",
) -> ShowrunnerDecision:
    normalized = [item for item in reports if isinstance(item, ShowrunnerJudgeReport)]
    failing = [item for item in normalized if item.status != "pass"]
    if not failing:
        return ShowrunnerDecision(
            packet_version="showrunner_decision_v1",
            run_id=run_id,
            stage_id=stage_id,
            status="execute",
            action="continue",
            reason="All Showrunner judge reports passed.",
            root_cause_layer="unknown",
            selected_lane="c_lane_production",
            judge_reports=[item.as_dict() for item in normalized],
            evidence_refs=_collect_evidence(normalized),
            allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
            success_criteria=["Continue only while artifacts remain aligned with the Production Goal Card."],
            failure_policy={"retryable": True, "fallback_action": "showrunner_review", "require_human_confirmation": False},
            quality_bar=_default_quality_bar(),
        )

    primary = sorted(failing, key=_report_priority, reverse=True)[0]
    action = _repair_action_for_reports(failing)
    return ShowrunnerDecision(
        packet_version="showrunner_decision_v1",
        run_id=run_id,
        stage_id=stage_id,
        status="blocked" if primary.status == "blocked" else "recover",
        action=action,
        reason="; ".join(_unique(problem for item in failing for problem in item.problems)) or primary.suggested_action,
        root_cause_layer=primary.root_cause_layer if primary.root_cause_layer in ROOT_CAUSE_LAYERS else "unknown",
        selected_lane="b_lane_agent_runs" if action in {"rewrite_story", "rewrite_prompt", "rewrite_shots_and_prompts"} else "c_lane_production",
        judge_reports=[item.as_dict() for item in normalized],
        evidence_refs=_collect_evidence(failing),
        allowed_writes=["agent_events", "agent_runs", "shot_rows"],
        success_criteria=[
            "Rewrite the failed layer before spending provider credits again.",
            "Re-run Showrunner gates against the same Production Goal Card.",
        ],
        failure_policy={"retryable": False, "fallback_action": action, "require_human_confirmation": False},
        quality_bar=_default_quality_bar(),
    )


def judge_generation_preflight(
    goal_card: ShowrunnerGoalCard,
    shots: list[dict[str, Any]],
    *,
    run_id: str = "",
    stage_id: str = "generate_keyframes",
) -> tuple[list[ShowrunnerJudgeReport], ShowrunnerDecision]:
    reports: list[ShowrunnerJudgeReport] = []
    for shot in shots:
        reports.append(judge_shot_responsibility(goal_card, shot))
        reports.append(judge_prompt_fidelity(goal_card, str(shot.get("prompt") or ""), shot=shot))
    return reports, make_showrunner_decision(reports, run_id=run_id, stage_id=stage_id)


def _common_creative_text_problems(goal_card: ShowrunnerGoalCard, text: str) -> tuple[list[str], list[str], int]:
    problems: list[str] = []
    codes: list[str] = []
    score = 88

    if PROJECT_ID_RE.search(text):
        _add_problem(problems, codes, "project_id_leakage", "项目 ID 或系统标识进入了创作文本。")
        score -= 45
    if goal_card.project_name and goal_card.project_name in text and PROJECT_ID_RE.search(goal_card.project_name):
        _add_problem(problems, codes, "project_id_leakage", "项目名是系统 ID，不能作为剧情内容。")
        score -= 20
    if goal_card.source_type == "real_project_process" and _has_any(text, GENERIC_PROTAGONIST_TERMS):
        _add_problem(problems, codes, "generic_protagonist", "真实项目过程被泛化成电视剧主角。")
        score -= 35

    return problems, _unique(codes), max(0, score)


def _report(
    *,
    stage: str,
    status: str,
    root_cause_layer: str,
    score: int,
    problems: list[str],
    codes: list[str],
    suggested_action: str,
    confidence: float,
    artifact_ref: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> ShowrunnerJudgeReport:
    normalized_status = status if status in REPORT_STATUSES else "needs_review"
    normalized_layer = root_cause_layer if root_cause_layer in ROOT_CAUSE_LAYERS else "unknown"
    bounded_score = max(0, min(100, int(score)))
    return ShowrunnerJudgeReport(
        report_version="showrunner_judge_v1",
        stage=stage,
        status=normalized_status,
        root_cause_layer=normalized_layer,
        scores={
            "goal_alignment": bounded_score,
            "commercial_hook": bounded_score if stage in {"story", "shot"} else 70,
            "premium_texture": bounded_score if stage in {"prompt", "keyframe", "video"} else 72,
            "continuity": bounded_score if stage in {"shot", "video", "edit"} else 70,
            "technical_validity": 80,
            "cuttability": bounded_score if stage in {"video", "edit"} else 70,
        },
        evidence=evidence or [],
        problems=_unique(problems),
        problem_codes=_unique(codes),
        suggested_action=suggested_action,
        confidence=max(0.0, min(1.0, float(confidence))),
        artifact_ref=artifact_ref or {},
    )


def _looks_like_real_project_process(text: str) -> bool:
    compact = str(text or "")
    if "我做这个工具" in compact:
        return True
    first_person_process = _has_any(compact, ("我做", "我从", "我希望", "我准备", "我想"))
    development_hits = sum(1 for item in ("工具", "开发", "代码", "文档", "测试", "链路", "判断", "立项") if item in compact)
    narrative_hits = sum(1 for item in ("过程", "一个月", "经历", "从开始", "到现在") if item in compact)
    return first_person_process and development_hits >= 2 and narrative_hits >= 2


def _looks_like_product_listing_video(text: str) -> bool:
    compact = str(text or "")
    product_hits = sum(1 for item in PRODUCT_TERMS if item in compact)
    video_intent = _has_any(compact, ("视频", "上架", "带货", "商品", "产品", "不超10秒", "10秒"))
    return product_hits >= 2 and video_intent


def _product_visual_anchors_for_text(text: str) -> list[str]:
    compact = str(text or "")
    anchors = [item for item in PRODUCT_DYNAMIC_VISUAL_ANCHORS if item in compact]
    return _unique(anchors + list(PRODUCT_VISUAL_ANCHORS))


def _product_duration_constraints(text: str) -> tuple[str, str]:
    compact = str(text or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*秒", compact)
    if not match:
        return "总时长不超过10秒", "视频超过10秒"

    seconds = _format_seconds(match.group(1))
    prefix = compact[max(0, match.start() - 6) : match.start()]
    is_upper_bound = _has_any(prefix, ("不超过", "不超", "最多", "最长", "以内"))
    if is_upper_bound:
        return f"总时长不超过{seconds}秒", f"视频超过{seconds}秒"
    return f"总时长约{seconds}秒", f"视频明显偏离{seconds}秒"


def _format_seconds(raw: str) -> str:
    try:
        value = float(raw)
    except ValueError:
        return raw
    if value.is_integer():
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")


def _has_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(item and item in text for item in terms)


def _add_problem(problems: list[str], codes: list[str], code: str, message: str) -> None:
    if code not in codes:
        codes.append(code)
    if message not in problems:
        problems.append(message)


def _has_blocking_code(codes: list[str]) -> bool:
    return bool({"project_id_leakage", "generic_protagonist"}.intersection(codes))


def _status_from_score(score: int, *, blocked: int, regenerate: int, review: int) -> str:
    if score < blocked:
        return "blocked"
    if score < regenerate:
        return "regenerate"
    if score < review:
        return "needs_review"
    return "pass"


def _normalize_review_status(status: str, score: int) -> str:
    if status in {"usable", "cuttable", "passed", "approved", "pass"} and score >= 65:
        return "pass"
    if status in {"blocked", "rejected"}:
        return "blocked"
    if status in {"regenerate", "failed", "fail"} or score < 50:
        return "regenerate"
    if status in {"needs_review", "warning"} or score < 72:
        return "needs_review"
    return "pass"


def _report_priority(report: ShowrunnerJudgeReport) -> tuple[int, int, int]:
    status_weight = {"blocked": 4, "regenerate": 3, "needs_review": 2, "pass": 1}.get(report.status, 0)
    layer_weight = {
        "goal_card": 10,
        "story": 9,
        "shot": 8,
        "prompt": 7,
        "reference": 6,
        "keyframe": 5,
        "video": 4,
        "edit": 3,
        "provider": 2,
        "technical": 1,
    }.get(report.root_cause_layer, 0)
    return status_weight, layer_weight, len(report.problem_codes)


def _repair_action_for_reports(reports: list[ShowrunnerJudgeReport]) -> str:
    layers = {item.root_cause_layer for item in reports}
    if layers.intersection({"goal_card"}):
        return "rewrite_goal_card"
    if layers.intersection({"story"}):
        return "rewrite_story"
    if layers.intersection({"shot", "prompt"}):
        return "rewrite_shots_and_prompts"
    if layers.intersection({"reference"}):
        return "lock_references"
    if layers.intersection({"keyframe"}):
        return "regenerate_keyframe"
    if layers.intersection({"video", "provider"}):
        return "regenerate_video"
    if layers.intersection({"edit"}):
        return "revise_edit"
    return "ask_showrunner"


def _collect_evidence(reports: list[ShowrunnerJudgeReport]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for report in reports:
        for item in report.evidence:
            refs.append({"stage": report.stage, **item})
    return refs


def _default_quality_bar() -> dict[str, int]:
    return {
        "minimum_goal_alignment": 75,
        "minimum_commercial_hook": 70,
        "minimum_premium_texture": 72,
        "minimum_continuity": 70,
    }


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _join_text(*items: str) -> str:
    return "\n".join(str(item or "") for item in items if str(item or "").strip())


def _compact_excerpt(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[: max(0, int(limit))]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
