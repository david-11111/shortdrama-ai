import json
import asyncio
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.middleware.rate_limit import check_concurrent_limit, check_rate_limit
from app.services import director as director_svc
from app.services.cost_guard import assert_cost_guard
from app.services.context_budget import ContextBudget, trim_messages
from app.services.credits import credit_service
from app.services.director_preflight import analyze_shot_risk
from app.services.final_video_storage import final_video_response
from app.services.media_proxy import proxy_remote_media_response
from app.services.production_entrypoint import direct_generation_block_detail
from app.services.production_text_quality import analyze_production_text_effectiveness
from app.services.task_dispatcher import TaskSpec, dispatch_task

router = APIRouter(prefix="/director", tags=["director"])

DIRECTOR_CHAT_BUDGET = ContextBudget(max_messages=12, max_message_chars=2000, max_total_chars=12000)
DIRECTOR_TASK_SPECS = {
    "director_chat": TaskSpec("director_chat", "app.tasks.director_tasks.director_chat_task", "text", "llm_director_chat", "llm_chat"),
    "director_script": TaskSpec("director_script", "app.tasks.director_tasks.director_script_task", "text", "llm_director_chat", "director_script"),
    "director_prepare": TaskSpec("director_prepare", "app.tasks.director_tasks.director_prepare_task", "default", "pipeline_analysis", None),
    "director_produce": TaskSpec("director_produce", "app.tasks.director_tasks.director_produce_task", "default", "video_gen_5s", "director_produce"),
    "director_ref_images": TaskSpec("director_ref_images", "app.tasks.director_tasks.director_reference_images_task", "image", "image_gen", "director_ref_images"),
    "director_final_cut_ai": TaskSpec("director_final_cut_ai", "app.tasks.director_tasks.director_final_cut_ai_task", "text", "final_cut_ai_plan", "llm_chat"),
}


def _block_direct_production_entrypoint(task_type: str) -> None:
    raise HTTPException(status_code=403, detail=direct_generation_block_detail(task_type))


async def _guard_director_produce_preflight(
    db: AsyncSession,
    project_id: str,
    user_id: int,
    shot_indices: list[int] | None,
) -> None:
    params: dict[str, Any] = {"project_id": project_id, "user_id": user_id}
    where = "project_id = :project_id AND user_id = :user_id"
    if shot_indices:
        where += " AND shot_index IN :shot_indices"
        params["shot_indices"] = tuple(shot_indices)
        stmt = text(
            f"""
            SELECT shot_index, prompt, duration, selected_image,
                   character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json
            FROM shot_rows
            WHERE {where}
            ORDER BY shot_index ASC
            """
        ).bindparams(bindparam("shot_indices", expanding=True))
    else:
        stmt = text(
            f"""
            SELECT shot_index, prompt, duration, selected_image,
                   character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json
            FROM shot_rows
            WHERE {where}
            ORDER BY shot_index ASC
            """
        )
    result = await db.execute(stmt, params)
    blocked = []
    for row in result.fetchall():
        shot = {
            "shot_index": row.shot_index,
            "prompt": row.prompt,
            "duration": row.duration,
            "selected_image": row.selected_image,
            "character_refs": row.character_refs_json or [],
            "scene_refs": row.scene_refs_json or [],
            "prop_refs": row.prop_refs_json or [],
            "costume_refs": row.costume_refs_json or [],
            "style_refs": row.style_refs_json or [],
        }
        report = analyze_shot_risk(shot)
        if report.get("risk_level") != "blocked":
            continue
        blocked.append({
            "shot_index": row.shot_index,
            "risks": report.get("risks", []),
            "suggestions": report.get("suggestions", []),
            "safe_prompt": report.get("safe_prompt", ""),
        })
    if blocked:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "director_preflight_blocked",
                "message": "生成前审查未通过，请先修正高风险分镜。",
                "blocked_shots": blocked,
            },
        )


@router.get("/media/{task_id}")
async def get_task_media(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text(
            """
            SELECT result
            FROM tasks
            WHERE user_id = :uid
              AND status = 'done'
              AND (task_id = :task_id OR (:numeric_id IS NOT NULL AND id = :numeric_id))
            LIMIT 1
            """
        ),
        {
            "task_id": task_id,
            "numeric_id": int(task_id) if str(task_id).isdigit() else None,
            "uid": current_user["id"],
        },
    )
    row = result.fetchone()
    if not row or not row.result:
        raise HTTPException(status_code=404, detail="Task media not found")

    task_result = row.result if isinstance(row.result, dict) else json.loads(row.result)
    return await proxy_remote_media_response(task_id, task_result)


