import pytest

pytest.importorskip("asyncpg")

from app.services.ref_resolver import build_image_generation_payload, build_video_generation_payload


def test_motion_controls_apply_only_to_video_payload():
    shot = {
        "project_id": "project-1",
        "shot_index": 1,
        "prompt": "主角站在夜晚街角，背景霓虹虚化。",
        "duration": 5,
        "selected_image": "/assets/project-1/shot-1.png",
    }

    image_payload = build_image_generation_payload(shot, strict=False, assets_by_id={})
    video_payload = build_video_generation_payload(shot, strict=False, assets_by_id={})

    assert "画面质感控制" in image_payload["prompt"]
    assert "真人表演" in image_payload["prompt"]
    assert "视频运镜控制" not in image_payload["prompt"]
    assert "视频运镜控制" in video_payload["prompt"]
    assert video_payload["image"] == "/assets/project-1/shot-1.png"


def test_ref_resolver_preserves_director_input_protocol():
    shot = {
        "project_id": "project-1",
        "shot_index": 1,
        "prompt": "Lu Chenzhou stands before the bone testing platform",
        "duration": 5,
        "selected_image": "/assets/project-1/shot-1.png",
        "director_input_protocol": {
            "task_type": "video",
            "asset_kind": "shot_keyframe",
            "creative_intent": "live action restrained emotion",
            "approval_status": "approved",
            "allowed_next_step": True,
        },
    }

    image_payload = build_image_generation_payload(shot, strict=False, assets_by_id={})
    video_payload = build_video_generation_payload(shot, strict=False, assets_by_id={})

    assert image_payload["director_input_protocol"]["creative_intent"] == "live action restrained emotion"
    assert video_payload["director_input_protocol"]["approval_status"] == "approved"
