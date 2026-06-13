import logging

import pytest

from app.services import task_submission

pytestmark = pytest.mark.asyncio


class _FakeSession:
    def __init__(self, executed: list[dict]):
        self.executed = executed

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return self

    async def execute(self, _statement, params):
        self.executed.append(params)


class _FakeSessionLocal:
    def __init__(self, executed: list[dict]):
        self.executed = executed

    def __call__(self):
        return _FakeSession(self.executed)


async def test_batch_reserve_failure_refunds_already_reserved(monkeypatch):
    refunded: list[str] = []

    async def reserve_func(_user_id, _operation, _quantity):
        if reserve_func.calls == 0:
            reserve_func.calls += 1
            return "tx-1"
        raise RuntimeError("reserve failed")

    reserve_func.calls = 0

    async def refund(transaction_ids, *, reason):
        refunded.extend(transaction_ids)

    monkeypatch.setattr(task_submission, "_refund_reserved_credits", refund)

    with pytest.raises(RuntimeError, match="reserve failed"):
        await task_submission.submit_batch_tasks(
            user_id=1,
            operation="image_gen",
            unit_price=12,
            task_type="image_gen",
            celery_task_name="app.tasks.image_tasks.generate_image_task",
            queue="image",
            priority=3,
            items=[{"prompt": "a"}, {"prompt": "b"}],
            reserve_func=reserve_func,
        )

    assert refunded == ["tx-1"]


async def test_batch_dispatch_failure_refunds_only_not_dispatched(monkeypatch, caplog):
    executed: list[dict] = []
    sent: list[tuple] = []
    refunded: list[str] = []
    marked_failed: list[str] = []

    async def reserve_func(_user_id, _operation, _quantity):
        tx = f"tx-{reserve_func.calls}"
        reserve_func.calls += 1
        return tx

    reserve_func.calls = 0

    async def refund(transaction_ids, *, reason):
        refunded.extend(transaction_ids)

    def send_task(*args, **kwargs):
        sent.append((args, kwargs))
        if len(sent) == 2:
            raise RuntimeError("broker down")

    async def mark_failed(task_ids, _message):
        marked_failed.extend(task_ids)

    monkeypatch.setattr(task_submission, "AsyncSessionLocal", _FakeSessionLocal(executed))
    monkeypatch.setattr(task_submission.celery_app, "send_task", send_task)
    monkeypatch.setattr(task_submission, "_refund_reserved_credits", refund)
    monkeypatch.setattr(task_submission, "_mark_tasks_failed", mark_failed)

    caplog.set_level(logging.ERROR, logger="app.services.task_submission")
    with pytest.raises(RuntimeError, match="broker down"):
        await task_submission.submit_batch_tasks(
            user_id=1,
            operation="image_gen",
            unit_price=12,
            task_type="image_gen",
            celery_task_name="app.tasks.image_tasks.generate_image_task",
            queue="image",
            priority=3,
            items=[{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}],
            reserve_func=reserve_func,
        )

    assert len(executed) == 3
    assert len(sent) == 2
    assert refunded == ["tx-1", "tx-2"]
    assert marked_failed == [executed[1]["task_id"], executed[2]["task_id"]]
    assert "task_type=image_gen" in caplog.text
    assert "pending_transaction_ids=['tx-1', 'tx-2']" in caplog.text


async def test_single_dispatch_failure_refunds_and_marks_task_failed(monkeypatch, caplog):
    executed: list[dict] = []
    refunded: list[str] = []
    marked_failed: list[str] = []

    async def reserve_func(_user_id, _operation, _quantity):
        return "tx-single"

    async def refund(transaction_ids, *, reason):
        refunded.extend(transaction_ids)

    def send_task(*_args, **_kwargs):
        raise RuntimeError("broker down")

    async def mark_failed(task_ids, _message):
        marked_failed.extend(task_ids)

    monkeypatch.setattr(task_submission, "AsyncSessionLocal", _FakeSessionLocal(executed))
    monkeypatch.setattr(task_submission.celery_app, "send_task", send_task)
    monkeypatch.setattr(task_submission, "_refund_reserved_credits", refund)
    monkeypatch.setattr(task_submission, "_mark_tasks_failed", mark_failed)

    caplog.set_level(logging.ERROR, logger="app.services.task_submission")
    with pytest.raises(RuntimeError, match="broker down"):
        await task_submission.submit_single_task(
            user_id=1,
            operation="tts_synthesis",
            unit_price=1,
            task_type="tts",
            celery_task_name="app.tasks.tts_tasks.generate_tts_task",
            queue="text",
            priority=3,
            payload={"text": "hello"},
            reserve_func=reserve_func,
        )

    assert len(executed) == 1
    assert refunded == ["tx-single"]
    assert marked_failed == [executed[0]["task_id"]]
    assert "task_type=tts" in caplog.text
    assert "transaction_id=tx-single" in caplog.text
