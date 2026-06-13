import pytest


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_direct_image_batch_requires_agent_run_entrypoint(client, test_user_pro):
    response = await client.post(
        "/api/batch/generate-images",
        json={"items": [{"prompt": "a product photo"}]},
        headers={"Authorization": test_user_pro["auth_header"]},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "agent_run_entrypoint_required"
    assert body["debug"]["allowed_entrypoint"] == "/director/agent-run"
    assert body["debug"]["api_entrypoint"] == "POST /api/agent-runs"


async def test_direct_video_batch_requires_agent_run_entrypoint(client, test_user_pro):
    response = await client.post(
        "/api/batch/generate-videos",
        json={"items": [{"prompt": "a product video", "duration": 5}]},
        headers={"Authorization": test_user_pro["auth_header"]},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "agent_run_entrypoint_required"
    assert body["debug"]["allowed_entrypoint"] == "/director/agent-run"
    assert body["debug"]["api_entrypoint"] == "POST /api/agent-runs"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/director/script", {"project_id": "legacy_direct", "query": "write a script"}),
        ("/api/director/prepare", {"project_id": "legacy_direct"}),
        ("/api/director/produce", {"project_id": "legacy_direct"}),
        ("/api/director/reference-images", {"project_id": "legacy_direct", "shot_indices": [1]}),
        ("/api/director/export-final", {"project_id": "legacy_direct", "ignore_saved_plan": True}),
        ("/api/director/export-preview", {"project_id": "legacy_direct", "ignore_saved_plan": True}),
    ],
)
async def test_legacy_direct_director_production_routes_are_blocked(client, test_user_pro, path, payload):
    response = await client.post(
        path,
        json=payload,
        headers={"Authorization": test_user_pro["auth_header"]},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "agent_run_entrypoint_required"
    assert body["debug"]["allowed_entrypoint"] == "/director/agent-run"


async def test_agent_run_accepts_input_assets_from_unique_entrypoint(client, test_user_pro):
    project_response = await client.post(
        "/api/projects",
        json={"name": "agent-run-input-assets"},
        headers={"Authorization": test_user_pro["auth_header"]},
    )
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["project_id"]

    response = await client.post(
        "/api/agent-runs",
        json={
            "project_id": project_id,
            "goal": "先生成故事计划，记录入口资产",
            "mode": "step",
            "action": "continue_project",
            "params": {
                "continue_action": "generate_story_plan",
                "input_assets": [
                    {
                        "asset_id": "asset-gold-1",
                        "asset_type": "image",
                        "file_url": "/assets/project/gold.png",
                        "role": "golden_reference",
                    }
                ]
            },
        },
        headers={"Authorization": test_user_pro["auth_header"]},
    )

    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    events_response = await client.get(
        f"/api/agent-runs/{run_id}/events",
        headers={"Authorization": test_user_pro["auth_header"]},
    )
    assert events_response.status_code == 200, events_response.text
    input_events = [
        event for event in events_response.json()["events"]
        if event.get("phase") == "input_assets"
    ]
    assert input_events
    assert input_events[0]["meta"]["input_assets"][0]["asset_id"] == "asset-gold-1"


async def test_agent_run_asset_upload_accepts_image_file(client, test_user_pro, monkeypatch):
    from app.routes import workbench

    class FakeStorageClient:
        def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
            assert fileobj.read() == b"fake image bytes"

    monkeypatch.setattr(workbench.storage_service, "_client", FakeStorageClient())

    project_response = await client.post(
        "/api/projects",
        json={"name": "agent-run-upload-image"},
        headers={"Authorization": test_user_pro["auth_header"]},
    )
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["project_id"]

    response = await client.post(
        f"/api/projects/{project_id}/assets/upload",
        files={"file": ("gold.jpg", b"fake image bytes", "image/jpeg")},
        data={"asset_type": "image", "metadata_json": '{"role":"golden_reference"}'},
        headers={"Authorization": test_user_pro["auth_header"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["asset_type"] == "image"
    assert payload["file_url"]
    assert payload["metadata_json"]["role"] == "golden_reference"
    assert payload["metadata_json"]["asset_kind"] == "golden_reference"
    assert payload["metadata_json"]["entity_type"] == "golden_reference"
    assert payload["metadata_json"]["lineage_role"] == "source"
    assert payload["metadata_json"]["size"] == len(b"fake image bytes")
