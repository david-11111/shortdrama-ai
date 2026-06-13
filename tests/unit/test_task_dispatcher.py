from types import SimpleNamespace

import pytest

from app.services import task_dispatcher
from app.services.task_dispatcher import TaskSpec

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


async def test_dispatch_task_applies_guards_and_delegates_submission(monkeypatch):
    observed = {"concurrent": False, "rate": False, "cost": False, "submission": None}
    db = object()
    payload = {"project_id": "p1", "message": "hello"}
    spec = TaskSpec(
        "director_chat",
        "app.tasks.director_tasks.director_chat_task",
        "text",
        "llm_director_chat",
        "llm_chat",
    )

    async def check_concurrent_limit(user_id, user_tier, passed_db):
        observed["concurrent"] = user_id == 7 and user_tier == "pro" and passed_db is db

    async def check_rate_limit(user_id, user_tier, resource, passed_db):
        observed["rate"] = user_id == 7 and user_tier == "pro" and resource == "llm_chat" and passed_db is db

    async def get_price(operation):
        assert operation == "llm_director_chat"
        return 17

    async def assert_cost_guard(passed_db, *, user_id, credits_to_reserve):
        observed["cost"] = passed_db is db and user_id == 7 and credits_to_reserve == 17

    async def submit_single_task(**kwargs):
        observed["submission"] = kwargs
        return SimpleNamespace(task_id="task-1", credits_reserved=17)

    monkeypatch.setattr(task_dispatcher, "check_concurrent_limit", check_concurrent_limit)
    monkeypatch.setattr(task_dispatcher, "check_rate_limit", check_rate_limit)
    monkeypatch.setattr(task_dispatcher.credit_service, "get_price", get_price)
    monkeypatch.setattr(task_dispatcher, "assert_cost_guard", assert_cost_guard)
    monkeypatch.setattr(task_dispatcher, "submit_single_task", submit_single_task)

    result = await task_dispatcher.dispatch_task(db, spec=spec, payload=payload, user_id=7, user_tier="pro")

    assert result == {"task_id": "task-1", "status": "queued", "credits_reserved": 17, "queue": "text"}
    assert observed["concurrent"]
    assert observed["rate"]
    assert observed["cost"]
    assert observed["submission"] == {
        "user_id": 7,
        "operation": "llm_director_chat",
        "unit_price": 17,
        "task_type": "director_chat",
        "celery_task_name": "app.tasks.director_tasks.director_chat_task",
        "queue": "text",
        "priority": 3,
        "payload": payload,
    }


async def test_dispatch_task_propagates_submission_failure(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    async def get_price(_operation):
        return 20

    async def submit_single_task(**_kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr(task_dispatcher, "check_concurrent_limit", noop)
    monkeypatch.setattr(task_dispatcher, "check_rate_limit", noop)
    monkeypatch.setattr(task_dispatcher.credit_service, "get_price", get_price)
    monkeypatch.setattr(task_dispatcher, "assert_cost_guard", noop)
    monkeypatch.setattr(task_dispatcher, "submit_single_task", submit_single_task)

    with pytest.raises(RuntimeError, match="broker down"):
        await task_dispatcher.dispatch_task(
            object(),
            spec=TaskSpec("director_produce", "app.tasks.director_tasks.director_produce_task", "default", "video_gen_5s"),
            payload={"project_id": "p1"},
            user_id=7,
            user_tier="enterprise",
        )
