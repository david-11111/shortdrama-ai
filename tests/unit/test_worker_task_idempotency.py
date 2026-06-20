from app.tasks import image_tasks, video_tasks
import pytest
import sys
from types import SimpleNamespace


def test_joy_echo_official_runner_prefers_http_api_when_configured(monkeypatch):
    from app.services import comfy_video, joy_echo_official

    calls = []

    monkeypatch.setattr(
        joy_echo_official,
        "get_settings",
        lambda: SimpleNamespace(
            joy_echo_api_base_url="https://joy.example.test",
            joy_echo_api_key="joy-key",
        ),
    )
    monkeypatch.setattr(
        comfy_video,
        "generate_comfy_video",
        lambda payload, **kwargs: calls.append((dict(payload), dict(kwargs))) or {
            "url": "/api/media/local/ltx/joy.mp4",
            "provider": "joy_echo_api",
        },
    )

    result = joy_echo_official.generate_joy_echo_official_video(
        {"provider": "joy-echo", "prompt": "p", "duration": 30},
    )

    assert result["provider"] == "joy_echo_api"
    assert calls[0][0]["prompt"] == "p"
    assert calls[0][1]["provider"] == "joy-echo"


def test_image_worker_returns_when_idempotency_lock_is_held(monkeypatch):
    calls = []

    monkeypatch.setattr(image_tasks, "get_task_snapshot", lambda _task_id: None)
    monkeypatch.setattr(image_tasks, "acquire_task_lock", lambda _task_id: False)
    monkeypatch.setattr(image_tasks, "release_task_lock", lambda _task_id: calls.append("release"))
    monkeypatch.setattr(image_tasks, "publish_progress", lambda *args, **kwargs: calls.append("progress"))

    result = image_tasks.generate_image_task.run("task-1", "7", {"prompt": "x"})

    assert result == {"status": "duplicate", "task_id": "task-1"}
    assert calls == []


def test_video_worker_returns_when_idempotency_lock_is_held(monkeypatch):
    calls = []

    monkeypatch.setattr(video_tasks, "get_task_snapshot", lambda _task_id: None)
    monkeypatch.setattr(video_tasks, "acquire_task_lock", lambda _task_id: False)
    monkeypatch.setattr(video_tasks, "release_task_lock", lambda _task_id: calls.append("release"))
    monkeypatch.setattr(video_tasks, "publish_progress", lambda *args, **kwargs: calls.append("progress"))

    result = video_tasks.generate_video_task.run("task-1", "7", {"prompt": "x"})

    assert result == {"status": "duplicate", "task_id": "task-1"}
    assert calls == []


def test_video_worker_retry_keeps_original_task_arguments(monkeypatch):
    class RetrySentinel(Exception):
        pass

    retry_kwargs = {}

    def fake_retry(*args, **kwargs):
        retry_kwargs.update(kwargs)
        raise RetrySentinel()

    def failing_video(*args, **kwargs):
        raise RuntimeError("temporary provider failure")

    monkeypatch.setattr(video_tasks, "get_task_snapshot", lambda _task_id: {"run_id": "00000000-0000-0000-0000-000000000001"})
    monkeypatch.setattr(video_tasks, "acquire_task_lock", lambda _task_id: True)
    monkeypatch.setattr(video_tasks, "release_task_lock", lambda _task_id: None)
    monkeypatch.setattr(video_tasks, "publish_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_task_agent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "assert_agent_run_entrypoint_for_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "adapt_provider_payload", lambda payload, **kwargs: payload)
    monkeypatch.setattr(video_tasks, "reflect_before_retry", lambda *args, **kwargs: ("retry", kwargs["payload"]))
    monkeypatch.setattr(video_tasks, "build_retry_delay", lambda _retries: 1)
    monkeypatch.setattr(
        video_tasks,
        "classify_exception",
        lambda _exc: SimpleNamespace(
            retryable=True,
            category=SimpleNamespace(value="provider"),
            report_to_key_pool=False,
            dead_letter=False,
        ),
    )
    monkeypatch.setattr(video_tasks.generate_video_task, "retry", fake_retry)

    from app.services import comfy_video

    monkeypatch.setattr(comfy_video, "generate_comfy_video", failing_video)

    with pytest.raises(RetrySentinel):
        video_tasks.generate_video_task.run("task-1", "7", {"provider": "ltx2.3"}, transaction_id="tx-1")

    assert retry_kwargs["args"] == ("task-1", "7", {"provider": "ltx2.3"})
    assert retry_kwargs["kwargs"] == {"transaction_id": "tx-1"}


