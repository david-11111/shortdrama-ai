from pathlib import Path
import hashlib
import pytest
import shutil
import uuid


def test_object_storage_asset_preserves_remote_reference():
    from app.services.final_video_storage import object_storage_asset

    asset = object_storage_asset(file_url="https://cdn.example/final.mp4", oss_key="k/final.mp4", file_size=123)

    assert asset["storage_mode"] == "oss"
    assert asset["file_url"] == "https://cdn.example/final.mp4"
    assert asset["oss_key"] == "k/final.mp4"
    assert asset["file_path"] is None
    assert asset["file_size"] == 123


def test_local_fallback_is_addressable_and_cannot_escape_storage(monkeypatch):
    from app.services import final_video_storage

    base = Path("tests") / ".tmp_final_video_storage" / uuid.uuid4().hex
    try:
        source = base / "source.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"final-video")
        monkeypatch.setattr(final_video_storage, "FINAL_VIDEO_DIR", base / "finals")

        asset = final_video_storage.copy_final_video_to_local_store(
            source_path=str(source),
            project_id="../project:id",
            task_id="task:id",
        )

        path = Path(asset["file_path"])
        assert path.exists()
        assert path.read_bytes() == b"final-video"
        assert path.parent.name == "project_id"
        assert path.name == "task_id.mp4"
        assert asset["storage_mode"] == "local_file"
        assert asset["file_url"] == "/api/director/final-video/task:id"
        assert asset["file_size"] == len(b"final-video")
        assert asset["checksum_sha256"] == hashlib.sha256(b"final-video").hexdigest()
    finally:
        shutil.rmtree(base, ignore_errors=True)


async def test_final_video_response_reports_missing_asset_file():
    from fastapi import HTTPException
    from app.services.final_video_storage import final_video_response

    class Result:
        def mappings(self):
            return self

        def first(self):
            return {
                "storage_mode": "local_file",
                "content_type": "video/mp4",
                "file_size": 10,
                "file_path": "tests/.missing/final.mp4",
                "file_url": "/api/director/final-video/task",
            }

    class Db:
        async def execute(self, *_args, **_kwargs):
            return Result()

    with pytest.raises(HTTPException) as exc:
        await final_video_response(Db(), task_id="00000000-0000-0000-0000-000000000001", user_id=1)

    assert exc.value.status_code == 502
    assert "missing" in exc.value.detail
