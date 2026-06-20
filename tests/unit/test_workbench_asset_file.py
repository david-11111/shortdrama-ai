from pathlib import Path

import pytest

from app.routes import workbench


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Db:
    def __init__(self, row):
        self.row = row
        self.params = None

    async def execute(self, _query, params):
        self.params = params
        return _Result(self.row)


@pytest.mark.asyncio
async def test_get_asset_file_serves_active_local_asset(monkeypatch):
    asset_file = Path(__file__)
    calls = []

    async def ensure_owner(_db, project_id, user_id):
        calls.append((project_id, user_id))

    monkeypatch.setattr(workbench, "_ensure_project_owner", ensure_owner)
    monkeypatch.setattr(workbench, "STORAGE", asset_file.parent)

    response = await workbench.get_asset_file(
        "project-1",
        "asset-1",
        db=_Db({"file_path": str(asset_file), "asset_type": "image"}),
        current_user={"id": 7},
    )

    assert calls == [("project-1", 7)]
    assert Path(response.path) == asset_file


@pytest.mark.asyncio
async def test_get_public_asset_file_serves_without_owner_check(monkeypatch):
    asset_file = Path(__file__)

    async def fail_owner(*_args, **_kwargs):
        raise AssertionError("public asset file route should not require owner auth")

    monkeypatch.setattr(workbench, "_ensure_project_owner", fail_owner)
    monkeypatch.setattr(workbench, "STORAGE", asset_file.parent)

    response = await workbench.get_public_asset_file(
        "project-1",
        "asset-1",
        db=_Db({"file_path": str(asset_file), "asset_type": "image"}),
    )

    assert Path(response.path) == asset_file
