import pytest

from app.services.agent_runtime_contracts import ExpectedArtifact
from app.services.main_chain_observer import expected_write_signals, observe_task_writeback, verify_expected_artifacts


def test_image_task_done_without_selected_image_emits_writeback_failed():
    signals = expected_write_signals(
        task={
            "task_id": "task-1",
            "run_id": "run-1",
            "task_type": "image_gen",
            "status": "done",
            "result": {"image_url": "https://cdn.example.com/a.jpg"},
        },
        shots=[{"shot_index": 1, "selected_image": "", "selected_video": ""}],
    )

    assert len(signals) == 1
    assert signals[0].type == "WRITEBACK_FAILED"
    assert signals[0].suggested_recovery == "repair_writeback"


def test_image_task_done_with_selected_image_has_no_writeback_signal():
    signals = expected_write_signals(
        task={
            "task_id": "task-1",
            "run_id": "run-1",
            "task_type": "image_gen",
            "status": "done",
            "result": {"image_url": "https://cdn.example.com/a.jpg"},
        },
        shots=[{"shot_index": 1, "selected_image": "https://cdn.example.com/a.jpg", "selected_video": ""}],
    )

    assert signals == []


def test_image_task_done_checks_matching_shot_index():
    signals = expected_write_signals(
        task={
            "task_id": "task-1",
            "run_id": "run-1",
            "task_type": "image_gen",
            "status": "done",
            "payload": {"shot_index": 2},
            "result": {"image_url": "https://cdn.example.com/b.jpg"},
        },
        shots=[
            {"shot_index": 1, "selected_image": "https://cdn.example.com/a.jpg", "selected_video": ""},
            {"shot_index": 2, "selected_image": "", "selected_video": ""},
        ],
    )

    assert len(signals) == 1
    assert signals[0].evidence_refs[0]["shot_index"] == 2


def test_video_task_done_without_selected_video_emits_writeback_failed():
    signals = expected_write_signals(
        task={
            "task_id": "task-2",
            "run_id": "run-1",
            "task_type": "video_gen",
            "status": "done",
            "result": {"video_url": "https://cdn.example.com/v.mp4"},
        },
        shots=[{"shot_index": 1, "selected_image": "https://cdn.example.com/a.jpg", "selected_video": ""}],
    )

    assert signals[0].type == "WRITEBACK_FAILED"
    assert signals[0].evidence_refs[0]["field"] == "selected_video"


def test_video_task_done_checks_matching_shot_index():
    signals = expected_write_signals(
        task={
            "task_id": "task-2",
            "run_id": "run-1",
            "task_type": "video_gen",
            "status": "done",
            "payload": {"shot_row": {"shot_index": 2}},
            "result": {"video_url": "https://cdn.example.com/v2.mp4"},
        },
        shots=[
            {"shot_index": 1, "selected_image": "https://cdn.example.com/a.jpg", "selected_video": "https://cdn.example.com/v1.mp4"},
            {"shot_index": 2, "selected_image": "https://cdn.example.com/b.jpg", "selected_video": ""},
        ],
    )

    assert len(signals) == 1
    assert signals[0].evidence_refs[0]["shot_index"] == 2


