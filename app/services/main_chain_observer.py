from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runtime import publish_agent_event
from app.services.agent_runtime_contracts import (
    ExpectedArtifact,
    ObservationSignal,
    expected_artifacts_for_action,
)


async def observe_task_writeback(db: AsyncSession, task_id: str) -> list[dict[str, Any]]:
    row = (
        await db.execute(
            text(
                """
                SELECT task_id::text AS task_id, run_id::text AS run_id, project_id,
                       user_id, task_type, status, result
                FROM tasks
                WHERE task_id = CAST(:task_id AS UUID)
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
    ).mappings().first()
    if not row:
        return []

    task = dict(row)
    shots = (
        await db.execute(
            text(
                """
                SELECT shot_index, selected_image, selected_video,
                       image_candidates_json, video_variants_json
                FROM shot_rows
                WHERE project_id = :project_id
                  AND user_id = :user_id
                ORDER BY shot_index ASC
                """
            ),
            {"project_id": task["project_id"], "user_id": task["user_id"]},
        )
    ).mappings().all()

    shot_rows = [dict(shot) for shot in shots]
    db_artifacts = await _load_db_artifacts(db, task=task, shots=shot_rows)
    signals = [
        *expected_write_signals(task=task, shots=shot_rows),
        *verify_expected_artifacts(
            run_id=str(task.get("run_id") or ""),
            task_id=task_id,
            action=_action_for_task_type(str(task.get("task_type") or "")),
            provider_artifacts=_provider_artifacts_from_task(task),
            db_artifacts=db_artifacts,
        ),
    ]
    signals = _dedupe_signals(signals)
    for signal in signals:
        await publish_agent_event(
            db,
            run_id=str(task.get("run_id") or ""),
            project_id=str(task.get("project_id") or ""),
            user_id=int(task.get("user_id") or 0),
            task_id=task_id,
            source="main_chain_observer",
            event_type="observation",
            phase=signal.type.lower(),
            title=signal.type,
            detail=signal.summary,
            status=signal.severity,
            progress=None,
            meta={"observation_signal": signal.as_dict()},
            event_kind="observation",
            visibility="expert",
            summary=signal.summary,
            reason=signal.suggested_recovery,
        )
    return [signal.as_dict() for signal in signals]


def expected_write_signals(*, task: dict[str, Any], shots: list[dict[str, Any]]) -> list[ObservationSignal]:
    if str(task.get("status") or "") not in {"done", "completed"}:
        return []
    task_type = str(task.get("task_type") or "")
    if task_type == "image_gen":
        return _missing_media_write_signal(task=task, shots=shots, field="selected_image", stage_id="generate_keyframes")
    if task_type == "video_gen":
        return _missing_media_write_signal(task=task, shots=shots, field="selected_video", stage_id="generate_videos")
    return []


def verify_expected_artifacts(
    *,
    run_id: str,
    task_id: str,
    action: str,
    provider_artifacts: list[dict[str, Any]],
    db_artifacts: list[dict[str, Any]],
    expected: list[ExpectedArtifact] | None = None,
) -> list[ObservationSignal]:
    expected_items = list(expected if expected is not None else expected_artifacts_for_action(action))
    provider_types = {str(item.get("artifact_type") or "") for item in provider_artifacts}
    db_types = {str(item.get("artifact_type") or "") for item in db_artifacts}
    signals: list[ObservationSignal] = []

    for item in expected_items:
        if not item.required:
            continue

        provider_has = item.artifact_type in provider_types
        db_has = item.artifact_type in db_types
        evidence = [
            {
                "kind": "artifact",
                "artifact_type": item.artifact_type,
                "write_target": item.write_target,
            }
        ]

        if provider_has and not db_has:
            signals.append(
                ObservationSignal(
                    type="WRITEBACK_FAILED",
                    severity="error",
                    source="artifact_verification",
                    run_id=run_id,
                    task_id=task_id,
                    stage_id=action,
                    summary=f"Provider returned {item.artifact_type} but DB writeback is missing.",
                    evidence_refs=evidence,
                    suggested_recovery="repair_writeback",
                )
            )
        elif not provider_has and not db_has:
            signals.append(
                ObservationSignal(
                    type="MISSING_ARTIFACT",
                    severity="error",
                    source="artifact_verification",
                    run_id=run_id,
                    task_id=task_id,
                    stage_id=action,
                    summary=f"Required artifact {item.artifact_type} is missing.",
                    evidence_refs=evidence,
                    suggested_recovery="retry_with_artifact_check",
                )
            )

    return signals


async def _load_db_artifacts(
    db: AsyncSession,
    *,
    task: dict[str, Any],
    shots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if any(str(shot.get("selected_image") or "").strip() for shot in shots):
        artifacts.append({"artifact_type": "selected_image", "ref": "shot_rows:selected_image"})
    if any(_has_json_items(shot.get("image_candidates_json")) for shot in shots):
        artifacts.append({"artifact_type": "image_candidate_metadata", "ref": "shot_rows:image_candidates_json"})
    if any(str(shot.get("selected_video") or "").strip() for shot in shots):
        artifacts.append({"artifact_type": "selected_video", "ref": "shot_rows:selected_video"})
    if any(_has_json_items(shot.get("video_variants_json")) for shot in shots):
        artifacts.append({"artifact_type": "video_variant_metadata", "ref": "shot_rows:video_variants_json"})

    artifact_rows = (
        await db.execute(
            text(
                """
                SELECT artifact_type, uri, meta
                FROM agent_artifacts
                WHERE task_id = CAST(:task_id AS UUID)
                   OR (
                        task_id IS NULL
                    AND run_id = CAST(:run_id AS UUID)
                    AND project_id = :project_id
                    AND user_id = :user_id
                   )
                """
            ),
            {
                "task_id": str(task.get("task_id") or ""),
                "run_id": str(task.get("run_id") or ""),
                "project_id": task.get("project_id"),
                "user_id": task.get("user_id"),
            },
        )
    ).mappings().all()
    for row in artifact_rows:
        artifacts.extend(_db_artifacts_from_agent_artifact(dict(row)))

    event_rows = (
        await db.execute(
            text(
                """
                SELECT id::text AS id, event_type, phase, meta
                FROM agent_events
                WHERE task_id = CAST(:task_id AS UUID)
                  AND (
                        event_type = 'writeback'
                     OR phase LIKE 'writeback_%'
                     OR meta->'agent_event'->>'event_kind' = 'writeback'
                  )
                """
            ),
            {"task_id": str(task.get("task_id") or "")},
        )
    ).mappings().all()
    for row in event_rows:
        artifacts.append({"artifact_type": "provider_writeback_event", "ref": f"agent_events:{row['id']}"})

    return _dedupe_artifacts(artifacts)


def _provider_artifacts_from_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    task_type = str(task.get("task_type") or "")
    artifacts: list[dict[str, Any]] = []

    image_url = _first_text(result.get("image_url"), result.get("asset_url"), result.get("url"))
    video_url = _first_text(result.get("video_url"), result.get("asset_url"), result.get("url"))
    if task_type == "image_gen" and image_url:
        artifacts.append({"artifact_type": "selected_image", "ref": image_url})
    if task_type == "video_gen" and video_url:
        artifacts.append({"artifact_type": "selected_video", "ref": video_url})
    if isinstance(result.get("image_candidate"), dict) or isinstance(result.get("image_metadata"), dict):
        artifacts.append({"artifact_type": "image_candidate_metadata", "ref": "task.result:image_metadata"})
    if isinstance(result.get("video_candidate"), dict) or isinstance(result.get("video_metadata"), dict):
        artifacts.append({"artifact_type": "video_variant_metadata", "ref": "task.result:video_metadata"})
    if result.get("thumbnail_url"):
        artifacts.append({"artifact_type": "thumbnail", "ref": str(result["thumbnail_url"])})
    if str(result.get("final_video_url") or "").strip():
        artifacts.append({"artifact_type": "final_video_asset", "ref": str(result["final_video_url"])})
    if isinstance(result.get("delivery_metadata"), dict):
        artifacts.append({"artifact_type": "delivery_metadata", "ref": "task.result:delivery_metadata"})
    if result:
        artifacts.append({"artifact_type": "final_task_result_link", "ref": "tasks.result"})
    return _dedupe_artifacts(artifacts)


def _db_artifacts_from_agent_artifact(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw_type = str(row.get("artifact_type") or "")
    uri = str(row.get("uri") or "")
    mapped = {
        "image_metadata": "image_candidate_metadata",
        "image_candidate_metadata": "image_candidate_metadata",
        "video_metadata": "video_variant_metadata",
        "video_variant_metadata": "video_variant_metadata",
        "thumbnail": "thumbnail",
        "final_video": "final_video_asset",
        "final_video_asset": "final_video_asset",
        "delivery_metadata": "delivery_metadata",
    }.get(raw_type, raw_type)
    return [{"artifact_type": mapped, "ref": uri or raw_type}] if mapped else []


def _action_for_task_type(task_type: str) -> str:
    if task_type == "image_gen":
        return "generate_keyframes"
    if task_type == "video_gen":
        return "generate_videos"
    if task_type in {"export_final", "final_edit"}:
        return "export_final"
    return task_type


def _dedupe_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for artifact in artifacts:
        key = (str(artifact.get("artifact_type") or ""), str(artifact.get("ref") or ""))
        if key[0] and key not in seen:
            seen.add(key)
            deduped.append(artifact)
    return deduped


def _dedupe_signals(signals: list[ObservationSignal]) -> list[ObservationSignal]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[ObservationSignal] = []
    for signal in signals:
        artifact_type = ""
        if signal.evidence_refs:
            artifact_type = str(signal.evidence_refs[0].get("artifact_type") or signal.evidence_refs[0].get("field") or "")
        key = (signal.type, signal.stage_id, artifact_type)
        if key not in seen:
            seen.add(key)
            deduped.append(signal)
    return deduped


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _has_json_items(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _missing_media_write_signal(
    *,
    task: dict[str, Any],
    shots: list[dict[str, Any]],
    field: str,
    stage_id: str,
) -> list[ObservationSignal]:
    if any(str(shot.get(field) or "").strip() for shot in shots):
        return []
    task_id = str(task.get("task_id") or "")
    return [
        ObservationSignal(
            type="WRITEBACK_FAILED",
            severity="error",
            source="writeback_status",
            run_id=str(task.get("run_id") or ""),
            task_id=task_id,
            stage_id=stage_id,
            summary=f"Task completed but {field} was not written back.",
            evidence_refs=[
                {"kind": "shot_row", "field": field},
                {"kind": "task", "id": task_id},
            ],
            suggested_recovery="repair_writeback",
            raw={"task_type": task.get("task_type"), "result": task.get("result")},
        )
    ]
