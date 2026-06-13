import pytest

from app.services.production_entrypoint import (
    ProductionEntrypointValidationError,
    assert_agent_run_entrypoint_for_task,
    direct_generation_block_detail,
)


def test_provider_task_without_agent_run_is_rejected():
    with pytest.raises(ProductionEntrypointValidationError, match="/director/agent-run"):
        assert_agent_run_entrypoint_for_task("image_gen", {}, db_run_id=None)


def test_provider_task_with_agent_run_is_allowed():
    assert_agent_run_entrypoint_for_task(
        "video_gen",
        {"run_id": "11111111-1111-1111-1111-111111111111"},
        db_run_id=None,
    )


def test_db_run_id_allows_agent_run_dispatched_task():
    assert_agent_run_entrypoint_for_task(
        "image_gen",
        {},
        db_run_id="22222222-2222-2222-2222-222222222222",
    )


def test_direct_generation_block_detail_names_only_entrypoint():
    detail = direct_generation_block_detail("video_gen")

    assert detail["allowed_entrypoint"] == "/director/agent-run"
    assert detail["api_entrypoint"] == "POST /api/agent-runs"
    assert detail["task_type"] == "video_gen"
