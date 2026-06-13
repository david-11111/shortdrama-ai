import pytest


pytestmark = [pytest.mark.unit]


class _FakeMappings:
    def first(self):
        return None


class _FakeResult:
    def mappings(self):
        return _FakeMappings()


class _FakeBegin:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def begin(self):
        return _FakeBegin()

    async def execute(self, *_args, **_kwargs):
        return _FakeResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSessionLocal:
    def __call__(self):
        return _FakeSession()


async def test_preview_export_records_final_video_asset(monkeypatch):
    from app.tasks import director_tasks

    recorded = []

    async def fake_upsert(session, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(director_tasks, "AsyncSessionLocal", _FakeSessionLocal())
    monkeypatch.setattr(director_tasks, "upsert_final_video_asset", fake_upsert)

    await director_tasks._record_director_export_result(
        project_id="project-1",
        user_id=4,
        task_id="56b09d8c-6928-4671-9e25-98a4912e8c2b",
        output={
            "final_url": "/api/director/final-video/56b09d8c-6928-4671-9e25-98a4912e8c2b",
            "storage_mode": "local_file",
            "oss_key": None,
            "clip_count": 8,
            "file_size": 123,
            "duration_sec": 36.3,
            "delivery_report": {"passed": True},
            "export_kind": "preview",
            "final_video_asset": {
                "storage_mode": "local_file",
                "file_path": "storage/final_videos/project-1/56b09d8c-6928-4671-9e25-98a4912e8c2b.mp4",
                "file_url": "/api/director/final-video/56b09d8c-6928-4671-9e25-98a4912e8c2b",
                "file_size": 123,
                "content_type": "video/mp4",
            },
        },
        preview=True,
        payload={},
    )

    assert recorded
    assert recorded[0]["task_id"] == "56b09d8c-6928-4671-9e25-98a4912e8c2b"
    assert recorded[0]["project_id"] == "project-1"
    assert recorded[0]["user_id"] == 4
    assert recorded[0]["asset"]["storage_mode"] == "local_file"
    assert recorded[0]["metadata"]["export_kind"] == "preview"
