import pytest

from app.tasks import _shared


@pytest.mark.asyncio
async def test_terminal_publish_observes_coordination_before_finalization(monkeypatch):
    calls = []

    async def fake_persist():
        calls.append("persist")

    async def fake_publish(task_id, payload):
        calls.append(("publish", task_id, payload["type"]))

    async def fake_publish_agent(task_id, payload):
        calls.append(("agent_event", task_id, payload["type"]))

    async def fake_drain(task_id):
        calls.append(("drain", task_id))

    async def fake_observe(task_id):
        calls.append(("coordination", task_id))

    async def fake_finalize(task_id):
        calls.append(("finalize", task_id))

    async def fake_apply(task_id):
        calls.append(("main_chain", task_id))
        return {"status": "waiting", "dispatched": False}

    monkeypatch.setattr(_shared, "_publish_async", fake_publish)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", fake_publish_agent)
    monkeypatch.setattr(_shared, "_drain_pending_instruction", fake_drain)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", fake_observe)
    monkeypatch.setattr(_shared, "_apply_main_chain_after_task", fake_apply)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)

    await _shared._persist_and_publish(fake_persist(), "task-1", {"type": "task_complete"})

    assert calls == [
        "persist",
        ("publish", "task-1", "task_complete"),
        ("agent_event", "task-1", "task_complete"),
        ("drain", "task-1"),
        ("coordination", "task-1"),
        ("main_chain", "task-1"),
        ("finalize", "task-1"),
    ]


@pytest.mark.asyncio
async def test_failed_publish_observes_coordination_before_finalization(monkeypatch):
    calls = []

    async def fake_persist_failed(
        task_id,
        *,
        error,
        retry_count,
        status,
        celery_task_id,
    ):
        calls.append(("persist_failed", task_id, error, retry_count, status, celery_task_id))

    async def fake_publish(task_id, payload):
        calls.append(("publish", task_id, payload["type"]))

    async def fake_publish_agent(task_id, payload):
        calls.append(("agent_event", task_id, payload["type"]))

    async def fake_drain(task_id):
        calls.append(("drain", task_id))

    async def fake_observe(task_id):
        calls.append(("coordination", task_id))

    async def fake_finalize(task_id):
        calls.append(("finalize", task_id))

    async def fake_apply(task_id):
        calls.append(("main_chain", task_id))
        return {"status": "waiting", "dispatched": False}

    monkeypatch.setattr(_shared, "_persist_failed", fake_persist_failed)
    monkeypatch.setattr(_shared, "_publish_async", fake_publish)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", fake_publish_agent)
    monkeypatch.setattr(_shared, "_drain_pending_instruction", fake_drain)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", fake_observe)
    monkeypatch.setattr(_shared, "_apply_main_chain_after_task", fake_apply)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)

    await _shared._persist_failed_and_publish(
        "task-1",
        {"type": "task_failed"},
        error="failed",
        retry_count=2,
        status="failed",
        celery_task_id="celery-1",
        dead_letter=False,
    )

    assert calls == [
        ("persist_failed", "task-1", "failed", 2, "failed", "celery-1"),
        ("publish", "task-1", "task_failed"),
        ("agent_event", "task-1", "task_failed"),
        ("drain", "task-1"),
        ("coordination", "task-1"),
        ("main_chain", "task-1"),
        ("finalize", "task-1"),
    ]


@pytest.mark.asyncio
async def test_terminal_hook_applies_main_chain_controller(monkeypatch):
    observed = {"controller": False}

    async def fake_drain(task_id):
        return None

    async def fake_observe(task_id):
        return {"status": "execute", "action": "generate_keyframes"}

    async def fake_apply(task_id):
        observed["controller"] = True
        return {"status": "dispatched", "dispatched": True}

    async def fake_finalize(task_id):
        return None

    async def fake_publish(task_id, payload):
        return None

    async def fake_publish_agent(task_id, payload):
        return None

    monkeypatch.setattr(_shared, "_drain_pending_instruction", fake_drain)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", fake_observe)
    monkeypatch.setattr(_shared, "_apply_main_chain_after_task", fake_apply, raising=False)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)
    monkeypatch.setattr(_shared, "_publish_async", fake_publish)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", fake_publish_agent)

    async def persisted():
        return None

    await _shared._persist_and_publish(
        persisted(),
        "11111111-1111-1111-1111-111111111111",
        {"type": "task_complete"},
    )

    assert observed["controller"] is True


@pytest.mark.asyncio
async def test_maybe_finalize_run_skips_when_main_chain_dispatched(monkeypatch):
    observed = {"finalize": False}

    async def fake_drain(task_id):
        return None

    async def fake_observe(task_id):
        return None

    async def fake_apply(task_id):
        return {"status": "dispatched", "dispatched": True}

    async def fake_finalize(task_id):
        observed["finalize"] = True

    async def fake_publish(task_id, payload):
        return None

    async def fake_publish_agent(task_id, payload):
        return None

    monkeypatch.setattr(_shared, "_drain_pending_instruction", fake_drain)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", fake_observe)
    monkeypatch.setattr(_shared, "_apply_main_chain_after_task", fake_apply)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)
    monkeypatch.setattr(_shared, "_publish_async", fake_publish)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", fake_publish_agent)

    async def persisted():
        return None

    await _shared._persist_and_publish(
        persisted(),
        "11111111-1111-1111-1111-111111111111",
        {"type": "task_complete"},
    )

    assert observed["finalize"] is False


@pytest.mark.asyncio
async def test_maybe_finalize_run_skips_when_main_chain_continuation_failed(monkeypatch):
    observed = {"finalize": False}

    async def fake_drain(task_id):
        return None

    async def fake_observe(task_id):
        return {"status": "execute", "action": "generate_videos"}

    async def fake_apply(task_id):
        return {"status": "failed", "dispatched": False, "continuation_failed": True}

    async def fake_finalize(task_id):
        observed["finalize"] = True

    async def fake_publish(task_id, payload):
        return None

    async def fake_publish_agent(task_id, payload):
        return None

    monkeypatch.setattr(_shared, "_drain_pending_instruction", fake_drain)
    monkeypatch.setattr(_shared, "_observe_run_coordination_after_task", fake_observe)
    monkeypatch.setattr(_shared, "_apply_main_chain_after_task", fake_apply)
    monkeypatch.setattr(_shared, "_maybe_finalize_run", fake_finalize)
    monkeypatch.setattr(_shared, "_publish_async", fake_publish)
    monkeypatch.setattr(_shared, "_publish_agent_task_event", fake_publish_agent)

    async def persisted():
        return None

    await _shared._persist_and_publish(
        persisted(),
        "11111111-1111-1111-1111-111111111111",
        {"type": "task_complete"},
    )

    assert observed["finalize"] is False
