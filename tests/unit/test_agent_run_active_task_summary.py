from datetime import datetime, timezone

import pytest

from app.routes.agent_runs import _active_run_task_summary, _normalize_active_task


def test_normalize_active_task_extracts_user_readable_context():
    row = {
        "task_id": "task-a",
        "task_type": "video_gen",
        "status": "running",
        "progress": 48,
        "stage_text": "Seedance 图生视频",
        "payload": {"video_provider": "seedance", "shot_index": 3},
        "created_at": datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 20, 8, 1, tzinfo=timezone.utc),
    }

    assert _normalize_active_task(row) == {
        "task_id": "task-a",
        "task_type": "video_gen",
        "status": "running",
        "progress": 48,
        "stage_text": "Seedance 图生视频",
        "provider": "seedance",
        "shot_index": 3,
        "created_at": "2026-05-20T08:00:00+00:00",
        "updated_at": "2026-05-20T08:01:00+00:00",
    }


@pytest.mark.asyncio
async def test_active_run_task_summary_returns_items_without_breaking_legacy_fields():
    class _Rows:
        def all(self):
            return [
                {
                    "task_id": "task-a",
                    "task_type": "image_gen",
                    "status": "provider_waiting",
                    "progress": 30,
                    "stage_text": "Calling Seedream",
                    "payload": {"provider": "seedream", "shot_index": 1},
                    "created_at": None,
                    "updated_at": None,
                }
            ]

    class _Result:
        def mappings(self):
            return _Rows()

    class _Db:
        async def execute(self, query, params):
            assert "task_type" in str(query)
            assert params["run_id"] == "run-1"
            return _Result()

    summary = await _active_run_task_summary(_Db(), run_id="run-1", user_id=7)

    assert summary["count"] == 1
    assert summary["task_ids"] == ["task-a"]
    assert summary["statuses"] == ["provider_waiting"]
    assert summary["items"][0]["task_type"] == "image_gen"
    assert summary["items"][0]["provider"] == "seedream"
    assert summary["items"][0]["progress"] == 30
