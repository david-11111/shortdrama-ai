from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services import main_chain_observer
from app.services.main_chain_controller import MainChainContext, MainChainResult, apply_decision_packet
from app.services.run_coordination import (
    DecisionTickResult,
    observe_task_terminal_decision_tick,
    task_run_context_for_main_chain,
    load_run_facts_from_snapshot,
)


async def continue_main_chain_after_task(task_id: str) -> dict[str, Any] | None:
    decision_dict = await observe_task_terminal_decision_tick(task_id)
    if not isinstance(decision_dict, dict):
        return None

    # LLM-enhanced tick: optionally enrich the decision with DeepSeek analysis
    llm_suggestion = await _maybe_llm_suggest_tick(task_id)
    if llm_suggestion:
        from app.services.llm_coordination import merge_llm_suggestion
        decision_dict = merge_llm_suggestion(decision_dict, llm_suggestion)

    async with AsyncSessionLocal() as session:
        context_row = await task_run_context_for_main_chain(session, task_id)
        if not context_row:
            return None
        packet = _packet_from_dict(decision_dict)
        await main_chain_observer.observe_task_writeback(session, task_id)

        # ---- Visual consistency check (triggered after image-gen tasks) ----
        task_type = await _get_task_type(session, task_id)
        if task_type == "image_gen":
            try:
                from app.services.agent_run_snapshot import get_agent_run_snapshot
                from app.services.visual_consistency_checker import check_all
                from app.services.agent_runtime import publish_agent_event

                run_id = str(context_row["run_id"])
                user_id = int(context_row["user_id"])
                project_id = str(context_row["project_id"])

                snapshot = await get_agent_run_snapshot(
                    session, run_id=run_id, user_id=user_id,
                )
                if snapshot:
                    outputs = snapshot.get("outputs") or {}
                    shots = list(outputs.get("shots") or [])
                    signals = check_all(shots)
                    for signal in signals:
                        await publish_agent_event(
                            session,
                            run_id=run_id,
                            project_id=project_id,
                            user_id=user_id,
                            task_id=task_id,
                            source=signal.source,
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
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Visual consistency check failed (non-blocking): %s", exc,
                )
        # ---- End visual consistency check ----

        result = await apply_decision_packet(
            session,
            packet=packet,
            context=MainChainContext(
                project_id=str(context_row["project_id"]),
                user_id=int(context_row["user_id"]),
                user_tier=str(context_row.get("user_tier") or "free"),
                run_id=str(context_row["run_id"]),
                run_mode=str(context_row.get("run_mode") or "autopilot"),
            ),
            handlers=_build_handlers(
                session,
                project_id=str(context_row["project_id"]),
                user_id=int(context_row["user_id"]),
                user_tier=str(context_row.get("user_tier") or "free"),
                run_id=str(context_row["run_id"]),
                run_mode=str(context_row.get("run_mode") or "autopilot"),
            ),
        )
        await session.commit()
        return {"status": result.status, "dispatched": result.dispatched, "decision": result.decision}


async def _maybe_llm_suggest_tick(task_id: str) -> dict[str, Any] | None:
    """Try LLM-enhanced tick enrichment; returns None on any failure."""
    try:
        from app.services.llm_coordination import llm_suggest_tick
        async with AsyncSessionLocal() as session:
            context_row = await task_run_context_for_main_chain(session, task_id)
            if not context_row:
                return None
            run_id = str(context_row["run_id"])
            user_id = int(context_row["user_id"])
            facts = await load_run_facts_from_snapshot(session, run_id=run_id, user_id=user_id)
            if not facts:
                return None
            return await llm_suggest_tick(facts)
    except Exception:
        return None


def _packet_from_dict(data: dict[str, Any]) -> DecisionTickResult:
    return DecisionTickResult(**data)


def _build_handlers(session: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        from app.services.main_chain_handlers import build_main_chain_handlers
    except ImportError:
        return {}
    return build_main_chain_handlers(session, **kwargs)


async def _get_task_type(session: AsyncSessionLocal, task_id: str) -> str:
    """Return the ``task_type`` for a given task ID, or empty string."""
    try:
        row = (
            await session.execute(
                text(
                    "SELECT task_type FROM tasks WHERE task_id = CAST(:task_id AS UUID) LIMIT 1"
                ),
                {"task_id": task_id},
            )
        ).mappings().first()
        return str(row["task_type"]) if row else ""
    except Exception:
        return ""