def test_video_task_missing_required_thumbnail_metadata_emits_missing_artifact():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-2",
        action="generate_videos",
        provider_artifacts=[
            {"artifact_type": "selected_video", "ref": "https://cdn.example.com/v.mp4"},
        ],
        db_artifacts=[
            {"artifact_type": "selected_video", "ref": "shot_rows:1:selected_video"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
    )

    assert [signal.type for signal in signals] == ["MISSING_ARTIFACT"]
    assert signals[0].evidence_refs[0]["artifact_type"] == "video_variant_metadata"


def test_video_task_missing_optional_thumbnail_does_not_block_completion():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-2",
        action="generate_videos",
        provider_artifacts=[
            {"artifact_type": "selected_video", "ref": "https://cdn.example.com/v.mp4"},
            {"artifact_type": "video_variant_metadata", "ref": "agent_artifacts:video-meta-1"},
        ],
        db_artifacts=[
            {"artifact_type": "selected_video", "ref": "shot_rows:1:selected_video"},
            {"artifact_type": "video_variant_metadata", "ref": "agent_artifacts:video-meta-1"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
    )

    assert signals == []


def test_provider_artifact_present_but_db_write_missing_emits_writeback_failed():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-1",
        action="generate_keyframes",
        provider_artifacts=[
            {"artifact_type": "selected_image", "ref": "https://cdn.example.com/a.jpg"},
            {"artifact_type": "image_candidate_metadata", "ref": "agent_artifacts:image-meta-1"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
        db_artifacts=[
            {"artifact_type": "image_candidate_metadata", "ref": "agent_artifacts:image-meta-1"},
            {"artifact_type": "provider_writeback_event", "ref": "agent_events:event-1"},
        ],
    )

    assert signals[0].type == "WRITEBACK_FAILED"
    assert signals[0].suggested_recovery == "repair_writeback"


def test_explicit_artifact_expectations_can_override_defaults():
    signals = verify_expected_artifacts(
        run_id="run-1",
        task_id="task-custom",
        action="custom_action",
        provider_artifacts=[],
        db_artifacts=[],
        expected=[
            ExpectedArtifact(
                artifact_type="custom_json",
                write_target={"table": "agent_artifacts", "kind": "custom_json"},
                required=True,
            )
        ],
    )

    assert signals[0].type == "MISSING_ARTIFACT"
    assert signals[0].evidence_refs[0]["artifact_type"] == "custom_json"


@pytest.mark.asyncio
async def test_observe_task_writeback_accepts_shot_row_image_candidate_metadata(monkeypatch):
    published = []

    async def fake_publish_agent_event(*args, **kwargs):
        published.append(kwargs)

    monkeypatch.setattr("app.services.main_chain_observer.publish_agent_event", fake_publish_agent_event)

    task_id = "11111111-1111-1111-1111-111111111111"
    db = FakeDb(
        [
            [
                {
                    "task_id": task_id,
                    "run_id": "22222222-2222-2222-2222-222222222222",
                    "project_id": "project-1",
                    "user_id": 7,
                    "task_type": "image_gen",
                    "status": "done",
                    "payload": {"shot_index": 1},
                    "result": {"image_url": "https://cdn.example.com/a.jpg"},
                }
            ],
            [
                {
                    "shot_index": 1,
                    "selected_image": "https://cdn.example.com/a.jpg",
                    "selected_video": "",
                    "image_candidates_json": [{"url": "https://cdn.example.com/a.jpg"}],
                    "video_variants_json": [],
                }
            ],
            [],
            [{"id": "event-1", "event_type": "writeback", "phase": "writeback_selected_image", "meta": {}}],
        ]
    )

    signals = await observe_task_writeback(db, task_id)

    assert signals == []
    assert published == []


@pytest.mark.asyncio
async def test_observe_task_writeback_runs_artifact_verification(monkeypatch):
    published = []

    async def fake_publish_agent_event(*args, **kwargs):
        published.append(kwargs)

    monkeypatch.setattr("app.services.main_chain_observer.publish_agent_event", fake_publish_agent_event)

    task_id = "11111111-1111-1111-1111-111111111111"
    db = FakeDb(
        [
            [
                {
                    "task_id": task_id,
                    "run_id": "22222222-2222-2222-2222-222222222222",
                    "project_id": "project-1",
                    "user_id": 7,
                    "task_type": "video_gen",
                    "status": "done",
                    "payload": {"shot_index": 1},
                    "result": {"video_url": "https://cdn.example.com/v.mp4"},
                }
            ],
            [{"shot_index": 1, "selected_image": "https://cdn.example.com/a.jpg", "selected_video": "https://cdn.example.com/v.mp4"}],
            [],
            [],
        ]
    )

    signals = await observe_task_writeback(db, task_id)

    assert any(signal["type"] == "MISSING_ARTIFACT" for signal in signals)
    assert any(
        event["source"] == "main_chain_observer"
        and event["meta"]["observation_signal"]["type"] == "MISSING_ARTIFACT"
        for event in published
    )


@pytest.mark.asyncio
async def test_observe_task_writeback_checks_current_video_shot(monkeypatch):
    published = []

    async def fake_publish_agent_event(*args, **kwargs):
        published.append(kwargs)

    monkeypatch.setattr("app.services.main_chain_observer.publish_agent_event", fake_publish_agent_event)

    task_id = "11111111-1111-1111-1111-111111111111"
    db = FakeDb(
        [
            [
                {
                    "task_id": task_id,
                    "run_id": "22222222-2222-2222-2222-222222222222",
                    "project_id": "project-1",
                    "user_id": 7,
                    "task_type": "video_gen",
                    "status": "done",
                    "payload": {"shot_row": {"shot_index": 2}},
                    "result": {"video_url": "https://cdn.example.com/v2.mp4"},
                }
            ],
            [
                {
                    "shot_index": 1,
                    "selected_image": "https://cdn.example.com/a.jpg",
                    "selected_video": "https://cdn.example.com/v1.mp4",
                    "image_candidates_json": [],
                    "video_variants_json": [{"url": "https://cdn.example.com/v1.mp4"}],
                },
                {
                    "shot_index": 2,
                    "selected_image": "https://cdn.example.com/b.jpg",
                    "selected_video": "",
                    "image_candidates_json": [],
                    "video_variants_json": [],
                },
            ],
            [],
            [{"id": "event-1", "event_type": "writeback", "phase": "writeback_selected_video", "meta": {}}],
        ]
    )

    signals = await observe_task_writeback(db, task_id)

    assert any(signal["type"] == "WRITEBACK_FAILED" for signal in signals)
    assert any(
        event["meta"]["observation_signal"]["type"] == "WRITEBACK_FAILED"
        for event in published
    )


class FakeDb:
    def __init__(self, rows_by_execute):
        self.rows_by_execute = list(rows_by_execute)

    async def execute(self, *args, **kwargs):
        return FakeResult(self.rows_by_execute.pop(0))


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows
