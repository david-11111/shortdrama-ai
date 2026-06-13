from __future__ import annotations

from typing import Any


AGENT_RUN_UI_ENTRYPOINT = "/director/agent-run"
AGENT_RUN_API_ENTRYPOINT = "POST /api/agent-runs"
AGENT_RUN_ENTRYPOINT = "agent_run"

PROVIDER_TASK_TYPES = {
    "image_gen",
    "video_gen",
    "final_edit",
    "video_production_run",
}


class ProductionEntrypointValidationError(RuntimeError):
    """Raised when production work attempts to bypass Agent Run."""


def direct_generation_block_detail(task_type: str) -> dict[str, Any]:
    return {
        "error": "agent_run_entrypoint_required",
        "message": "Production generation must enter through /director/agent-run.",
        "allowed_entrypoint": AGENT_RUN_UI_ENTRYPOINT,
        "api_entrypoint": AGENT_RUN_API_ENTRYPOINT,
        "task_type": task_type,
    }


def assert_agent_run_entrypoint_for_task(
    task_type: str,
    payload: dict[str, Any] | None,
    *,
    db_run_id: str | None = None,
) -> None:
    if task_type not in PROVIDER_TASK_TYPES:
        return

    payload = payload or {}
    run_id = (
        db_run_id
        or payload.get("run_id")
        or payload.get("_chain_run_id")
        or payload.get("agent_run_id")
    )
    if str(run_id or "").strip():
        return

    raise ProductionEntrypointValidationError(
        f"{task_type} rejected: production generation must enter through "
        f"{AGENT_RUN_UI_ENTRYPOINT} ({AGENT_RUN_API_ENTRYPOINT})"
    )
