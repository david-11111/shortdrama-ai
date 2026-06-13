import pytest

from app.services.story_understanding import build_story_understanding


pytestmark = [pytest.mark.unit]


def test_story_understanding_resolves_specific_real_drama_before_storyboard():
    card = build_story_understanding("我想复拍最近很火的张嘉益演的电视剧主角的前一分钟戏。")

    assert card["sufficient_for_storyboard"] is True
    assert card["understanding_card"]["work"] == "主角"
    assert card["understanding_card"]["role"] == "胡三元"
    assert "县剧团后台" in card["understanding_card"]["scene_anchors"]
    assert "鼓槌" in card["understanding_card"]["prop_anchors"]
    assert "泛化成无身份电视剧男主" in card["understanding_card"]["must_not"]


def test_story_understanding_blocks_ambiguous_real_work_reference():
    card = build_story_understanding("我想复拍最近很火的某演员演的电视剧主角开场。")

    assert card["sufficient_for_storyboard"] is False
    assert "actor_role_needs_fact_check" in card["ambiguity_flags"]
    assert "work_title" in card["missing_fields"]
    assert any(step["id"] == "resolve_real_work" and step["status"] == "blocked" for step in card["required_steps"])
