from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runtime import normalize_agent_event
from app.services.agent_runtime_contract import public_capability
from app.services.agent_run_state_machine import evaluate_production_stages, recommend_next_action


SNAPSHOT_VERSION = "agent_run_snapshot_v1"
DEFAULT_EVENT_LIMIT = 300
DEFAULT_TASK_LIMIT = 300
DEFAULT_ARTIFACT_LIMIT = 120
DEFAULT_EVIDENCE_ITEM_LIMIT = 80
DEFAULT_STREAM_LIMIT = 200

STANDARD_NODES: list[dict[str, Any]] = [
    {"id": "read_context", "title": "读取上下文", "phases": {"read_context", "created"}},
    {"id": "merge_memory", "title": "合并记忆与账本", "phases": {"merge_memory", "plan_story", "lock_assets"}},
    {"id": "plan_shots", "title": "规划剧情/分镜", "phases": {"plan_shots", "generate_story_plan", "plan_scene", "generate_storyboard"}},
    {"id": "lock_visual_assets", "title": "锁定视觉资产", "phases": {"plan_visual_assets", "lock_assets"}},
    {"id": "generate_keyframes", "title": "生成关键帧", "phases": {"generate_keyframes", "seedream_acquire_key", "seedream_requesting", "seedream_result", "writeback_selected_image"}},
    {"id": "generate_videos", "title": "生成视频", "phases": {"generate_videos", "seedance_acquire_key", "seedance_requesting", "seedance_result", "writeback_selected_video"}},
    {"id": "audio_subtitles", "title": "配音/BGM/字幕", "phases": {"generate_voice", "select_bgm", "generate_subtitles", "tts_requesting", "tts_result"}},
    {"id": "ffmpeg_export", "title": "FFmpeg 剪辑导出", "phases": {"ffmpeg_export", "validate_plan", "normalize_clips", "concat_clips", "mix_audio", "burn_subtitles", "export_mp4", "probe_output"}},
    {"id": "quality_check", "title": "成片质检", "phases": {"quality_check", "delivery_audit"}},
    {"id": "writeback", "title": "回写复盘", "phases": {"writeback", "writeback_review"}},
]

NODE_ID_BY_PHASE = {
    phase: node["id"]
    for node in STANDARD_NODES
    for phase in node["phases"]
}

TERMINAL_FAILED = {"failed", "dead_letter", "cancelled"}
TERMINAL_DONE = {"done", "completed"}
ACTIVE_STATUSES = {"created", "queued", "pending", "running", "retrying", "dispatching", "verifying", "writing_back", "provider_waiting", "provider_requesting"}


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    return default


def _bounded_limit(value: Any, *, default: int, maximum: int) -> int:
    return max(1, min(_safe_int(value, default), maximum))


def _tail(items: list[Any], limit: int) -> list[Any]:
    if limit <= 0:
        return []
    return items[-limit:]


async def get_agent_run_snapshot(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: int,
    event_limit: int = DEFAULT_EVENT_LIMIT,
    task_limit: int = DEFAULT_TASK_LIMIT,
    artifact_limit: int = DEFAULT_ARTIFACT_LIMIT,
    evidence_item_limit: int = DEFAULT_EVIDENCE_ITEM_LIMIT,
    stream_limit: int = DEFAULT_STREAM_LIMIT,
) -> dict[str, Any] | None:
    run = await _fetch_run(db, run_id=run_id, user_id=user_id)
    if not run:
        return None

    project_id = str(run["project_id"])
    event_limit = _bounded_limit(event_limit, default=DEFAULT_EVENT_LIMIT, maximum=1000)
    task_limit = _bounded_limit(task_limit, default=DEFAULT_TASK_LIMIT, maximum=1000)
    artifact_limit = _bounded_limit(artifact_limit, default=DEFAULT_ARTIFACT_LIMIT, maximum=500)
    evidence_item_limit = _bounded_limit(evidence_item_limit, default=DEFAULT_EVIDENCE_ITEM_LIMIT, maximum=300)
    stream_limit = _bounded_limit(stream_limit, default=DEFAULT_STREAM_LIMIT, maximum=500)
    related_run_ids, related_runs = await _fetch_related_run_ids(db, run=run, user_id=user_id)
    events, event_total = await _fetch_events(db, run_ids=related_run_ids, limit=event_limit)
    tasks, task_total = await _fetch_tasks(db, run_ids=related_run_ids, limit=task_limit)
    steps = await _fetch_steps(db, run_ids=related_run_ids)
    artifacts, artifact_total = await _fetch_artifacts(db, run_ids=related_run_ids, limit=artifact_limit)
    shots = await _fetch_shots(db, project_id=project_id, user_id=user_id)
    shots = _filter_shots_for_clean_start(shots, run=run)
    production_run = await _fetch_video_production_run(db, run_ids=related_run_ids, user_id=user_id)
    final_video_preview = await _fetch_latest_final_video_preview(
        db,
        project_id=project_id,
        user_id=user_id,
        run_ids=related_run_ids,
    )
    production_run = _merge_final_video_preview(production_run, final_video_preview)
    credit_ledger = await _fetch_credit_ledger(db, tasks=tasks, user_id=user_id)
    display_run = _display_run_state(run=run, related_runs=related_runs, tasks=tasks, production_run=production_run)
    state_tasks = _effective_tasks_for_state(tasks=tasks, shots=shots)

    nodes = _build_nodes(run=display_run, events=events, tasks=state_tasks, steps=steps, artifacts=artifacts, shots=shots, production_run=production_run)
    flow = evaluate_production_stages(shots=shots, tasks=state_tasks, production_run=production_run)
    _attach_flow_to_nodes(nodes, flow)
    state_machine = _build_state_machine_layer(flow=flow, shots=shots, tasks=state_tasks, production_run=production_run)
    stream = _build_stream(events=events, nodes=nodes, limit=stream_limit)
    event_groups = _group_events_by_visibility(events)
    evidence = _build_evidence(nodes=nodes, events=events, tasks=tasks, steps=steps, artifacts=artifacts, shots=shots, production_run=production_run, item_limit=evidence_item_limit)
    ledger = _build_ledger(run=display_run, shots=shots, production_run=production_run)
    evidence_layers = _build_evidence_layers(
        run=display_run,
        events=events,
        tasks=tasks,
        steps=steps,
        artifacts=artifacts,
        shots=shots,
        ledger=ledger,
        nodes=nodes,
        production_run=production_run,
        item_limit=evidence_item_limit,
    )
    actions = _build_actions(run=display_run, nodes=nodes, tasks=state_tasks, production_run=production_run)
    outputs = _build_outputs(
        run=display_run,
        events=events,
        tasks=tasks,
        steps=steps,
        artifacts=artifacts,
        shots=shots,
        production_run=production_run,
    )

    decision_context = _build_decision_context(run=run, state_machine=state_machine)

    snapshot = {
        "version": SNAPSHOT_VERSION,
        "run": {
            "run_id": str(run["id"]),
            "project_id": project_id,
            "user_id": run["user_id"],
            "trigger_type": run.get("trigger_type"),
            "goal": run.get("goal") or "",
            "status": display_run.get("status") or "created",
            "current_phase": display_run.get("current_phase") or "",
            "mode": run.get("mode") or "step",
            "started_at": _iso(run.get("started_at")),
            "ended_at": _iso(display_run.get("ended_at")),
            "summary": display_run.get("summary") or "",
            "final_decision": display_run.get("final_decision") or "",
        },
        "project": {
            "project_id": project_id,
            "name": run.get("project_name") or project_id,
        },
        "budget": {
            "estimated_max_credits": int(run.get("estimated_max_credits") or 0),
            "allowed_max_credits": int(run.get("allowed_max_credits") or 0),
            "reserved_credits": int(run.get("reserved_credits") or 0),
            "spent_credits": int(run.get("spent_credits") or 0),
            "refunded_credits": credit_ledger["refunded_credits"],
            "remaining_run_budget": int(run.get("remaining_run_budget") or 0),
            "task_credits_reserved": sum(int(task.get("credits_reserved") or 0) for task in tasks),
            "task_credits_charged": credit_ledger["charged_credits"],
            "task_credits_refunded": credit_ledger["refunded_credits"],
        },
        "ledger": ledger,
        "nodes": nodes,
        "flow": flow,
        "state_machine": state_machine,
        "decision_context": decision_context,
        "stream": stream,
        "events": event_groups,
        "evidence": evidence,
        "evidence_layers": evidence_layers,
        "outputs": outputs,
        "actions": actions,
        "artifacts": artifacts,
        "tasks": tasks,
        "credit_ledger": credit_ledger,
        "meta": {
            "limits": {
                "events": event_limit,
                "tasks": task_limit,
                "artifacts": artifact_limit,
                "evidence_items": evidence_item_limit,
                "stream": stream_limit,
            },
            "totals": {
                "events": event_total,
                "tasks": task_total,
                "artifacts": artifact_total,
                "steps": len(steps),
                "shots": len(shots),
                "related_runs": len(related_run_ids),
            },
            "truncated": {
                "events": event_total > len(events),
                "tasks": task_total > len(tasks),
                "artifacts": artifact_total > len(artifacts),
            },
        },
        "related_runs": related_runs,
    }
    validate_snapshot_contract(snapshot)
    return snapshot


