import json

import pytest

from app.tasks import _shared


def test_worker_agent_event_payload_is_canonical_execution_event():
    event = _shared._build_task_agent_event(
        "task-1",
        "tool_result",
        {"tool": "seedream", "progress": 80, "asset_url": "https://example.test/a.png"},
        {
            "run_id": "run-1",
            "project_id": "project-1",
            "user_id": 7,
            "task_type": "image_gen",
        },
    )

    assert event["type"] == "execution_event"
    assert event["run_id"] == "run-1"
    assert event["project_id"] == "project-1"
    assert event["task_id"] == "task-1"
    assert event["source"] == "provider"
    assert event["event_type"] == "tool_result"
    assert event["phase"] == "seedream_result"
    assert event["title"] == "\u5de5\u5177\u8fd4\u56de\uff1aSeedream \u51fa\u56fe"
    assert event["detail"] == "tool returned"
    assert event["status"] == "done"
    assert event["progress"] == 80
    assert event["meta"]["task_type"] == "image_gen"
    assert event["meta"]["tool"] == "seedream"
    assert event["meta"]["asset_url"] == "https://example.test/a.png"
    assert event["actor"] == "seedream"
    assert event["event_kind"] == "tool_result"
    assert event["visibility"] == "user"
    assert event["summary"] == "Seedream \u51fa\u56fe 返回结果"
    assert event["artifact_refs"] == [{"kind": "asset_url", "uri": "https://example.test/a.png"}]
    assert event["debug"]["raw"]["tool"] == "seedream"
    assert event["meta"]["agent_event"]["actor"] == "seedream"
    assert event["meta"]["agent_event"]["event_kind"] == "tool_result"


@pytest.mark.asyncio
async def test_worker_agent_event_publishes_to_project_channel(monkeypatch):
    published: list[tuple[str, str]] = []

    class FakeRedis:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def publish(self, channel: str, payload: str):
            published.append((channel, payload))

    class FakeRedisFactory:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return FakeRedis()

    monkeypatch.setattr(_shared.aioredis, "Redis", FakeRedisFactory)

    event = {
        "type": "execution_event",
        "project_id": "project-1",
        "event_type": "writeback",
        "phase": "writeback_selected_image",
        "title": "done",
        "detail": "selected_image updated",
        "status": "done",
        "meta": {"field": "selected_image"},
    }

    await _shared._publish_agent_event_to_channel("project-1", event)

    assert len(published) == 1
    channel, payload = published[0]
    assert channel == "project:project-1:events"
    assert json.loads(payload) == event


@pytest.mark.asyncio
async def test_worker_agent_event_persists_canonical_columns(monkeypatch):
    executed: list[dict] = []

    class FakeResult:
        def fetchone(self):
            return type("Row", (), {"id": 11, "created_at": None})()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def begin(self):
            return self

        async def execute(self, _statement, params):
            executed.append(params)
            return FakeResult()

    class FakeSessionLocal:
        def __call__(self):
            return FakeSession()

    monkeypatch.setattr(_shared, "AsyncSessionLocal", FakeSessionLocal())

    result = await _shared._persist_agent_event(
        {
            "run_id": None,
            "project_id": "project-1",
            "task_id": None,
            "user_id": 7,
            "source": "worker",
            "event_type": "tool_call",
            "phase": "seedream_requesting",
            "title": "calling",
            "detail": "requesting image",
            "status": "running",
            "progress": 10,
            "meta": {"task_type": "image_gen"},
        }
    )

    assert result == {"id": "11", "created_at": None}
    assert executed[0]["run_id"] is None
    assert executed[0]["project_id"] == "project-1"
    assert executed[0]["event_type"] == "tool_call"
    meta = json.loads(executed[0]["meta"])
    assert meta["task_type"] == "image_gen"
    assert meta["agent_event"]["actor"] == "executor"
    assert meta["agent_event"]["event_kind"] == "tool_call"
    assert meta["agent_event"]["summary"] == "calling"