@router.get("/final-video/{task_id}")
async def get_final_video_blob(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await final_video_response(db, task_id=task_id, user_id=current_user["id"])


# ─── 同步查询端点 ────────────────────────────────────────────────────────────────


@router.get("/presets")
async def get_presets(current_user: dict = Depends(get_current_user)):
    return director_svc.get_director_presets()


@router.get("/evaluation-standard")
async def get_evaluation_standard(current_user: dict = Depends(get_current_user)):
    return director_svc.get_director_evaluation_rubric()


@router.get("/final-cut-recipes")
async def get_final_cut_recipes(current_user: dict = Depends(get_current_user)):
    from app.services.final_cut_recipes import load_final_cut_recipes

    return load_final_cut_recipes()


@router.get("/final-cut-recipes/{recipe_id}")
async def get_final_cut_recipe(recipe_id: str, current_user: dict = Depends(get_current_user)):
    from app.services.final_cut_recipes import get_final_cut_recipe

    recipe = get_final_cut_recipe(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Final cut recipe not found")
    return recipe


@router.post("/final-cut-plan/ai")
async def generate_final_cut_plan_with_ai(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project_id = str((body or {}).get("project_id") or "").strip()
    recipe_id = str((body or {}).get("recipe_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")
    if not recipe_id:
        raise HTTPException(status_code=422, detail="recipe_id is required")

    from app.services.final_cut_recipes import get_final_cut_recipe

    recipe = get_final_cut_recipe(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Final cut recipe not found")

    current_plan = await _load_current_final_edit_plan(db, project_id, current_user["id"])
    if not current_plan.get("clips"):
        raise HTTPException(status_code=400, detail="No produced clips found for final cut planning")

    return await _dispatch_director_task(
        "director_final_cut_ai",
        body,
        current_user["id"],
        current_user["tier"],
        db,
    )


@router.post("/final-cut-plan/apply-rule")
async def apply_final_cut_rule_to_plan(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project_id = str((body or {}).get("project_id") or "").strip()
    recipe_id = str((body or {}).get("recipe_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")
    if not recipe_id:
        raise HTTPException(status_code=422, detail="recipe_id is required")

    from app.services.final_cut_recipes import get_final_cut_recipe
    from app.services.final_cut_rule_apply import apply_final_cut_rule

    recipe = get_final_cut_recipe(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Final cut recipe not found")

    plan = await _load_current_final_edit_plan(db, project_id, current_user["id"])
    result = apply_final_cut_rule(plan, recipe_id)
    await _save_final_edit_plan_json(db, project_id, current_user["id"], result["plan"])
    return {
        "ok": True,
        "project_id": project_id,
        "recipe_id": recipe_id,
        "recipe_name": recipe.get("name"),
        **result,
    }


@router.post("/diagnose-task")
async def diagnose_task(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    query = body.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    return director_svc.diagnose_task(
        query,
        style_hint=body.get("style_hint", ""),
        context_hint=body.get("context_hint", ""),
        manual_task_type=body.get("manual_task_type", ""),
    )


@router.post("/recommend-mode")
async def recommend_mode(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    task_type = body.get("task_type", "")
    if not task_type:
        raise HTTPException(status_code=400, detail="task_type is required")
    return director_svc.recommend_mode(
        task_type=task_type,
        project_id=body.get("project_id", ""),
        query=body.get("query", ""),
        style_hint=body.get("style_hint", ""),
        context_hint=body.get("context_hint", ""),
        diagnosis=body.get("diagnosis"),
        manual_preset_key=body.get("manual_preset_key", ""),
        manual_filter_mode=body.get("manual_filter_mode", ""),
        manual_filter_value=body.get("manual_filter_value", ""),
    )


@router.post("/explain-decision")
async def explain_decision(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    query = body.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    return director_svc.explain_decision(
        query,
        project_id=body.get("project_id", ""),
        style_hint=body.get("style_hint", ""),
        context_hint=body.get("context_hint", ""),
        task_type=body.get("task_type", ""),
        manual_task_type=body.get("manual_task_type", ""),
        preset_key=body.get("preset_key", ""),
        filter_mode=body.get("filter_mode", ""),
        filter_value=body.get("filter_value", ""),
    )


@router.post("/evaluate-run")
async def evaluate_run(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    project_id = body.get("project_id", "")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    return director_svc.evaluate_run(
        project_id=project_id,
        script=body.get("script"),
        output_name=body.get("output_name", ""),
        style_hint=body.get("style_hint", ""),
        context_hint=body.get("context_hint", ""),
        manual_feedback=body.get("manual_feedback", ""),
        preset_key=body.get("preset_key", ""),
    )


@router.post("/rework-suggest")
async def rework_suggest(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    return director_svc.suggest_rework(
        evaluation_result=body.get("evaluation_result"),
        project_id=body.get("project_id", ""),
        output_name=body.get("output_name", ""),
        manual_feedback=body.get("manual_feedback", ""),
    )


@router.post("/evolution/record")
async def evolution_record(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    return director_svc.record_case(
        project_id=body.get("project_id", ""),
        output_name=body.get("output_name", ""),
        run_log=body.get("run_log"),
        evaluation_result=body.get("evaluation_result"),
        manual_verdict=body.get("manual_verdict", ""),
        manual_notes=body.get("manual_notes", ""),
        case_tags=body.get("case_tags"),
    )


@router.get("/evolution/patterns")
async def evolution_patterns(
    project_id: str = "",
    problem_type: str = "",
    verdict_type: str = "",
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    return director_svc.list_patterns(
        project_id=project_id,
        problem_type=problem_type,
        verdict_type=verdict_type,
        limit=limit,
    )


# ─── 项目记忆 ────────────────────────────────────────────────────────────────────


@router.get("/{project_id}/project-memory")
async def get_project_memory(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    return director_svc.get_project_memory(project_id)


@router.post("/{project_id}/project-memory")
async def update_project_memory(
    project_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    profile = body.get("profile", body)
    force = body.get("force", False)
    return director_svc.update_project_profile(project_id, profile, force=force)


# ─── 异步操作端点（Celery 派发） ─────────────────────────────────────────────────


async def _dispatch_director_task(
    task_type: str,
    body: dict,
    user_id: int,
    user_tier: str,
    db: AsyncSession,
) -> dict:
    spec = DIRECTOR_TASK_SPECS.get(task_type)
    if spec is None:
        raise HTTPException(400, f"Unknown director task type: {task_type}")
    body = _sanitize_director_payload(task_type, body)
    result = await dispatch_task(db, spec=spec, payload=body, user_id=user_id, user_tier=user_tier)
    return {"task_id": result["task_id"], "status": result["status"]}


    # 路由表：task_type → (celery_task_name, queue, rate_resource, credit_operation)


def _sanitize_director_payload(task_type: str, body: dict) -> dict:
    payload = dict(body or {})
    if task_type == "director_ref_images":
        description = str(payload.get("character_description") or payload.get("prompt") or "").strip()
        quality = analyze_production_text_effectiveness(description, domain="reference_image")
        if not quality["ok"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "参考图描述没有可执行锚点，不能只写电影感、高级、氛围、质感这类空词。",
                    "reasons": quality["reasons"],
                    "quality": quality,
                },
            )
        payload["text_quality"] = quality
        return payload
    if task_type != "director_chat":
        return payload
    messages, report = trim_messages(payload.get("messages", []), DIRECTOR_CHAT_BUDGET)
    payload["messages"] = messages
    payload["_context_budget"] = report.as_dict()
    return payload


def _trim_chat_messages(raw_messages: Any) -> list[dict[str, str]]:
    return trim_messages(raw_messages, DIRECTOR_CHAT_BUDGET)[0]


@router.post("/script")
async def generate_script(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _block_direct_production_entrypoint("director_script")
    return await _dispatch_director_task("director_script", body, current_user["id"], current_user["tier"], db)


@router.post("/chat")
async def director_chat(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _dispatch_director_task("director_chat", body, current_user["id"], current_user["tier"], db)


@router.post("/prepare")
async def director_prepare(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _block_direct_production_entrypoint("director_prepare")
    return await _dispatch_director_task("director_prepare", body, current_user["id"], current_user["tier"], db)


@router.post("/produce")
async def director_produce(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _block_direct_production_entrypoint("director_produce")
    project_id = str(body.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    shot_indices = _normalize_shot_indices(body.get("shot_indices"))
    count = await _count_shot_rows(db, project_id, current_user["id"], shot_indices)
    if count == 0:
        raise HTTPException(status_code=400, detail="No shot rows to produce")
    if shot_indices and count != len(shot_indices):
        raise HTTPException(status_code=400, detail="Some requested shot rows do not exist")

    await _guard_director_produce_preflight(db, project_id, current_user["id"], shot_indices)

    if shot_indices:
        body["shot_indices"] = shot_indices
    return await _dispatch_director_task("director_produce", body, current_user["id"], current_user["tier"], db)


@router.post("/export-final")
async def director_export_final(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _block_direct_production_entrypoint("director_export_final")
    project_id = str((body or {}).get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")

    shot_indices = _normalize_shot_indices((body or {}).get("shot_indices"))
    edit_plan = (body or {}).get("edit_plan")
    if not edit_plan and not (body or {}).get("ignore_saved_plan"):
        edit_plan = await _load_current_final_edit_plan(db, project_id, current_user["id"])
    if edit_plan:
        from app.services.final_edit import export_payload_from_plan, validate_delivery_plan

        try:
            validation = validate_delivery_plan(edit_plan)
            if not validation["passed"]:
                raise ValueError(json.dumps({"error": "final_delivery_blocked", "items": validation["errors"]}, ensure_ascii=False))
            edit_payload = export_payload_from_plan(edit_plan)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        clip_count = len(edit_payload["clips"])
    else:
        edit_payload = None
        clip_count = await _count_exportable_videos(db, project_id, current_user["id"], shot_indices)
    if clip_count <= 0:
        raise HTTPException(status_code=400, detail="No produced videos found for export")

    user_id = current_user["id"]
    user_tier = current_user["tier"]
    await check_concurrent_limit(user_id, user_tier, db)
    await check_rate_limit(user_id, user_tier, "director_produce", db)

    credit_op = "pipeline_analysis"
    credits_reserved = await credit_service.get_price(credit_op)
    await assert_cost_guard(db, user_id=user_id, credits_to_reserve=credits_reserved)
    transaction_id = await reserve_credits(user_id, credit_op, 1)

    from app.celery_app import celery_app

    task_id = uuid.uuid4().hex
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)
    run_id = str((body or {}).get("run_id") or (body or {}).get("_chain_run_id") or "").strip() or None
    payload = {
        **(body or {}),
        "project_id": project_id,
        "shot_indices": shot_indices,
        "clip_count": clip_count,
    }
    if edit_payload:
        payload["edit_plan_export"] = edit_payload
    db_payload = {**payload, "_credit_transaction_id": transaction_id}
    await db.execute(
        text(
            """
            INSERT INTO tasks (
                task_id, user_id, project_id, run_id, task_type, status, priority,
                payload, credits_reserved, credit_transaction_id
            )
            VALUES (
                :tid, :uid, :project_id, CAST(:run_id AS UUID), 'director_export_final', 'queued', :priority,
                :payload, :credits, :credit_transaction_id
            )
            """
        ),
        {
            "tid": task_id,
            "uid": user_id,
            "project_id": project_id,
            "run_id": run_id,
            "priority": priority,
            "payload": json.dumps(db_payload, ensure_ascii=False),
            "credits": credits_reserved,
            "credit_transaction_id": transaction_id,
        },
    )
    await db.commit()

    celery_app.send_task(
        "app.tasks.director_tasks.director_export_final_task",
        args=[task_id, str(user_id), payload],
        kwargs={"transaction_id": transaction_id},
        queue="default",
        priority=priority,
    )
    return {"task_id": task_id, "status": "queued", "clip_count": clip_count}


@router.post("/export-preview")
async def director_export_preview(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _block_direct_production_entrypoint("director_export_preview")
    project_id = str((body or {}).get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")

    shot_indices = _normalize_shot_indices((body or {}).get("shot_indices"))
    edit_plan = (body or {}).get("edit_plan")
    if not edit_plan and not (body or {}).get("ignore_saved_plan"):
        edit_plan = await _load_current_final_edit_plan(db, project_id, current_user["id"])
    if edit_plan:
        from app.services.final_edit import export_payload_from_plan, validate_delivery_plan

        try:
            validation = validate_delivery_plan(edit_plan)
            if not validation["passed"]:
                raise ValueError(json.dumps({"error": "final_delivery_blocked", "items": validation["errors"]}, ensure_ascii=False))
            edit_payload = export_payload_from_plan(edit_plan)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        clip_count = len(edit_payload["clips"])
    else:
        edit_payload = None
        clip_count = await _count_exportable_videos(db, project_id, current_user["id"], shot_indices)
    if clip_count <= 0:
        raise HTTPException(status_code=400, detail="No produced videos found for preview")

    user_id = current_user["id"]
    user_tier = current_user["tier"]
    await check_concurrent_limit(user_id, user_tier, db)
    await check_rate_limit(user_id, user_tier, "director_produce", db)

    from app.celery_app import celery_app

    task_id = uuid.uuid4().hex
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)
    run_id = str((body or {}).get("run_id") or (body or {}).get("_chain_run_id") or "").strip() or None
    payload = {
        **(body or {}),
        "project_id": project_id,
        "shot_indices": shot_indices,
        "clip_count": clip_count,
        "preview": True,
    }
    if edit_payload:
        payload["edit_plan_export"] = edit_payload
    await db.execute(
        text(
            """
            INSERT INTO tasks (task_id, user_id, project_id, run_id, task_type, status, priority, payload, credits_reserved)
            VALUES (:tid, :uid, :project_id, CAST(:run_id AS UUID), 'director_export_preview', 'queued', :priority, :payload, 0)
            """
        ),
        {
            "tid": task_id,
            "uid": user_id,
            "project_id": project_id,
            "run_id": run_id,
            "priority": priority,
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )
    await db.commit()

    celery_app.send_task(
        "app.tasks.director_tasks.director_export_preview_task",
        args=[task_id, str(user_id), payload],
        kwargs={"transaction_id": None},
        queue="default",
        priority=priority,
    )
    return {"task_id": task_id, "status": "queued", "clip_count": clip_count}


def _normalize_shot_indices(raw_indices) -> list[int] | None:
    if not raw_indices:
        return None
    if not isinstance(raw_indices, (list, tuple, set)):
        raise HTTPException(status_code=400, detail="shot_indices must be a list")
    try:
        indices = sorted({int(idx) for idx in raw_indices})
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="shot_indices must be integers") from exc
    if any(idx <= 0 for idx in indices):
        raise HTTPException(status_code=400, detail="shot_indices must be positive")
    return indices


async def _count_shot_rows(
    db: AsyncSession,
    project_id: str,
    user_id: int,
    shot_indices: list[int] | None,
) -> int:
    params: dict = {"pid": project_id, "uid": user_id}
    query = text("SELECT COUNT(*) FROM shot_rows WHERE project_id = :pid AND user_id = :uid")
    if shot_indices:
        params["indices"] = shot_indices
        query = text(
            """
            SELECT COUNT(*)
            FROM shot_rows
            WHERE project_id = :pid
              AND user_id = :uid
              AND shot_index IN :indices
            """
        ).bindparams(bindparam("indices", expanding=True))
    result = await db.execute(query, params)
    return int(result.scalar() or 0)


async def _count_exportable_videos(
    db: AsyncSession,
    project_id: str,
    user_id: int,
    shot_indices: list[int] | None = None,
) -> int:
    query = text(
        """
        SELECT COUNT(*)
        FROM shot_rows
        WHERE project_id = :pid
          AND user_id = :uid
          AND selected_video IS NOT NULL
          AND selected_video <> ''
        """
    )
    params: dict[str, Any] = {"pid": project_id, "uid": user_id}
    if shot_indices is not None:
        if not shot_indices:
            return 0
        query = text(
            """
            SELECT COUNT(*)
            FROM shot_rows
            WHERE project_id = :pid
              AND user_id = :uid
              AND shot_index IN :indices
              AND selected_video IS NOT NULL
              AND selected_video <> ''
            """
        ).bindparams(bindparam("indices", expanding=True))
        params["indices"] = shot_indices
    result = await db.execute(query, params)
    return int(result.scalar() or 0)


async def _load_current_final_edit_plan(db: AsyncSession, project_id: str, user_id: int) -> dict[str, Any]:
    from app.services.final_edit import build_default_edit_plan, merge_plan_with_shots

    owner = await db.execute(
        text("SELECT 1 FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
        {"project_id": project_id, "user_id": user_id},
    )
    if not owner.fetchone():
        raise HTTPException(status_code=404, detail="Project not found")

    shot_result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected_video
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    shot_rows = [dict(row) for row in shot_result.mappings().fetchall()]
    plan_result = await db.execute(
        text(
            """
            SELECT plan_json
            FROM final_edit_plans
            WHERE project_id = :project_id AND user_id = :user_id
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    row = plan_result.fetchone()
    if not row:
        return build_default_edit_plan(shot_rows)
    return merge_plan_with_shots(row.plan_json, shot_rows)


async def _save_final_edit_plan_json(
    db: AsyncSession,
    project_id: str,
    user_id: int,
    plan: dict[str, Any],
) -> None:
    from app.services.final_edit import normalize_edit_plan

    normalized = normalize_edit_plan(plan)
    await db.execute(
        text(
            """
            INSERT INTO final_edit_plans (project_id, user_id, plan_json)
            VALUES (:project_id, :user_id, CAST(:plan_json AS JSONB))
            ON CONFLICT (project_id, user_id)
            DO UPDATE SET plan_json = EXCLUDED.plan_json, updated_at = NOW()
            """
        ),
        {
            "project_id": project_id,
            "user_id": user_id,
            "plan_json": json.dumps(normalized, ensure_ascii=False),
        },
    )
    await db.commit()


def _generate_final_cut_plan_with_doubao(
    recipe: dict[str, Any],
    current_plan: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    from app.services.final_cut_ai import generate_final_cut_plan
    from app.services.key_pool import key_pool

    key_name: str | None = None
    try:
        key_name, api_key = key_pool.acquire("doubao")
        return generate_final_cut_plan(
            api_key,
            recipe=recipe,
            current_plan=current_plan,
            user_instruction=instruction,
        )
    except Exception as exc:
        if key_name:
            key_pool.report_error(key_name, str(exc))
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


@router.post("/reference-images")
async def director_reference_images(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    _block_direct_production_entrypoint("director_ref_images")
    return await _dispatch_director_task("director_ref_images", body, current_user["id"], current_user["tier"], db)


# ─── 标注 & 参考图绑定 ──────────────────────────────────────────────────────────


def _build_clean_script_annotation(body: dict) -> dict:
    from app.services.prompt.script_annotator import annotate_clean_script_with_mode
    from app.services.prompt.engine import resolve_filtered_library_ids

    raw_text = body.get("raw_text", "")
    if not raw_text:
        raise HTTPException(400, "raw_text is required")

    filter_mode = body.get("filter_mode", "")
    filter_value = body.get("filter_value", "")
    library_ids = None
    if filter_mode and filter_value:
        library_ids = resolve_filtered_library_ids(filter_mode, filter_value)

    return annotate_clean_script_with_mode(
        raw_text,
        style_hint=body.get("style_hint", ""),
        context_hint=body.get("context_hint", ""),
        prompt_mode=body.get("prompt_mode", "compiled"),
        library_ids=library_ids,
    )


@router.post("/annotate-clean-script")
async def annotate_clean_script(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    result = _build_clean_script_annotation(body)
    return result


@router.post("/annotate-clean-script/export")
async def export_annotated_clean_script(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    from app.services.prompt.script_annotator import export_annotation_report

    export_format = str(body.get("format") or "csv").strip().lower()
    if export_format not in {"csv", "json", "markdown"}:
        raise HTTPException(400, "format must be one of: csv, json, markdown")

    package = _build_clean_script_annotation(body)
    content = export_annotation_report(package, export_format)
    extension = "md" if export_format == "markdown" else export_format
    content_type = {
        "csv": "text/csv; charset=utf-8",
        "json": "application/json; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
    }[export_format]
    return {
        "format": export_format,
        "filename": f"clean-script-annotation.{extension}",
        "content_type": content_type,
        "content": content,
    }


@router.get("/{project_id}/reference-bindings")
async def get_reference_bindings(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    result = await db.execute(
        text("""
            SELECT shot_index, character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                   selected_image, selected_video
            FROM shot_rows
            WHERE project_id = :pid AND user_id = :uid
            ORDER BY shot_index
        """),
        {"pid": project_id, "uid": user_id},
    )
    rows = result.mappings().fetchall()
    bindings = []
    for row in rows:
        bindings.append({
            "shot_index": row["shot_index"],
            "character_refs": row["character_refs_json"] or [],
            "scene_refs": row["scene_refs_json"] or [],
            "prop_refs": row["prop_refs_json"] or [],
            "costume_refs": row["costume_refs_json"] or [],
            "style_refs": row["style_refs_json"] or [],
            "selected_image": row["selected_image"],
            "selected_video": row["selected_video"],
        })
    return {"project_id": project_id, "bindings": bindings}


@router.post("/{project_id}/reference-bindings")
async def save_reference_bindings(
    project_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    bindings = body.get("bindings", [])
    updated = 0
    for binding in bindings:
        shot_index = binding.get("shot_index")
        if shot_index is None:
            continue
        result = await db.execute(
            text("""
                UPDATE shot_rows
                SET character_refs_json = CAST(:char_refs AS JSONB),
                    scene_refs_json = CAST(:scene_refs AS JSONB),
                    prop_refs_json = CAST(:prop_refs AS JSONB),
                    costume_refs_json = CAST(:costume_refs AS JSONB),
                    style_refs_json = CAST(:style_refs AS JSONB),
                    updated_at = NOW()
                WHERE project_id = :pid AND user_id = :uid AND shot_index = :idx
            """),
            {
                "pid": project_id,
                "uid": user_id,
                "idx": shot_index,
                "char_refs": json.dumps(binding.get("character_refs", []), ensure_ascii=False),
                "scene_refs": json.dumps(binding.get("scene_refs", []), ensure_ascii=False),
                "prop_refs": json.dumps(binding.get("prop_refs", []), ensure_ascii=False),
                "costume_refs": json.dumps(binding.get("costume_refs", []), ensure_ascii=False),
                "style_refs": json.dumps(binding.get("style_refs", []), ensure_ascii=False),
            },
        )
        updated += int(result.rowcount or 0)
    await db.commit()
    return {"status": "ok", "updated": updated}


# ─── 组 B：导演扩展端点 ──────────────────────────────────────────────────────────


@router.post("/chat/jobs")
async def director_chat_submit_job(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """提交导演 chat job，立即返回 job_id（< 2s）。"""
    import concurrent.futures
    from app.services.job_registry import create_job, update_job, JobStatus

    message = (body or {}).get("message", "").strip()
    if not message:
        raise HTTPException(422, "message is required")

    session_id = (body or {}).get("session_id") or uuid.uuid4().hex[:12]
    job = create_job(session_id, "director_chat", max_duration=300.0, user_id=str(current_user["id"]))

    def _run():
        try:
            update_job(job.job_id, status=JobStatus.RUNNING, stage_text="处理中")
            from app.services.director.explainer import explain_run as _explain
            result = {"message": message, "session_id": session_id, "status": "processed"}
            update_job(job.job_id, status=JobStatus.DONE, result=result, progress=100)
        except Exception as exc:
            update_job(job.job_id, status=JobStatus.FAILED, error=str(exc))

    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    _executor.submit(_run)
    return {"job_id": job.job_id, "session_id": session_id, "status": "queued"}


@router.get("/chat/jobs/{job_id}")
async def director_chat_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """查询 chat job 状态。"""
    from app.services.job_registry import get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.to_dict()


@router.get("/explain-run")
async def director_explain_run(
    project_id: str = "",
    event_type: str = "",
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """解释导演运行过程（trace 日志）。"""
    try:
        from app.services.director.trace import load_trace_records
        events = load_trace_records(project_id, event_type=event_type, limit=limit)
        return {"project_id": project_id, "events": events, "total": len(events)}
    except Exception as exc:
        raise HTTPException(500, f"explain-run failed: {exc}")


@router.get("/{project_id}/{name}")
async def director_get_output(
    project_id: str,
    name: str,
    slim: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """获取导演输出文件列表和状态。"""
    from pathlib import Path
    from app.services.director.paths import safe_path_segment

    safe_proj = safe_path_segment(project_id)
    safe_name = safe_path_segment(name)
    base_dir = Path("storage") / safe_proj / "director" / safe_name
    out_dir = base_dir
    if not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)

    final = out_dir / "final.mp4"
    if slim:
        return {
            "done": final.exists(),
            "final_url": f"/storage/{project_id}/director/{name}/final.mp4" if final.exists() else None,
        }

    files = [
        {"file": f.name, "size": f.stat().st_size}
        for f in sorted(out_dir.rglob("*")) if f.is_file()
    ]
    return {
        "done": final.exists(),
        "final_url": f"/storage/{project_id}/director/{name}/final.mp4" if final.exists() else None,
        "files": files,
    }
