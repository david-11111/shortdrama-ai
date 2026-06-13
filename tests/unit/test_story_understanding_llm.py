import pytest

from app.services import story_understanding_llm


pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_story_understanding_llm_falls_back_when_key_missing(monkeypatch):
    class Settings:
        deepseek_api_key = ""

    monkeypatch.setattr(story_understanding_llm, "get_settings", lambda: Settings())

    result = await story_understanding_llm.build_story_understanding_with_llm(
        "我想复拍最近很火的张嘉益演的电视剧主角的前一分钟戏。"
    )

    assert result["source"] == "local_fallback"
    assert result["understanding_card"]["role"] == "胡三元"


@pytest.mark.asyncio
async def test_story_understanding_llm_merges_deepseek_json(monkeypatch):
    class Settings:
        deepseek_api_key = "key"
        deepseek_model = "deepseek-chat"
        deepseek_base_url = "https://deepseek.test"

    async def fake_call(_instruction, *, project_context):
        return {
            "work": "主角",
            "actor": "张嘉益",
            "role": "胡三元",
            "role_identity": "县剧团司鼓、秦腔人",
            "story_world": "西北县剧团后台与排练场",
            "scene_anchors": ["县剧团后台", "排练场"],
            "prop_anchors": ["鼓槌", "旧谱本"],
            "action_anchors": ["敲鼓点", "看排练"],
            "tone_anchors": ["秦腔舞台气息"],
            "must_not": ["泛化成电视剧男主"],
            "confidence": 0.92,
        }

    monkeypatch.setattr(story_understanding_llm, "get_settings", lambda: Settings())
    monkeypatch.setattr(story_understanding_llm, "_call_deepseek_story_understanding", fake_call)

    result = await story_understanding_llm.build_story_understanding_with_llm("需求", project_context={})

    assert result["source"] == "deepseek"
    assert result["sufficient_for_storyboard"] is True
    assert result["understanding_card"]["role"] == "胡三元"
    assert "鼓槌" in result["understanding_card"]["prop_anchors"]


def test_story_understanding_llm_marks_incomplete_llm_output_not_sufficient():
    local = {"understanding_card": {}, "mentions_real_work": True}
    result = story_understanding_llm._merge_llm_card(local, {"actor": "张嘉益", "role": "电视剧主角"})

    assert result["sufficient_for_storyboard"] is False
    assert "work" in result["missing_fields"]
    assert "role_identity" in result["missing_fields"]
    assert "story_world" in result["missing_fields"]


@pytest.mark.asyncio
async def test_story_understanding_llm_rejects_placeholder_deepseek_fields(monkeypatch):
    class Settings:
        deepseek_api_key = "key"
        deepseek_model = "deepseek-chat"
        deepseek_base_url = "https://deepseek.test"

    async def fake_call(_instruction, *, project_context):
        return {
            "work": "主角",
            "actor": "张嘉益",
            "role": "missing_fields",
            "role_identity": "missing_fields",
            "story_world": "missing_fields",
            "scene_anchors": ["missing_fields"],
            "prop_anchors": ["未知"],
            "missing_fields": ["role", "role_identity", "story_world"],
            "confidence": 0.2,
        }

    monkeypatch.setattr(story_understanding_llm, "get_settings", lambda: Settings())
    monkeypatch.setattr(story_understanding_llm, "_call_deepseek_story_understanding", fake_call)

    result = await story_understanding_llm.build_story_understanding_with_llm(
        "我想复拍最近很火的张嘉益演的电视剧主角的前一分钟戏。", project_context={}
    )

    assert result["source"] == "deepseek"
    assert result["sufficient_for_storyboard"] is True
    assert result["missing_fields"] == []
    assert result["understanding_card"]["work"] == "主角"
    assert result["understanding_card"]["role"] == "胡三元"
    assert "县剧团" in result["understanding_card"]["story_world"]
    assert "missing_fields" not in result["understanding_card"]["scene_anchors"]
