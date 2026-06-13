import pytest
from fastapi import HTTPException

from app.routes.director import _sanitize_director_payload
from app.routes.workbench import _apply_visual_plan_action_to_db
from app.services.production_text_quality import analyze_production_text_effectiveness


pytestmark = [pytest.mark.unit]


def test_vague_style_words_are_not_actionable_reference_prompt():
    report = analyze_production_text_effectiveness("电影感，高级，氛围统一，质感稳定", domain="reference_image")

    assert report["ok"] is False
    assert "missing_concrete_anchor" in report["reasons"]
    assert "vague_style_only" in report["reasons"]


def test_concrete_actor_reference_prompt_is_actionable():
    report = analyze_production_text_effectiveness(
        "张嘉益演的电视剧主角，中年男人，深色夹克，手里攥着旧文件袋，眼神压着火。",
        domain="reference_image",
    )

    assert report["ok"] is True
    assert report["effective_anchor_count"] >= 3


def test_director_reference_images_rejects_empty_style_description():
    with pytest.raises(HTTPException) as exc:
        _sanitize_director_payload(
            "director_ref_images",
            {"character_description": "电影感，高级，氛围统一，质感稳定"},
        )

    assert exc.value.status_code == 400
    assert "参考图描述没有可执行锚点" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_visual_plan_generate_reference_rejects_empty_prompt_seed():
    with pytest.raises(HTTPException) as exc:
        await _apply_visual_plan_action_to_db(
            None,
            "project-1",
            4,
            {
                "id": "shot-1-style",
                "shot_index": 1,
                "kind": "style",
                "action_type": "generate_reference",
                "prompt_seed": "高级电影感，氛围统一，质感稳定",
            },
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["message"].startswith("Visual reference action is not actionable")