def test_video_worker_routes_joy_echo_to_official_runner(monkeypatch):
    calls = []

    def fake_router(payload):
        calls.append(dict(payload))
        return {"url": "/api/media/local/ltx/joy.mp4", "provider": "joy-echo"}

    monkeypatch.setattr(video_tasks, "router_dispatch", fake_router)
    monkeypatch.setattr(video_tasks, "get_task_snapshot", lambda _task_id: {"run_id": "00000000-0000-0000-0000-000000000001"})
    monkeypatch.setattr(video_tasks, "acquire_task_lock", lambda _task_id: True)
    monkeypatch.setattr(video_tasks, "release_task_lock", lambda _task_id: None)
    monkeypatch.setattr(video_tasks, "publish_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_task_agent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "assert_agent_run_entrypoint_for_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "adapt_provider_payload", lambda payload, **kwargs: payload)
    monkeypatch.setattr(video_tasks, "maybe_charge", lambda _transaction_id: None)
    monkeypatch.setattr(video_tasks, "_writeback_video", lambda *args, **kwargs: None)

    result = video_tasks.generate_video_task.run(
        "task-joy",
        "7",
        {"provider": "joy-echo", "prompt": "p", "duration": 30},
    )

    # router_dispatch 被正确调用
    assert len(calls) == 1
    assert calls[0].get("provider") == "joy-echo"
    assert calls[0].get("prompt") == "p"


def test_video_worker_strips_ltx23_reference_images(monkeypatch):
    calls = []

    def fake_router(payload):
        calls.append(dict(payload))
        return {"url": "/api/media/local/ltx/shot.mp4", "provider": "ltx2.3"}

    monkeypatch.setattr(video_tasks, "router_dispatch", fake_router)
    monkeypatch.setattr(video_tasks, "get_task_snapshot", lambda _task_id: {"run_id": "00000000-0000-0000-0000-000000000001"})
    monkeypatch.setattr(video_tasks, "acquire_task_lock", lambda _task_id: True)
    monkeypatch.setattr(video_tasks, "release_task_lock", lambda _task_id: None)
    monkeypatch.setattr(video_tasks, "publish_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_task_agent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "assert_agent_run_entrypoint_for_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "adapt_provider_payload", lambda payload, **kwargs: payload)
    monkeypatch.setattr(video_tasks, "maybe_charge", lambda _transaction_id: None)
    monkeypatch.setattr(video_tasks, "_writeback_video", lambda *args, **kwargs: None)

    result = video_tasks.generate_video_task.run(
        "task-ltx",
        "7",
        {
            "provider": "ltx2.3",
            "prompt": "p",
            "duration": 5,
            "image_url": "https://cdn.test/keyframe.png",
            "ref_images": ["https://cdn.test/ref.png"],
        },
    )

    # text_only provider → image_url 和 ref_images 在 video_tasks.py 中被 pop
    # router_dispatch 收到 payload 时它们已被移除
    assert "image_url" not in calls[0]
    assert "ref_images" not in calls[0]


def test_video_worker_uses_shot_row_user_id_for_writeback(monkeypatch):
    calls = []

    async def fake_update_shot_media(project_id, shot_index, user_id, **kwargs):
        calls.append(
            {
                "project_id": project_id,
                "shot_index": shot_index,
                "user_id": user_id,
                "video_url": kwargs["video_url"],
                "status": kwargs["status"],
            }
        )

    def fake_router(payload):
        return {"url": "/api/media/local/ltx/shot.mp4", "provider": "ltx2.3"}

    monkeypatch.setattr(video_tasks, "router_dispatch", fake_router)
    monkeypatch.setattr(video_tasks, "get_task_snapshot", lambda _task_id: {"run_id": "00000000-0000-0000-0000-000000000001"})
    monkeypatch.setattr(video_tasks, "acquire_task_lock", lambda _task_id: True)
    monkeypatch.setattr(video_tasks, "release_task_lock", lambda _task_id: None)
    monkeypatch.setattr(video_tasks, "publish_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_task_agent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "assert_agent_run_entrypoint_for_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "adapt_provider_payload", lambda payload, **kwargs: payload)
    monkeypatch.setattr(video_tasks, "maybe_charge", lambda _transaction_id: None)
    monkeypatch.setattr(video_tasks, "update_shot_media", fake_update_shot_media)

    video_tasks.generate_video_task.run(
        "task-ltx",
        "0",
        {
            "provider": "ltx2.3",
            "prompt": "p",
            "shot_row": {
                "project_id": "project-1",
                "user_id": 7,
                "shot_index": 2,
                "prompt": "p",
            },
        },
    )

    assert calls == [
        {
            "project_id": "project-1",
            "shot_index": 2,
            "user_id": "7",
            "video_url": "/api/media/local/ltx/shot.mp4",
            "status": "video_done",
        }
    ]