def validate_snapshot_contract(snapshot: dict[str, Any]) -> None:
    required_top = {"version", "run", "project", "budget", "ledger", "nodes", "flow", "state_machine", "decision_context", "stream", "events", "evidence", "evidence_layers", "outputs", "actions", "artifacts", "tasks"}
    missing = required_top - set(snapshot)
    if missing:
        raise ValueError(f"snapshot missing top-level fields: {sorted(missing)}")
    if snapshot["version"] != SNAPSHOT_VERSION:
        raise ValueError(f"unsupported snapshot version: {snapshot['version']}")
    if not isinstance(snapshot["nodes"], list):
        raise ValueError("snapshot.nodes must be a list")
    node_ids = {node.get("id") for node in snapshot["nodes"]}
    for required in [node["id"] for node in STANDARD_NODES]:
        if required not in node_ids:
            raise ValueError(f"snapshot missing node: {required}")
    for node in snapshot["nodes"]:
        for field in ("id", "title", "status", "summary", "progress", "event_ids", "task_ids", "available_actions"):
            if field not in node:
                raise ValueError(f"snapshot node missing field {field}: {node.get('id')}")
    if not isinstance(snapshot["flow"], list):
        raise ValueError("snapshot.flow must be a list")
    if not isinstance(snapshot["state_machine"], dict):
        raise ValueError("snapshot.state_machine must be a dict")
    for field in ("stage", "allowed", "blocked", "missing", "reason", "next_action", "available_actions"):
        if field not in snapshot["state_machine"]:
            raise ValueError(f"snapshot.state_machine missing field {field}")
    if not isinstance(snapshot["decision_context"], dict):
        raise ValueError("snapshot.decision_context must be a dict")
    for field in ("current_goal", "awaiting_user", "pending_action", "last_recommendation", "blocked_by", "block_reason", "next_action", "routing_source", "target_domain", "updated_at"):
        if field not in snapshot["decision_context"]:
            raise ValueError(f"snapshot.decision_context missing field {field}")
    for stage in snapshot["flow"]:
        for field in ("id", "title", "action", "node_id", "status", "source", "progress", "gate", "stats", "policy"):
            if field not in stage:
                raise ValueError(f"snapshot flow stage missing field {field}: {stage.get('id')}")
    if not isinstance(snapshot["evidence"], dict):
        raise ValueError("snapshot.evidence must be a dict")
    if not isinstance(snapshot["evidence_layers"], dict):
        raise ValueError("snapshot.evidence_layers must be a dict")
    if not isinstance(snapshot["events"], dict):
        raise ValueError("snapshot.events must be a dict")
    for visibility in ("user", "expert", "debug"):
        if visibility not in snapshot["events"]:
            raise ValueError(f"snapshot missing event visibility: {visibility}")
    for event in [item for group in snapshot["events"].values() for item in group]:
        for field in ("actor", "event_kind", "summary", "visibility"):
            if field not in event:
                raise ValueError(f"snapshot event missing field {field}: {event.get('id')}")
    for event in snapshot["stream"]:
        for field in ("actor", "event_kind", "summary"):
            if field not in event:
                raise ValueError(f"snapshot stream event missing field {field}: {event.get('id')}")
        if event.get("visibility") == "debug" and not _debug_event_allowed_in_stream(event):
            raise ValueError(f"debug event leaked into stream: {event.get('id')}")
    if not isinstance(snapshot["outputs"], dict):
        raise ValueError("snapshot.outputs must be a dict")
    for layer_id in (
        "agent_execution_log",
        "brain_trace",
        "detailed_flow_ledger",
        "raw_read_list",
        "production_stream_terminal",
        "progress_ledger",
        "creative_technique_ledger",
        "state_machine_flow",
    ):
        if layer_id not in snapshot["evidence_layers"]:
            raise ValueError(f"snapshot missing evidence layer: {layer_id}")


async def _fetch_run(db: AsyncSession, *, run_id: str, user_id: int) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT r.*, p.name AS project_name
            FROM agent_runs r
            JOIN projects p ON p.project_id = r.project_id AND p.user_id = r.user_id
            WHERE r.id = CAST(:run_id AS UUID)
              AND r.user_id = :user_id
            LIMIT 1
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _fetch_related_run_ids(db: AsyncSession, *, run: dict[str, Any], user_id: int) -> tuple[list[str], list[dict[str, Any]]]:
    root_id = str(run["id"])
    project_id = str(run["project_id"])
    result = await db.execute(
        text(
            """
            WITH event_child_runs AS (
                SELECT DISTINCT e.meta #>> '{result,run_id}' AS child_run_id
                FROM agent_events e
                WHERE e.run_id = CAST(:root_uuid AS UUID)
                  AND e.meta #>> '{result,run_id}' IS NOT NULL
            )
            SELECT r.id::text AS id, r.project_id, r.user_id, r.status, r.current_phase,
                   r.summary, r.final_decision, r.started_at, r.ended_at, r.meta
            FROM agent_runs r
            LEFT JOIN event_child_runs ec ON ec.child_run_id = r.id::text
            WHERE r.user_id = :user_id
              AND r.project_id = :project_id
              AND (
                    r.id = CAST(:root_uuid AS UUID)
                 OR r.meta->>'source_run_id' = :root_text
                 OR r.meta->>'_chain_run_id' = :root_text
                 OR r.meta #>> '{human_routing,source_run_id}' = :root_text
                 OR ec.child_run_id IS NOT NULL
              )
            ORDER BY r.started_at ASC
            """
        ),
        {"root_uuid": root_id, "root_text": root_id, "project_id": project_id, "user_id": user_id},
    )
    rows = [dict(row) for row in result.mappings().all()]
    if not rows:
        rows = [{
            "id": root_id,
            "project_id": project_id,
            "user_id": user_id,
            "status": run.get("status"),
            "current_phase": run.get("current_phase"),
            "summary": run.get("summary"),
            "final_decision": run.get("final_decision"),
            "started_at": run.get("started_at"),
            "ended_at": run.get("ended_at"),
            "meta": run.get("meta"),
        }]
    related_ids = []
    for row in rows:
        item = str(row.get("id") or "").strip()
        if item and item not in related_ids:
            related_ids.append(item)
    return related_ids or [root_id], rows


def _display_run_state(
    *,
    run: dict[str, Any],
    related_runs: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
) -> dict[str, Any]:
    display = dict(run)
    active_tasks = [task for task in tasks if task.get("status") in ACTIVE_STATUSES]
    latest_related = related_runs[-1] if related_runs else {}
    if active_tasks:
        latest_task = active_tasks[-1]
        display["status"] = "running"
        display["current_phase"] = latest_task.get("task_type") or latest_related.get("current_phase") or "dispatching"
        display["summary"] = _running_task_summary(latest_task)
        display["final_decision"] = latest_related.get("final_decision") or display.get("final_decision") or ""
        display["ended_at"] = None
        return display
    if production_run and str(production_run.get("status") or "") in ACTIVE_STATUSES:
        display["status"] = "running"
        display["current_phase"] = production_run.get("current_stage") or "dispatching"
        display["summary"] = str(production_run.get("current_stage") or "视频生产执行中")
        display["ended_at"] = None
        return display
    terminal_related = [item for item in related_runs if str(item.get("id") or "") != str(run.get("id") or "")]
    if terminal_related:
        latest = terminal_related[-1]
        latest_status = str(latest.get("status") or "")
        if latest_status and latest_status != "created":
            display["status"] = latest_status
            display["current_phase"] = latest.get("current_phase") or display.get("current_phase")
            display["summary"] = latest.get("summary") or display.get("summary")
            display["final_decision"] = latest.get("final_decision") or display.get("final_decision")
            display["ended_at"] = latest.get("ended_at") or display.get("ended_at")
    return display


def _running_task_summary(task: dict[str, Any]) -> str:
    task_type = str(task.get("task_type") or "")
    stage = str(task.get("stage_text") or "").strip()
    if task_type == "video_gen":
        return f"视频生成执行中{f'：{stage}' if stage else ''}"
    if task_type == "image_gen":
        return f"关键帧生成执行中{f'：{stage}' if stage else ''}"
    return f"任务执行中{f'：{stage}' if stage else ''}"


