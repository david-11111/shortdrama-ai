from app.services.final_edit import validate_delivery_plan


def test_validate_delivery_plan_blocks_missing_bgm_and_subtitles():
    plan = {
        "settings": {"burn_subtitles": True, "bgm_path": ""},
        "clips": [
            {"shot_index": 1, "enabled": True, "video_url": "vid-1", "duration": 5, "subtitle": ""},
        ],
    }

    result = validate_delivery_plan(plan)

    assert result["passed"] is False
    codes = {item["code"] for item in result["errors"]}
    assert "missing_bgm" in codes
    assert "missing_subtitles" in codes


def test_validate_delivery_plan_passes_complete_plan():
    plan = {
        "settings": {"burn_subtitles": True, "bgm_path": "http://audio/bgm.mp3"},
        "clips": [
            {"shot_index": 1, "enabled": True, "video_url": "vid-1", "duration": 5, "subtitle": "opening"},
        ],
    }

    result = validate_delivery_plan(plan)

    assert result["passed"] is True
    assert result["clip_count"] == 1
    assert result["errors"] == []


def test_validate_delivery_plan_blocks_required_voiceover():
    plan = {
        "settings": {
            "burn_subtitles": False,
            "bgm_path": "http://audio/bgm.mp3",
            "require_voiceover": True,
        },
        "clips": [
            {"shot_index": 1, "enabled": True, "video_url": "vid-1", "duration": 5},
        ],
    }

    result = validate_delivery_plan(plan)

    assert result["passed"] is False
    assert {item["code"] for item in result["errors"]} == {"missing_voiceover"}