def test_image_worker_writes_shot_error_after_provider_failure(monkeypatch):
    calls = []

    async def fake_update_shot_error(project_id, shot_index, user_id, error, *, status, preserve_selected_video=False):
        calls.append(
            {
                "project_id": project_id,
                "shot_index": shot_index,
                "user_id": user_id,
                "error": error,
                "status": status,
                "preserve_selected_video": preserve_selected_video,
            }
        )

    def failing_seedream(*args, **kwargs):
        raise RuntimeError("Seedream request failed with status=403: AccountOverdueError")

    monkeypatch.setattr(image_tasks, "get_task_snapshot", lambda _task_id: {"run_id": "00000000-0000-0000-0000-000000000001"})
    monkeypatch.setattr(image_tasks, "acquire_task_lock", lambda _task_id: True)
    monkeypatch.setattr(image_tasks, "release_task_lock", lambda _task_id: calls.append({"release": _task_id}))
    monkeypatch.setattr(image_tasks, "publish_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(image_tasks, "publish_task_agent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(image_tasks, "assert_agent_run_entrypoint_for_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(image_tasks, "build_image_generation_payload", lambda *args, **kwargs: {"prompt": "p"})
    monkeypatch.setattr(image_tasks, "adapt_provider_payload", lambda payload, **kwargs: payload)
    monkeypatch.setattr(image_tasks.key_pool, "acquire", lambda _service: ("seedream-main", "api-key"))
    monkeypatch.setattr(image_tasks.key_pool, "release", lambda _key_name: None)
    monkeypatch.setattr(image_tasks.key_pool, "report_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(image_tasks, "resolve_callable", lambda *args, **kwargs: failing_seedream)
    monkeypatch.setattr(image_tasks, "maybe_refund", lambda _transaction_id: 12)
    monkeypatch.setattr(image_tasks, "publish_failed", lambda *args, **kwargs: calls.append({"failed": True}))
    monkeypatch.setattr(image_tasks, "update_shot_error", fake_update_shot_error, raising=False)

    payload = {
        "prompt": "p",
        "shot_row": {
            "project_id": "project-1",
            "shot_index": 3,
            "selected_image": "https://cdn.test/old.png",
        },
    }

    with pytest.raises(RuntimeError, match="AccountOverdueError"):
        image_tasks.generate_image_task.run("task-1", "7", payload, "tx-1")

    assert {
        "project_id": "project-1",
        "shot_index": 3,
        "user_id": "7",
        "error": "Seedream request failed with status=403: AccountOverdueError",
        "status": "image_done",
        "preserve_selected_video": False,
    } in calls


def test_video_worker_preserves_existing_video_status_after_failure(monkeypatch):
    calls = []

    async def fake_update_shot_error(project_id, shot_index, user_id, error, *, status, preserve_selected_video=False):
        calls.append(
            {
                "project_id": project_id,
                "shot_index": shot_index,
                "user_id": user_id,
                "error": error,
                "status": status,
                "preserve_selected_video": preserve_selected_video,
            }
        )

    def failing_video(*args, **kwargs):
        raise RuntimeError("LTX failed after another task already wrote video")

    monkeypatch.setattr(video_tasks, "get_task_snapshot", lambda _task_id: {"run_id": "00000000-0000-0000-0000-000000000001"})
    monkeypatch.setattr(video_tasks, "acquire_task_lock", lambda _task_id: True)
    monkeypatch.setattr(video_tasks, "release_task_lock", lambda _task_id: None)
    monkeypatch.setattr(video_tasks, "publish_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "publish_task_agent_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "assert_agent_run_entrypoint_for_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "adapt_provider_payload", lambda payload, **kwargs: payload)
    monkeypatch.setattr(video_tasks, "maybe_refund", lambda _transaction_id: 10)
    monkeypatch.setattr(video_tasks, "publish_failed", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_tasks, "update_shot_error", fake_update_shot_error)
    monkeypatch.setattr(
        video_tasks,
        "classify_exception",
        lambda _exc: SimpleNamespace(
            retryable=False,
            category=SimpleNamespace(value="provider"),
            report_to_key_pool=False,
            dead_letter=True,
        ),
    )

    from app.services import comfy_video

    monkeypatch.setattr(comfy_video, "generate_comfy_video", failing_video)

    payload = {
        "provider": "ltx2.3",
        "prompt": "p",
        "shot_row": {
            "project_id": "project-1",
            "user_id": 7,
            "shot_index": 2,
            "selected_image": "https://cdn.test/keyframe.png",
        },
    }

    with pytest.raises(RuntimeError, match="LTX failed"):
        video_tasks.generate_video_task.run("task-video", "0", payload, "tx-1")

    assert calls == [
        {
            "project_id": "project-1",
            "shot_index": 2,
            "user_id": "7",
            "error": "LTX failed after another task already wrote video",
            "status": "image_done",
            "preserve_selected_video": True,
        }
    ]