def _effective_tasks_for_state(*, tasks: list[dict[str, Any]], shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_images = {str(shot.get("shot_index")) for shot in shots if shot.get("selected_image")}
    selected_videos = {str(shot.get("shot_index")) for shot in shots if shot.get("selected_video")}
    successful_by_type: set[tuple[str, str]] = set()
    for task in tasks:
        if task.get("status") not in TERMINAL_DONE:
            continue
        task_type = str(task.get("task_type") or "")
        shot_index = _task_shot_index(task)
        if task_type and shot_index:
            successful_by_type.add((task_type, shot_index))

    effective: list[dict[str, Any]] = []
    for task in tasks:
        task_type = str(task.get("task_type") or "")
        shot_index = _task_shot_index(task)
        if task.get("status") in TERMINAL_FAILED:
            if task_type == "image_gen" and shot_index in selected_images:
                continue
            if task_type == "video_gen" and (shot_index in selected_videos or (task_type, shot_index) in successful_by_type):
                continue
        effective.append(task)
    return effective


def _task_shot_index(task: dict[str, Any]) -> str:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    value = payload.get("shot_index") or payload.get("index") or payload.get("shot")
    return str(value).strip() if value not in (None, "") else ""


async def _fetch_credit_ledger(db: AsyncSession, *, tasks: list[dict[str, Any]], user_id: int) -> dict[str, Any]:
    refs = sorted({
        str(task.get("credit_transaction_id") or (task.get("payload") or {}).get("_credit_transaction_id") or "").strip()
        for task in tasks
        if str(task.get("credit_transaction_id") or (task.get("payload") or {}).get("_credit_transaction_id") or "").strip()
    })
    if not refs:
        return {
            "transaction_ids": [],
            "reserved_credits": 0,
            "charged_credits": 0,
            "refunded_credits": 0,
            "transactions": [],
            "exact": False,
        }
    query = text(
        """
        SELECT reference_id, tx_type, amount, balance_after, description, created_at
        FROM credit_transactions
        WHERE user_id = :user_id
          AND reference_id IN :refs
        ORDER BY created_at ASC
        """
    ).bindparams(bindparam("refs", expanding=True))
    result = await db.execute(query, {"user_id": user_id, "refs": refs})
    rows = [
        {
            "reference_id": row.get("reference_id"),
            "tx_type": row.get("tx_type"),
            "amount": int(row.get("amount") or 0),
            "balance_after": int(row.get("balance_after") or 0),
            "description": row.get("description") or "",
            "created_at": _iso(row.get("created_at")),
        }
        for row in result.mappings().all()
    ]
    return {
        "transaction_ids": refs,
        "reserved_credits": sum(abs(item["amount"]) for item in rows if item["tx_type"] == "reserve"),
        "charged_credits": sum(abs(item["amount"]) for item in rows if item["tx_type"] == "charge"),
        "refunded_credits": sum(item["amount"] for item in rows if item["tx_type"] == "refund"),
        "transactions": rows,
        "exact": True,
    }


async def _fetch_events(db: AsyncSession, *, run_ids: list[str], limit: int) -> tuple[list[dict[str, Any]], int]:
    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM agent_events
            WHERE run_id::text IN :run_ids
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids},
    )
    result = await db.execute(
        text(
            """
            SELECT *
            FROM (
                SELECT *
                FROM agent_events
                WHERE run_id::text IN :run_ids
                ORDER BY created_at DESC
                LIMIT :limit
            ) recent_events
            ORDER BY created_at ASC
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids, "limit": limit},
    )
    return [_event(row) for row in result.mappings().all()], int(count_result.scalar_one() or 0)


async def _fetch_tasks(db: AsyncSession, *, run_ids: list[str], limit: int) -> tuple[list[dict[str, Any]], int]:
    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE run_id::text IN :run_ids
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids},
    )
    result = await db.execute(
        text(
            """
            SELECT task_id::text AS task_id, project_id, run_id::text AS run_id, user_id,
                   task_type, status, progress, stage_text, error_message,
                   credits_reserved, credits_charged, credit_transaction_id, payload, result,
                   created_at, updated_at, completed_at
            FROM (
                SELECT *
                FROM tasks
                WHERE run_id::text IN :run_ids
                ORDER BY created_at DESC
                LIMIT :limit
            ) recent_tasks
            ORDER BY created_at ASC
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids, "limit": limit},
    )
    return [_task(row) for row in result.mappings().all()], int(count_result.scalar_one() or 0)


async def _fetch_steps(db: AsyncSession, *, run_ids: list[str]) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT id::text AS id, run_id::text AS run_id, step_index, phase, title,
                   status, input_summary, decision_summary, output_summary,
                   stop_reason, meta, started_at, ended_at, updated_at
            FROM agent_steps
            WHERE run_id::text IN :run_ids
            ORDER BY step_index ASC
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids},
    )
    return [_step(row) for row in result.mappings().all()]


async def _fetch_artifacts(db: AsyncSession, *, run_ids: list[str], limit: int) -> tuple[list[dict[str, Any]], int]:
    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM agent_artifacts
            WHERE run_id::text IN :run_ids
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids},
    )
    result = await db.execute(
        text(
            """
            SELECT id::text AS id, run_id::text AS run_id, project_id, task_id::text AS task_id,
                   user_id, artifact_type, uri, summary, meta, created_at
            FROM (
                SELECT *
                FROM agent_artifacts
                WHERE run_id::text IN :run_ids
                ORDER BY created_at DESC
                LIMIT :limit
            ) recent_artifacts
            ORDER BY created_at ASC
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids, "limit": limit},
    )
    return [_artifact(row) for row in result.mappings().all()], int(count_result.scalar_one() or 0)


async def _fetch_shots(db: AsyncSession, *, project_id: str, user_id: int) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected_image, selected_video,
                   image_candidates_json, video_variants_json, last_error, updated_at
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    return [_shot(row) for row in result.mappings().all()]


def _filter_shots_for_clean_start(shots: list[dict[str, Any]], *, run: dict[str, Any]) -> list[dict[str, Any]]:
    meta = _json(run.get("meta"))
    if not bool(meta.get("clean_start")):
        return shots
    started_at = _coerce_datetime(run.get("started_at"))
    if started_at is None:
        return shots
    filtered: list[dict[str, Any]] = []
    for shot in shots:
        updated_at = _coerce_datetime(shot.get("updated_at"))
        if updated_at is None:
            continue
        if updated_at >= started_at:
            filtered.append(shot)
    return filtered


async def _fetch_video_production_run(db: AsyncSession, *, run_ids: list[str], user_id: int) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT id::text AS id, project_id, user_id, agent_run_id::text AS agent_run_id,
                   episode, scene, target_duration_sec, status, current_stage, goal,
                   plan_json, quality_report_json, edit_strategy_json,
                   final_delivery_report_json, final_task_id::text AS final_task_id,
                   final_video_url, created_at, updated_at
            FROM video_production_runs
            WHERE agent_run_id::text IN :run_ids
              AND user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"run_ids": run_ids, "user_id": user_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _fetch_latest_final_video_preview(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    run_ids: list[str],
) -> dict[str, Any] | None:
    if not run_ids:
        return None
    result = await db.execute(
        text(
            """
            SELECT t.project_id,
                   t.user_id,
                   t.task_id::text AS final_task_id,
                   COALESCE(
                       NULLIF(a.file_url, ''),
                       NULLIF(t.result->>'final_video_url', ''),
                       NULLIF(t.result->>'preview_url', '')
                   ) AS final_video_url,
                   COALESCE(a.created_at, t.completed_at, t.updated_at, t.created_at) AS exported_at
            FROM tasks t
            LEFT JOIN final_video_assets a
              ON a.task_id = t.task_id
             AND a.project_id = t.project_id
             AND a.user_id = t.user_id
            WHERE t.project_id = :project_id
              AND t.user_id = :user_id
              AND t.run_id::text IN :run_ids
              AND t.task_type IN ('director_export_preview', 'director_export_final')
              AND t.status IN ('done', 'completed')
              AND COALESCE(
                    NULLIF(a.file_url, ''),
                    NULLIF(t.result->>'final_video_url', ''),
                    NULLIF(t.result->>'preview_url', '')
                  ) IS NOT NULL
            ORDER BY exported_at DESC
            LIMIT 1
            """
        ).bindparams(bindparam("run_ids", expanding=True)),
        {"project_id": project_id, "user_id": user_id, "run_ids": run_ids},
    )
    row = result.mappings().first()
    return dict(row) if row else None


def _merge_final_video_preview(
    production_run: dict[str, Any] | None,
    final_video_preview: dict[str, Any] | None,
) -> dict[str, Any] | None:
    preview_url = str((final_video_preview or {}).get("final_video_url") or "").strip()
    if not preview_url:
        return production_run
    if not production_run:
        return {
            "project_id": final_video_preview.get("project_id"),
            "user_id": final_video_preview.get("user_id"),
            "final_task_id": final_video_preview.get("final_task_id") or "",
            "final_video_url": preview_url,
            "status": "preview_exported",
            "current_stage": "preview_exported",
        }
    if str(production_run.get("final_video_url") or "").strip():
        return production_run
    return {
        **production_run,
        "final_task_id": production_run.get("final_task_id") or final_video_preview.get("final_task_id") or "",
        "final_video_url": preview_url,
        "status": production_run.get("status") or "preview_exported",
        "current_stage": production_run.get("current_stage") or "preview_exported",
    }


def _build_nodes(
    *,
    run: dict[str, Any],
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for index, spec in enumerate(STANDARD_NODES, 1):
        node_events = [event for event in events if _node_for_event(event) == spec["id"]]
        node_steps = [step for step in steps if _node_for_phase(step.get("phase")) == spec["id"]]
        node_tasks = [task for task in tasks if _node_for_task(task) == spec["id"]]
        node_artifacts = [artifact for artifact in artifacts if _node_for_artifact(artifact) == spec["id"]]
        status = _node_status(spec["id"], node_events, node_tasks, node_steps, run, production_run)
        summary = _node_summary(spec["id"], status, node_events, node_tasks, shots, production_run)
        nodes.append({
            "id": spec["id"],
            "title": spec["title"],
            "index": index,
            "status": status,
            "summary": summary,
            "brain_summary": _brain_summary(node_steps, node_events),
            "evidence_summary": _evidence_summary(node_events, node_tasks, node_artifacts),
            "progress": _node_progress(spec["id"], status, node_events, node_tasks, shots),
            "risks": _node_risks(node_events, node_tasks),
            "artifacts": node_artifacts,
            "event_ids": [event["id"] for event in node_events],
            "task_ids": [task["task_id"] for task in node_tasks],
            "available_actions": _node_actions(spec["id"], status, node_tasks, shots),
        })
    return nodes


def _attach_flow_to_nodes(nodes: list[dict[str, Any]], flow: list[dict[str, Any]]) -> None:
    by_node: dict[str, list[dict[str, Any]]] = {}
    for stage in flow:
        node_id = str(stage.get("node_id") or "")
        if not node_id:
            continue
        by_node.setdefault(node_id, []).append(stage)
    for node in nodes:
        stages = by_node.get(str(node.get("id") or ""), [])
        if not stages:
            continue
        blocked = next((stage for stage in stages if stage.get("status") == "blocked"), None)
        running = next((stage for stage in stages if stage.get("status") == "running"), None)
        active = blocked or running or next((stage for stage in stages if stage.get("status") == "pending"), stages[-1])
        node["flow_stages"] = stages
        node["gate"] = active.get("gate") or {}
        if blocked:
            node["status"] = "blocked"
            node["summary"] = str((blocked.get("gate") or {}).get("reason") or node.get("summary") or "blocked")
            node["risks"] = [
                *list(node.get("risks") or []),
                {"source": "state_machine", "title": "Flow gate blocked", "detail": node["summary"], "meta": blocked},
            ]


def _build_state_machine_layer(
    *,
    flow: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
) -> dict[str, Any]:
    current = next((stage for stage in flow if stage.get("status") in {"running", "blocked", "pending"}), flow[-1] if flow else {})
    gate = current.get("gate") if isinstance(current.get("gate"), dict) else {}
    next_step = recommend_next_action(shots=shots, tasks=tasks, production_run=production_run)
    available_actions = [
        stage.get("action")
        for stage in flow
        if (stage.get("gate") or {}).get("allowed") and stage.get("status") in {"pending", "running"}
    ]
    available_actions = [str(action) for action in dict.fromkeys(available_actions) if action]
    return {
        "stage": current.get("id") or next_step.get("stage_id") or "",
        "allowed": bool(gate.get("allowed", next_step.get("allowed", True))),
        "blocked": not bool(gate.get("allowed", next_step.get("allowed", True))),
        "missing": list(gate.get("missing") or next_step.get("missing") or []),
        "reason": str(gate.get("reason") or next_step.get("reason") or ""),
        "next_action": str(next_step.get("action") or ""),
        "available_actions": available_actions,
        "status": current.get("status") or next_step.get("status") or "",
        "evidence_summary": _state_machine_evidence_summary(flow, shots, tasks),
        "debug": {"current": current, "next": next_step},
    }


def _build_decision_context(*, run: dict[str, Any], state_machine: dict[str, Any]) -> dict[str, Any]:
    meta = run.get("meta") if isinstance(run.get("meta"), dict) else {}
    stored = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
    raw_pending = meta.get("pending_action") if isinstance(meta.get("pending_action"), dict) else stored.get("pending_action")
    pending = _compact_pending_action(raw_pending)
    pending = _pending_action_allowed_by_state(pending, state_machine)
    blocked = bool(state_machine.get("blocked"))
    blocked_by = list(state_machine.get("missing") or []) if blocked else stored.get("blocked_by")
    if not isinstance(blocked_by, list):
        blocked_by = []
    next_action = str((pending or {}).get("action") or "").strip()
    if not next_action:
        recovery_action = _recovery_action_for_missing(blocked_by)
        next_action = str((recovery_action if blocked else stored.get("next_action")) or state_machine.get("next_action") or "").strip()
    return {
        "current_goal": str(stored.get("current_goal") or run.get("goal") or "").strip(),
        "awaiting_user": "confirm" if pending else "",
        "pending_action": pending,
        "last_recommendation": str(stored.get("last_recommendation") or run.get("summary") or "").strip(),
        "blocked_by": [str(item) for item in blocked_by if str(item or "").strip()],
        "block_reason": str(stored.get("block_reason") or state_machine.get("reason") or "").strip(),
        "next_action": next_action,
        "routing_source": str(stored.get("routing_source") or "").strip(),
        "target_domain": str(stored.get("target_domain") or "").strip(),
        "updated_at": str(stored.get("updated_at") or "").strip(),
    }


def _compact_pending_action(pending_action: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(pending_action, dict) or not pending_action.get("action"):
        return None
    allowed = ("action", "recommendation", "domain", "target_domain", "status", "instruction")
    compact = {
        key: pending_action.get(key)
        for key in allowed
        if pending_action.get(key) not in (None, "", [], {})
    }
    return compact if compact.get("action") else None


def _pending_action_allowed_by_state(pending_action: dict[str, Any] | None, state_machine: dict[str, Any]) -> dict[str, Any] | None:
    if not pending_action:
        return None
    if not state_machine.get("blocked"):
        return pending_action
    missing = state_machine.get("missing") if isinstance(state_machine.get("missing"), list) else []
    allowed_actions = {
        str(state_machine.get("next_action") or "").strip(),
        _recovery_action_for_missing(missing),
    }
    allowed_actions = {action for action in allowed_actions if action}
    if not allowed_actions:
        return pending_action
    return pending_action if str(pending_action.get("action") or "").strip() in allowed_actions else None


def _recovery_action_for_missing(missing_items: list[Any]) -> str:
    missing = {str(item) for item in missing_items}
    if "shot_rows" in missing:
        return "generate_story_plan"
    if missing.intersection({"selected_image", "generate_keyframes", "review_keyframes", "image_review_blockers", "image_task_failures"}):
        return "generate_keyframes"
    if missing.intersection({"selected_video", "generate_videos", "review_videos", "video_review_blockers", "video_task_failures"}):
        return "generate_videos"
    if missing.intersection({"final_video_url", "final_cut"}):
        return "plan_final_edit"
    return ""


def _state_machine_evidence_summary(flow: list[dict[str, Any]], shots: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> str:
    blocked = sum(1 for stage in flow if stage.get("status") == "blocked")
    active_tasks = sum(1 for task in tasks if task.get("status") in ACTIVE_STATUSES)
    return f"shots={len(shots)}, active_tasks={active_tasks}, blocked_stages={blocked}"


def _build_stream(*, events: list[dict[str, Any]], nodes: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    node_ids = {node["id"] for node in nodes}
    human_response_texts = {
        _normalize_stream_text(_stream_text(event))
        for event in events
        if event.get("phase") == "human_response" and str(event.get("visibility") or "user") != "debug"
    }
    rows = []
    seen_human_response_texts: set[str] = set()
    for event in events:
        if event.get("visibility") == "debug" and not _debug_event_allowed_in_stream(event):
            continue
        if _is_duplicate_planner_response(event, human_response_texts):
            continue
        if _is_duplicate_human_response(event, seen_human_response_texts):
            continue
        node_id = _node_for_event(event)
        if node_id not in node_ids:
            node_id = "writeback"
        rows.append({
            "id": event["id"],
            "node_id": node_id,
            "time": event.get("created_at"),
            "level": _event_level(event),
            "text": _stream_text(event),
            "event_type": event.get("event_type"),
            "phase": event.get("phase"),
            "source": event.get("source"),
            "actor": event.get("actor"),
            "event_kind": event.get("event_kind"),
            "visibility": event.get("visibility"),
            "summary": event.get("summary"),
            "reason": event.get("reason"),
            "artifact_refs": event.get("artifact_refs") or [],
        })
    return rows[-limit:]


def _is_duplicate_planner_response(event: dict[str, Any], human_response_texts: set[str]) -> bool:
    if event.get("phase") != "llm_planner" or event.get("event_type") != "decision":
        return False
    text = _normalize_stream_text(_stream_text(event))
    return bool(text and text in human_response_texts)


def _is_duplicate_human_response(event: dict[str, Any], seen_texts: set[str]) -> bool:
    if event.get("phase") != "human_response":
        return False
    text = _normalize_stream_text(_stream_text(event))
    if not text:
        return False
    if text in seen_texts:
        return True
    seen_texts.add(text)
    return False


def _normalize_stream_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _debug_event_allowed_in_stream(event: dict[str, Any]) -> bool:
    return event.get("phase") == "llm_planner" and event.get("event_type") == "decision"


def _group_events_by_visibility(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {"user": [], "expert": [], "debug": []}
    for event in events:
        visibility = str(event.get("visibility") or "user")
        grouped.setdefault(visibility, []).append(event)
    return {key: grouped.get(key, []) for key in ("user", "expert", "debug")}


def _build_evidence(
    *,
    nodes: list[dict[str, Any]],
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
    item_limit: int,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for node in nodes:
        node_id = node["id"]
        evidence[node_id] = {
            "state_ledger": _node_state_ledger(node_id, shots, production_run),
            "brain_trace": _tail([step for step in steps if _node_for_phase(step.get("phase")) == node_id], item_limit),
            "detailed_flow": _tail(_node_detailed_flow(node_id, steps, events), item_limit),
            "raw_reads": _tail(_raw_reads_from_events(events), item_limit) if node_id == "read_context" else [],
            "tool_events": _tail([event for event in events if _node_for_event(event) == node_id], item_limit),
            "tasks": _tail([task for task in tasks if _node_for_task(task) == node_id], item_limit),
            "artifacts": _tail([artifact for artifact in artifacts if _node_for_artifact(artifact) == node_id], item_limit),
            "shots": _tail(_shots_for_node(node_id, shots), item_limit),
            "backend_links": _backend_links(node_id, production_run),
        }
    return evidence


def _build_evidence_layers(
    *,
    run: dict[str, Any],
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    ledger: dict[str, Any],
    nodes: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
    item_limit: int,
) -> dict[str, Any]:
    production_ledger = _json(run.get("production_ledger"))
    run_meta = _json(run.get("meta"))
    raw_reads = _raw_reads_from_events(events)
    detailed_flow = []
    for node in nodes:
        flows = _node_detailed_flow(node["id"], steps, events)
        for flow in flows:
            detailed_flow.append({"node_id": node["id"], "node_title": node["title"], **flow})

    terminal_events = [
        event for event in events
        if _is_terminal_event(event)
    ]
    task_terminal_rows = [
        {
            "kind": "task",
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "status": task.get("status"),
            "progress": task.get("progress"),
            "stage": task.get("stage_text"),
            "error": task.get("error_message"),
            "updated_at": task.get("updated_at"),
        }
        for task in tasks
    ]

    progress_rows = [
        {"label": "目标时长", "value": ledger.get("target_duration_sec") or ledger.get("target_total_seconds") or 0, "unit": "sec"},
        {"label": "已生成时长", "value": ledger.get("generated_duration_sec") or ledger.get("generated_video_seconds") or 0, "unit": "sec"},
        {"label": "已审核时长", "value": ledger.get("approved_duration_sec") or 0, "unit": "sec"},
        {"label": "剩余时长", "value": ledger.get("remaining_seconds") or 0, "unit": "sec"},
        {"label": "镜头总数", "value": ledger.get("shot_count") or len(shots), "unit": "shots"},
        {"label": "已选关键帧", "value": ledger.get("selected_image_count") or 0, "unit": "shots"},
        {"label": "已选视频", "value": ledger.get("selected_video_count") or 0, "unit": "shots"},
        {"label": "当前集", "value": ledger.get("current_episode") or 1, "unit": "episode"},
        {"label": "当前场", "value": ledger.get("current_scene") or 1, "unit": "scene"},
    ]

    creative = _first_dict(
        production_ledger.get("creative_technique_ledger"),
        run_meta.get("creative_technique_ledger"),
        _meta_value_from_steps(steps, "creative_technique_ledger"),
        _meta_value_from_steps(steps, "creative_lowering_audit"),
    )
    creative_audit = _first_list(
        _meta_value_from_steps(steps, "creative_lowering_audit"),
        production_ledger.get("creative_lowering_audit"),
        run_meta.get("creative_lowering_audit"),
    )
    creative_items = []
    if creative:
        creative_items.append({"kind": "ledger", "data": creative})
    creative_items.extend({"kind": "audit", "data": item} for item in creative_audit)

    return {
        "state_machine_flow": _layer(
            "state_machine_flow",
            "Commercial production state machine",
            f"{len(nodes)} node groups mapped to real production gates.",
            [
                stage
                for node in nodes
                for stage in list(node.get("flow_stages") or [])
            ],
        ),
        "agent_execution_log": _layer(
            "agent_execution_log",
            "Agent 执行日志",
            f"{len(events)} 条事件，覆盖 run 的实时执行记录。",
            events,
            item_limit=item_limit,
        ),
        "brain_trace": _layer(
            "brain_trace",
            "大脑执行轨迹",
            f"{len(steps)} 个大脑 step，记录输入、判断、输出和停止原因。",
            steps,
            item_limit=item_limit,
        ),
        "detailed_flow_ledger": _layer(
            "detailed_flow_ledger",
            "详细流程账本",
            f"{len(detailed_flow)} 条流程证据，按制作节点归档。",
            detailed_flow,
            item_limit=item_limit,
        ),
        "raw_read_list": _layer(
            "raw_read_list",
            "原始读取清单",
            f"{len(raw_reads)} 条上下文读取证据。",
            raw_reads,
            item_limit=item_limit,
        ),
        "production_stream_terminal": _layer(
            "production_stream_terminal",
            "制片流式终端",
            f"{len(terminal_events)} 条 worker/provider/ffmpeg 事件，{len(task_terminal_rows)} 个任务状态。",
            [{"kind": "event", "data": event} for event in terminal_events] + task_terminal_rows,
            item_limit=item_limit,
        ),
        "progress_ledger": _layer(
            "progress_ledger",
            "进度账本",
            f"镜头 {ledger.get('selected_video_count') or 0}/{ledger.get('shot_count') or len(shots)}，已生成 {ledger.get('generated_duration_sec') or 0}s。",
            progress_rows,
            meta={"ledger": ledger, "open_risks": ledger.get("open_risks") or []},
        ),
        "creative_technique_ledger": _layer(
            "creative_technique_ledger",
            "制作技巧账本",
            f"{len(creative_items)} 条技巧下沉证据。",
            creative_items,
            meta={"has_ledger": bool(creative), "audit_count": len(creative_audit)},
            item_limit=item_limit,
        ),
    }


def _layer(
    layer_id: str,
    title: str,
    summary: str,
    items: list[Any],
    meta: dict[str, Any] | None = None,
    item_limit: int | None = None,
) -> dict[str, Any]:
    visible_items = _tail(items, item_limit or len(items))
    return {
        "id": layer_id,
        "title": title,
        "summary": summary,
        "count": len(items),
        "items": visible_items,
        "meta": {
            **(meta or {}),
            "truncated": len(visible_items) < len(items),
            "visible_count": len(visible_items),
        },
    }


def _is_terminal_event(event: dict[str, Any]) -> bool:
    source = str(event.get("source") or "").lower()
    event_type = str(event.get("event_type") or "").lower()
    phase = str(event.get("phase") or "").lower()
    text_blob = " ".join(str(event.get(key) or "") for key in ("title", "detail", "source")).lower()
    return (
        source in {"worker", "provider", "ffmpeg", "queue", "api", "ledger"}
        or event_type in {"tool_call", "tool_result", "artifact", "writeback", "error"}
        or any(token in phase or token in text_blob for token in ("ffmpeg", "seedream", "seedance", "provider", "queue", "worker", "bgm", "subtitle"))
    )


def _meta_value_from_steps(steps: list[dict[str, Any]], key: str) -> Any:
    for step in reversed(steps):
        meta = step.get("meta") if isinstance(step.get("meta"), dict) else {}
        if key in meta:
            return meta.get(key)
    return None


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


def _build_actions(
    *,
    run: dict[str, Any],
    nodes: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    failed_video_tasks = [task for task in tasks if task.get("task_type") == "video_gen" and task.get("status") in TERMINAL_FAILED]
    has_video = any(task.get("task_type") == "video_gen" and task.get("status") in TERMINAL_DONE for task in tasks)
    run_failed = str(run.get("status") or "") in {"failed", "blocked"} or bool(failed_video_tasks)
    rows = [
        {"id": "retry_failed", "label": "重试失败视频", "enabled": bool(failed_video_tasks), "reason": "" if failed_video_tasks else "当前没有失败的视频任务"},
        {"id": "export_partial", "label": "只剪已有素材", "enabled": has_video, "reason": "" if has_video else "当前没有可剪辑视频"},
        {"id": "change_provider", "label": "换 provider", "enabled": run_failed, "reason": "" if run_failed else "当前 run 未阻断"},
        {"id": "continue_step", "label": "继续一步", "enabled": str(run.get("status") or "") not in {"running", "dispatching"}, "reason": "运行中不重复派发" if str(run.get("status") or "") in {"running", "dispatching"} else ""},
        {"id": "cancel_run", "label": "取消 run", "enabled": str(run.get("status") or "") in {"created", "queued", "running", "dispatching"}, "reason": ""},
        {"id": "open_expert_console", "label": "打开专家后台", "enabled": True, "reason": ""},
    ]
    for row in rows:
        row["capability"] = public_capability(_capability_action_id(str(row.get("id") or "")))
    return rows


def _capability_action_id(action_id: str) -> str:
    return {
        "continue_step": "status_query",
        "retry_failed": "generate_videos",
        "change_provider": "generate_videos",
        "export_partial": "plan_final_edit",
    }.get(action_id, action_id)


def _build_outputs(
    *,
    run: dict[str, Any],
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []

    for shot in shots:
        shot_index = shot.get("shot_index")
        prompt = shot.get("prompt") or ""
        selected_image = str(shot.get("selected_image") or "").strip()
        selected_video = str(shot.get("selected_video") or "").strip()
        if selected_image:
            images.append({
                "id": f"shot-{shot_index}-selected-image",
                "kind": "selected_image",
                "url": selected_image,
                "title": f"第 {shot_index} 镜参考图",
                "summary": prompt,
                "shot_index": shot_index,
                "source": "shot_rows",
            })
        for index, url in enumerate(_urls_from_value(shot.get("image_candidates")), 1):
            images.append({
                "id": f"shot-{shot_index}-image-candidate-{index}",
                "kind": "image_candidate",
                "url": url,
                "title": f"第 {shot_index} 镜候选图 {index}",
                "summary": prompt,
                "shot_index": shot_index,
                "source": "shot_rows",
            })
        if selected_video:
            videos.append({
                "id": f"shot-{shot_index}-selected-video",
                "kind": "selected_video",
                "url": selected_video,
                "title": f"第 {shot_index} 镜视频",
                "summary": prompt,
                "shot_index": shot_index,
                "source": "shot_rows",
            })
        for index, url in enumerate(_urls_from_value(shot.get("video_variants")), 1):
            videos.append({
                "id": f"shot-{shot_index}-video-variant-{index}",
                "kind": "video_variant",
                "url": url,
                "title": f"第 {shot_index} 镜候选视频 {index}",
                "summary": prompt,
                "shot_index": shot_index,
                "source": "shot_rows",
            })

    for artifact in artifacts:
        url = str(artifact.get("uri") or "").strip()
        if not url:
            continue
        artifact_type = str(artifact.get("artifact_type") or "")
        item = {
            "id": artifact.get("id"),
            "kind": artifact_type,
            "url": url,
            "title": artifact.get("summary") or artifact_type,
            "summary": artifact.get("summary") or "",
            "shot_index": (artifact.get("meta") or {}).get("shot_index") if isinstance(artifact.get("meta"), dict) else None,
            "source": "agent_artifacts",
        }
        if artifact_type in {"image", "keyframe", "reference_image"}:
            images.append(item)
        elif artifact_type in {"video", "final_video"}:
            videos.append(item)

    for task in tasks:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        task_type = str(task.get("task_type") or "")
        shot_index = payload.get("shot_index") or result.get("shot_index")
        for url in _urls_from_value(result):
            item = {
                "id": f"task-{task.get('task_id')}-{url}",
                "kind": task_type,
                "url": url,
                "title": _task_output_title(task_type, shot_index),
                "summary": str(task.get("stage_text") or ""),
                "shot_index": shot_index,
                "source": "tasks",
            }
            if "image" in task_type:
                images.append(item)
            elif "video" in task_type:
                videos.append(item)

    final_video_url = str((production_run or {}).get("final_video_url") or "").strip()
    if final_video_url:
        videos.append({
            "id": "final-video",
            "kind": "final_video",
            "url": final_video_url,
            "title": "最终成片",
            "summary": "导出完成的成片视频",
            "shot_index": None,
            "source": "video_production_runs",
        })
        videos[-1]["title"] = "最终成片"
        videos[-1]["summary"] = "导出完成的成片视频"

    return {
        "script": _script_output(steps=steps, tasks=tasks),
        "director_notes": _director_notes(events=events, steps=steps),
        "keyframe_pool": _build_keyframe_pool(shots=shots, images=_dedupe_outputs(images), tasks=tasks),
        "images": _dedupe_outputs(images),
        "videos": _dedupe_outputs(videos),
        "shots": [
            {
                "shot_index": shot.get("shot_index"),
                "prompt": shot.get("prompt") or "",
                "duration": shot.get("duration") or 0,
                "status": shot.get("status") or "",
                "selected_image": shot.get("selected_image") or "",
                "selected_video": shot.get("selected_video") or "",
                "image_candidates": shot.get("image_candidates") or [],
                "video_variants": shot.get("video_variants") or [],
                "image_review_status": _review_status(shot, "image"),
                "video_review_status": _review_status(shot, "video"),
                "last_error": shot.get("last_error") or "",
                "updated_at": shot.get("updated_at") or "",
            }
            for shot in shots
        ],
        "summary": {
            "image_count": len(_dedupe_outputs(images)),
            "video_count": len(_dedupe_outputs(videos)),
            "shot_count": len(shots),
            "final_video_url": final_video_url,
            "run_summary": run.get("summary") or "",
        },
    }


def _build_keyframe_pool(*, shots: list[dict[str, Any]], images: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_by_shot: dict[Any, int] = {}
    failed_by_shot: dict[Any, int] = {}
    for task in tasks:
        if str(task.get("task_type") or "") != "image_gen":
            continue
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        shot_index = payload.get("shot_index")
        status = str(task.get("status") or "")
        if status in ACTIVE_STATUSES:
            active_by_shot[shot_index] = active_by_shot.get(shot_index, 0) + 1
        if status in TERMINAL_FAILED:
            failed_by_shot[shot_index] = failed_by_shot.get(shot_index, 0) + 1

    image_by_shot: dict[Any, list[dict[str, Any]]] = {}
    for image in images:
        image_by_shot.setdefault(image.get("shot_index"), []).append(image)

    pools: list[dict[str, Any]] = []
    for shot in shots:
        shot_index = shot.get("shot_index")
        candidates = []
        selected_image = str(shot.get("selected_image") or "").strip()
        if selected_image:
            candidates.append(_keyframe_candidate(url=selected_image, shot_index=shot_index, selected=True, source="shot_rows", prompt=shot.get("prompt") or ""))
        for item in _candidate_values(shot.get("image_candidates")):
            candidates.append(_keyframe_candidate_from_value(item, shot_index=shot_index, selected=False, source="shot_rows", prompt=shot.get("prompt") or ""))
        for image in image_by_shot.get(shot_index, []):
            candidates.append(
                _keyframe_candidate(
                    url=str(image.get("url") or ""),
                    shot_index=shot_index,
                    selected=str(image.get("kind") or "") == "selected_image",
                    source=str(image.get("source") or "outputs"),
                    prompt=str(image.get("summary") or shot.get("prompt") or ""),
                    artifact_id=str(image.get("id") or ""),
                    provider=str(image.get("source") or ""),
                )
            )
        candidates = _dedupe_keyframe_candidates(candidates)
        pools.append(
            {
                "shot_index": shot_index,
                "prompt": shot.get("prompt") or "",
                "status": shot.get("status") or "",
                "candidates": candidates,
                "summary": {
                    "candidate_count": len(candidates),
                    "selected_count": sum(1 for item in candidates if item.get("selected")),
                    "running_count": active_by_shot.get(shot_index, 0),
                    "failed_count": failed_by_shot.get(shot_index, 0),
                },
            }
        )
    return pools


def _candidate_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def _keyframe_candidate_from_value(value: Any, *, shot_index: Any, selected: bool, source: str, prompt: str) -> dict[str, Any]:
    if isinstance(value, dict):
        review = value.get("review") if isinstance(value.get("review"), dict) else {}
        return _keyframe_candidate(
            url=str(value.get("url") or value.get("uri") or value.get("image_url") or ""),
            shot_index=value.get("shot_index", shot_index),
            selected=bool(value.get("selected")) or selected,
            source=source,
            prompt=str(value.get("prompt") or value.get("summary") or prompt),
            artifact_id=str(value.get("artifact_id") or value.get("id") or ""),
            provider=str(value.get("provider") or source),
            status=str(value.get("status") or "ready"),
            quality_score=value.get("quality_score", review.get("quality_score")),
        )
    return _keyframe_candidate(url=str(value or ""), shot_index=shot_index, selected=selected, source=source, prompt=prompt)


def _keyframe_candidate(
    *,
    url: str,
    shot_index: Any,
    selected: bool,
    source: str,
    prompt: str,
    artifact_id: str = "",
    provider: str = "",
    status: str = "ready",
    quality_score: Any = None,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "shot_index": shot_index,
        "url": url,
        "prompt": prompt,
        "provider": provider or source,
        "status": status,
        "selected": selected,
        "quality_score": quality_score,
        "source": source,
    }


def _dedupe_keyframe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for candidate in candidates:
        key = str(candidate.get("url") or candidate.get("artifact_id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _urls_from_value(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        stripped = value.strip()
        if _looks_like_url(stripped):
            urls.append(stripped)
        return urls
    if isinstance(value, list):
        for item in value:
            urls.extend(_urls_from_value(item))
        return urls
    if isinstance(value, dict):
        for key in ("url", "uri", "image_url", "video_url", "selected_image", "selected_video", "oss_url", "result_url"):
            urls.extend(_urls_from_value(value.get(key)))
    return urls


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://", "/storage/", "/static/", "storage/", "uploads/"))


def _dedupe_outputs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _task_output_title(task_type: str, shot_index: Any) -> str:
    label = "产物"
    if "image" in task_type:
        label = "参考图/关键帧"
    elif "video" in task_type:
        label = "视频"
    return f"第 {shot_index} 镜{label}" if shot_index not in (None, "") else label


def _script_output(*, steps: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_items = []
    for task in tasks:
        if str(task.get("task_type") or "") not in {"director_script", "script", "storyboard"}:
            continue
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        text_value = _first_text_value(result, ("script", "story", "content", "text", "storyboard", "summary"))
        if text_value and not _is_internal_note_text(text_value):
            task_items.append({"title": "剧本/分镜产物", "content": text_value, "source": "tasks"})
    step_items = []
    for step in steps:
        if _node_for_phase(step.get("phase")) != "plan_shots":
            continue
        text_value = step.get("output_summary") or step.get("decision_summary") or step.get("input_summary") or ""
        if text_value and not _is_internal_note_text(str(text_value)):
            step_items.append({
                "title": step.get("title") or "剧本/分镜",
                "content": text_value,
                "source": "agent_steps",
            })
    items = task_items + step_items
    return {
        "items": items,
        "content": items[-1]["content"] if items else "",
    }


def _director_notes(*, events: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notes = []
    for event in events:
        if event.get("event_type") != "decision":
            continue
        if str(event.get("source") or "") in {"queue", "worker", "ledger", "state_machine"}:
            continue
        detail = str(event.get("detail") or "").strip()
        if detail and not _is_internal_note_text(detail):
            notes.append({
                "title": event.get("title") or event.get("phase") or "导演建议",
                "content": detail,
                "source": event.get("source") or "agent_events",
                "created_at": event.get("created_at") or "",
            })
    return notes[-8:]


def _is_internal_note_text(value: str) -> bool:
    text_value = str(value or "")
    return (
        "=" in text_value
        or text_value.startswith("{")
        or text_value.startswith("[")
        or "production_run" in text_value
        or "video_task_failures" in text_value
        or "provider_waiting" in text_value
        or "selected_image" in text_value
        or "selected_video" in text_value
        or "task_id" in text_value
        or "artifact_id" in text_value
        or text_value in {"开始执行", "阶段完成", "前置完成"}
    )


def _first_text_value(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, (dict, list)):
            return json.dumps(item, ensure_ascii=False, default=str)
    return ""


def _build_ledger(*, run: dict[str, Any], shots: list[dict[str, Any]], production_run: dict[str, Any] | None) -> dict[str, Any]:
    production_ledger = _json(run.get("production_ledger"))
    target = int((production_run or {}).get("target_duration_sec") or production_ledger.get("target_duration_sec") or 0)
    generated = sum(float(shot.get("duration") or 0) for shot in shots if shot.get("selected_video"))
    return {
        **production_ledger,
        "target_duration_sec": target,
        "generated_duration_sec": round(generated, 3),
        "approved_duration_sec": production_ledger.get("approved_duration_sec", 0),
        "current_episode": _safe_int((production_run or {}).get("episode") or production_ledger.get("current_episode"), 1),
        "current_scene": _safe_int((production_run or {}).get("scene") or production_ledger.get("current_scene"), 1),
        "shot_count": len(shots),
        "selected_image_count": sum(1 for shot in shots if shot.get("selected_image")),
        "selected_video_count": sum(1 for shot in shots if shot.get("selected_video")),
        "open_risks": production_ledger.get("open_risks") or [],
        "final_video_url": (production_run or {}).get("final_video_url") or production_ledger.get("final_video_url") or "",
    }


def _node_status(
    node_id: str,
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    run: dict[str, Any],
    production_run: dict[str, Any] | None,
) -> str:
    production_status = str((production_run or {}).get("status") or "")
    if production_status == "provider_waiting" and node_id == "generate_videos":
        return "running"
    if node_id == "generate_keyframes" and any(task.get("task_type") == "image_gen" and task.get("status") in TERMINAL_DONE for task in tasks):
        if not any(task.get("task_type") == "image_gen" and task.get("status") in TERMINAL_FAILED for task in tasks):
            return "completed"
    if node_id == "generate_videos" and any(task.get("task_type") == "video_gen" and task.get("status") in TERMINAL_DONE for task in tasks):
        if not any(task.get("task_type") == "video_gen" and task.get("status") in TERMINAL_FAILED for task in tasks):
            return "completed"
    if any(_event_is_hard_failure(event) for event in events):
        return "failed"
    if any(task.get("status") in TERMINAL_FAILED and not _is_deferred_provider_task(task, production_status) for task in tasks):
        return "failed"
    if any(_event_is_blocking_risk(event) for event in events):
        return "blocked"
    if any(task.get("status") in ACTIVE_STATUSES for task in tasks):
        return "running"
    if any(event.get("status") in ACTIVE_STATUSES for event in events):
        return "running"
    if any(task.get("status") in TERMINAL_DONE for task in tasks):
        return "completed"
    if any(step.get("status") in {"done", "completed"} for step in steps):
        return "completed"
    if events:
        return "completed"
    if node_id == _node_for_phase(run.get("current_phase") or (production_run or {}).get("current_stage")):
        return "running"
    return "pending"


def _event_is_hard_failure(event: dict[str, Any]) -> bool:
    if str(event.get("status") or "") in {"deferred", "provider_waiting"}:
        return False
    detail = str(event.get("detail") or "").lower()
    if any(token in detail for token in ("saturated", "backpressure", "too many requests", "429", "rate limit")):
        return False
    return event.get("event_type") == "error" or event.get("status") == "failed"


def _event_is_blocking_risk(event: dict[str, Any]) -> bool:
    if str(event.get("status") or "") in {"deferred", "provider_waiting"}:
        return False
    return event.get("event_type") == "risk" or event.get("status") == "blocked"


def _is_deferred_provider_task(task: dict[str, Any], production_status: str) -> bool:
    if production_status != "provider_waiting":
        return False
    if str(task.get("task_type") or "") != "video_gen":
        return False
    message = str(task.get("error_message") or "").lower()
    return any(token in message for token in ("saturated", "backpressure", "too many requests", "429", "rate limit"))


def _node_summary(
    node_id: str,
    status: str,
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    production_run: dict[str, Any] | None,
) -> str:
    if node_id == "generate_keyframes":
        done = sum(1 for shot in shots if shot.get("selected_image"))
        return f"关键帧 {done}/{len(shots)}"
    if node_id == "generate_videos":
        done = sum(1 for shot in shots if shot.get("selected_video"))
        production_status = str((production_run or {}).get("status") or "")
        deferred = sum(1 for task in tasks if _is_deferred_provider_task(task, production_status))
        failed = sum(1 for task in tasks if task.get("status") in TERMINAL_FAILED and not _is_deferred_provider_task(task, production_status))
        if deferred:
            return f"视频 {done}/{len(shots)}，provider 等待 {deferred}"
        if failed:
            return f"视频 {done}/{len(shots)}，失败 {failed}"
        return f"视频 {done}/{len(shots)}"
    if node_id == "ffmpeg_export":
        url = (production_run or {}).get("final_video_url")
        return "成片已导出" if url else ("等待素材齐全" if status == "pending" else "导出中")
    problem = next((event for event in events if event.get("event_type") in {"error", "risk"} or event.get("status") in {"failed", "blocked"}), None)
    if problem:
        return problem.get("detail") or problem.get("title") or status
    latest = events[-1] if events else None
    if latest:
        return latest.get("detail") or latest.get("title") or status
    return status


def _node_progress(node_id: str, status: str, events: list[dict[str, Any]], tasks: list[dict[str, Any]], shots: list[dict[str, Any]]) -> int:
    if node_id == "generate_keyframes" and shots:
        return int(100 * sum(1 for shot in shots if shot.get("selected_image")) / len(shots))
    if node_id == "generate_videos" and shots:
        return int(100 * sum(1 for shot in shots if shot.get("selected_video")) / len(shots))
    progress_values = [int(event.get("progress") or 0) for event in events if event.get("progress") is not None]
    progress_values += [int(task.get("progress") or 0) for task in tasks if task.get("progress") is not None]
    if progress_values:
        return max(0, min(100, max(progress_values)))
    return {"pending": 0, "running": 50, "completed": 100, "failed": 100, "blocked": 100}.get(status, 0)


def _node_risks(events: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks = []
    for event in events:
        if event.get("event_type") in {"risk", "error"} or event.get("status") in {"failed", "blocked"}:
            risks.append({"source": "event", "title": event.get("title"), "detail": event.get("detail"), "meta": event.get("meta") or {}})
    for task in tasks:
        if task.get("status") in TERMINAL_FAILED:
            risks.append({"source": "task", "title": f"{task.get('task_type')}失败", "detail": task.get("error_message"), "task_id": task.get("task_id")})
    return risks


def _node_actions(node_id: str, status: str, tasks: list[dict[str, Any]], shots: list[dict[str, Any]]) -> list[str]:
    actions = []
    if node_id == "generate_videos" and any(task.get("status") in TERMINAL_FAILED for task in tasks):
        actions.extend(["retry_failed", "change_provider"])
        if any(shot.get("selected_video") for shot in shots):
            actions.append("export_partial")
    if status in {"blocked", "failed"}:
        actions.append("open_expert_console")
    return actions


def _brain_summary(steps: list[dict[str, Any]], events: list[dict[str, Any]]) -> str:
    if steps:
        latest = steps[-1]
        return latest.get("decision_summary") or latest.get("output_summary") or latest.get("input_summary") or ""
    decision = next((event for event in reversed(events) if event.get("event_type") == "decision"), None)
    return (decision or {}).get("detail") or ""


def _evidence_summary(events: list[dict[str, Any]], tasks: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> str:
    calls = sum(1 for event in events if event.get("event_type") == "tool_call")
    results = sum(1 for event in events if event.get("event_type") == "tool_result")
    failed = sum(1 for task in tasks if task.get("status") in TERMINAL_FAILED)
    parts = []
    if calls or results:
        parts.append(f"工具 {calls}/{results}")
    if tasks:
        parts.append(f"任务 {len(tasks)}")
    if failed:
        parts.append(f"失败 {failed}")
    if artifacts:
        parts.append(f"产物 {len(artifacts)}")
    return "；".join(parts)


def _node_state_ledger(node_id: str, shots: list[dict[str, Any]], production_run: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "shot_count": len(shots),
        "selected_image_count": sum(1 for shot in shots if shot.get("selected_image")),
        "selected_video_count": sum(1 for shot in shots if shot.get("selected_video")),
        "production_status": (production_run or {}).get("status"),
        "current_stage": (production_run or {}).get("current_stage"),
        "final_video_url": (production_run or {}).get("final_video_url") or "",
    }


def _node_detailed_flow(node_id: str, steps: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flows = []
    for step in steps:
        if _node_for_phase(step.get("phase")) != node_id:
            continue
        flows.append({
            "input": step.get("input_summary") or "",
            "decision": step.get("decision_summary") or "",
            "output": step.get("output_summary") or "",
            "stop": step.get("stop_reason") or "",
            "meta": step.get("meta") or {},
        })
    if flows:
        return flows
    for event in events:
        if _node_for_event(event) != node_id:
            continue
        meta = event.get("meta") or {}
        if any(key in meta for key in ("input", "decision", "output", "stop")):
            flows.append({
                "input": meta.get("input") or "",
                "decision": meta.get("decision") or "",
                "output": meta.get("output") or "",
                "stop": meta.get("stop") or "",
                "meta": meta,
            })
    return flows


def _raw_reads_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reads = []
    for event in events:
        meta = event.get("meta") or {}
        raw = meta.get("raw_reads") or meta.get("read_files")
        if isinstance(raw, list):
            reads.extend(item for item in raw if isinstance(item, dict))
    return reads


def _shots_for_node(node_id: str, shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if node_id in {"generate_keyframes", "generate_videos", "lock_visual_assets", "ffmpeg_export", "quality_check"}:
        return shots
    return []


def _backend_links(node_id: str, production_run: dict[str, Any] | None) -> list[dict[str, str]]:
    project_id = (production_run or {}).get("project_id") or ""
    links = [{"label": "专家后台", "href": f"/director/produce/{project_id}"}] if project_id else []
    anchors = {
        "lock_visual_assets": "visual-assets",
        "generate_keyframes": "shot-cards",
        "generate_videos": "shot-cards",
        "ffmpeg_export": "final-cut",
        "read_context": "raw-reads",
    }
    anchor = anchors.get(node_id)
    if project_id and anchor:
        links.append({"label": "后台定位", "href": f"/director/produce/{project_id}#{anchor}"})
    return links


def _node_for_event(event: dict[str, Any]) -> str:
    return _node_for_phase(event.get("phase")) or _node_for_tool_event(event)


def _node_for_phase(phase: Any) -> str:
    return NODE_ID_BY_PHASE.get(str(phase or "").strip(), "")


def _node_for_tool_event(event: dict[str, Any]) -> str:
    text_blob = " ".join(str(event.get(key) or "") for key in ("title", "detail", "source", "event_type")).lower()
    if "seedream" in text_blob or "selected_image" in text_blob:
        return "generate_keyframes"
    if "seedance" in text_blob or "kling" in text_blob or "selected_video" in text_blob or "video_gen" in text_blob:
        return "generate_videos"
    if "ffmpeg" in text_blob or "subtitle" in text_blob or "bgm" in text_blob:
        return "ffmpeg_export"
    return "writeback"


def _node_for_task(task: dict[str, Any]) -> str:
    task_type = str(task.get("task_type") or "")
    if task_type == "image_gen":
        return "generate_keyframes"
    if task_type == "video_gen":
        return "generate_videos"
    if task_type in {"tts_gen", "director_tts"}:
        return "audio_subtitles"
    if "export" in task_type or "final_cut" in task_type:
        return "ffmpeg_export"
    if task_type == "video_production_run":
        return _node_for_phase(task.get("stage_text")) or "read_context"
    return "writeback"


def _node_for_artifact(artifact: dict[str, Any]) -> str:
    artifact_type = str(artifact.get("artifact_type") or "")
    if artifact_type in {"image", "keyframe"}:
        return "generate_keyframes"
    if artifact_type == "video":
        return "generate_videos"
    if artifact_type in {"final_video", "edit_strategy", "edit_plan"}:
        return "ffmpeg_export"
    return "writeback"


def _event_level(event: dict[str, Any]) -> str:
    if event.get("event_type") == "error" or event.get("status") == "failed":
        return "error"
    if event.get("event_type") == "risk" or event.get("status") == "blocked":
        return "warning"
    if event.get("event_type") in {"artifact", "writeback"}:
        return "success"
    return "info"


def _stream_text(event: dict[str, Any]) -> str:
    summary = str(event.get("summary") or "").strip()
    if summary:
        return summary
    title = str(event.get("title") or event.get("phase") or "执行事件")
    detail = str(event.get("detail") or "").strip()
    return f"{title}：{detail}" if detail else title


def _estimate_refunded_credits(tasks: list[dict[str, Any]]) -> int:
    # v1 没有稳定的 task -> transaction_id 反向索引。先用 failed task reserved
    # 估算可退/已退风险金额，后续接 credit transaction linkage 后精确化。
    return sum(int(task.get("credits_reserved") or 0) for task in tasks if task.get("status") in TERMINAL_FAILED)


def _event(row: Any) -> dict[str, Any]:
    meta = _json(row.get("meta"))
    agent_event = normalize_agent_event(
        source=row.get("source"),
        event_type=row.get("event_type"),
        title=row.get("title"),
        detail=row.get("detail"),
        meta=meta,
    )
    return {
        "id": str(row["id"]),
        "type": "execution_event",
        "run_id": str(row["run_id"]) if row.get("run_id") else None,
        "project_id": row.get("project_id"),
        "task_id": str(row["task_id"]) if row.get("task_id") else None,
        "step_id": str(row["step_id"]) if row.get("step_id") else None,
        "user_id": row.get("user_id"),
        "source": row.get("source"),
        "event_type": row.get("event_type"),
        "phase": row.get("phase"),
        "title": row.get("title"),
        "detail": row.get("detail"),
        "status": row.get("status"),
        "progress": row.get("progress"),
        "meta": meta,
        **agent_event,
        "created_at": _iso(row.get("created_at")),
    }


def _task(row: Any) -> dict[str, Any]:
    return {
        "task_id": str(row["task_id"]),
        "project_id": row.get("project_id"),
        "run_id": str(row["run_id"]) if row.get("run_id") else None,
        "user_id": row.get("user_id"),
        "task_type": row.get("task_type"),
        "status": row.get("status"),
        "progress": row.get("progress"),
        "stage_text": row.get("stage_text") or "",
        "error_message": row.get("error_message") or "",
        "credits_reserved": int(row.get("credits_reserved") or 0),
        "credits_charged": int(row.get("credits_charged") or 0),
        "credit_transaction_id": row.get("credit_transaction_id") or "",
        "payload": _json(row.get("payload")),
        "result": _json(row.get("result")),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "completed_at": _iso(row.get("completed_at")),
    }


def _step(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "run_id": str(row["run_id"]),
        "step_index": row.get("step_index"),
        "phase": row.get("phase"),
        "title": row.get("title"),
        "status": row.get("status"),
        "input_summary": row.get("input_summary") or "",
        "decision_summary": row.get("decision_summary") or "",
        "output_summary": row.get("output_summary") or "",
        "stop_reason": row.get("stop_reason") or "",
        "meta": _json(row.get("meta")),
        "started_at": _iso(row.get("started_at")),
        "ended_at": _iso(row.get("ended_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _artifact(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "run_id": str(row["run_id"]) if row.get("run_id") else None,
        "project_id": row.get("project_id"),
        "task_id": str(row["task_id"]) if row.get("task_id") else None,
        "user_id": row.get("user_id"),
        "artifact_type": row.get("artifact_type"),
        "uri": row.get("uri") or "",
        "summary": row.get("summary") or "",
        "meta": _json(row.get("meta")),
        "created_at": _iso(row.get("created_at")),
    }


def _shot(row: Any) -> dict[str, Any]:
    shot = {
        "shot_index": row.get("shot_index"),
        "prompt": row.get("prompt") or "",
        "duration": float(row.get("duration") or 0),
        "status": row.get("status") or "",
        "selected_image": row.get("selected_image") or "",
        "selected_video": row.get("selected_video") or "",
        "image_candidates": _json(row.get("image_candidates_json"), []),
        "video_variants": _json(row.get("video_variants_json"), []),
        "last_error": row.get("last_error") or "",
        "updated_at": _iso(row.get("updated_at")),
    }
    shot["image_review_status"] = _review_status(shot, "image")
    shot["video_review_status"] = _review_status(shot, "video")
    return shot


def _review_status(shot: dict[str, Any], media_type: str) -> str:
    list_key = "image_candidates" if media_type == "image" else "video_variants"
    selected_key = "selected_image" if media_type == "image" else "selected_video"
    selected_url = str(shot.get(selected_key) or "").strip()
    candidates = shot.get(list_key) if isinstance(shot.get(list_key), list) else []
    fallback_status = ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        status = str(candidate.get("review_status") or candidate.get("status") or review.get("status") or "").strip().lower()
        if not status:
            continue
        url = str(
            candidate.get("url")
            or candidate.get("uri")
            or candidate.get("image_url")
            or candidate.get("video_url")
            or ""
        ).strip()
        if selected_url and url == selected_url:
            return status
        fallback_status = fallback_status or status
    return fallback_status


def _json(value: Any, default: Any | None = None) -> Any:
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return default
        return parsed if isinstance(parsed, (dict, list)) else default
    return default


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed.replace(tzinfo=None)
    return None
