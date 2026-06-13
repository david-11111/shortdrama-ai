import shutil
import asyncio
import time
import uuid
from pathlib import Path

import pytest

from app.services import project_continue, project_workspace
from app.services import requirement_pipeline


@pytest.mark.asyncio
async def test_requirement_pipeline_uses_doubao_first_pass_then_prompt_library(monkeypatch):
    calls = {"doubao": 0, "retrieval_query": ""}

    async def fake_doubao_card(instruction, *, project_context, **kwargs):
        calls["doubao"] += 1
        return {
            "initial_brief": "高级美妆睫毛产品广告，重点是眼部微距、使用动作和效果展示。",
            "demand_type": "product_ad",
            "subject": "睫毛广告",
            "selling_points": ["根根分明", "自然卷翘"],
            "visual_anchors": ["眼部微距", "睫毛根根分明"],
            "action_anchors": ["涂睫毛膏", "夹睫毛", "展示效果"],
            "tone_anchors": ["高级美妆质感", "柔光", "干净奢华"],
            "must_not": ["不要短剧冲突", "不要对手方施压"],
        }

    def fake_retrieve(query, **kwargs):
        calls["retrieval_query"] = query
        return {
            "matched": [
                {
                    "id": "50",
                    "name": "TVC商业广告片专属工程",
                    "prompt_text": "以产品为绝对核心，每一秒服务产品质感与品牌调性。",
                    "score": 11.45,
                }
            ],
            "base": [],
        }

    monkeypatch.setattr(requirement_pipeline, "_call_doubao_requirement_card", fake_doubao_card)
    monkeypatch.setattr(requirement_pipeline, "retrieve_prompt_matches", fake_retrieve)

    result = await requirement_pipeline.build_requirement_pipeline(
        "睫毛广告，豆包你帮我做个设计",
        project_context={"project_id": "p1"},
    )

    assert calls["doubao"] == 1
    assert "睫毛广告" in calls["retrieval_query"]
    assert "高级美妆质感" in calls["retrieval_query"]
    assert result["source"] == "doubao"
    assert result["demand_type"] == "product_ad"
    assert result["understanding_card"]["subject"] == "睫毛广告"
    assert result["library_context"]["matched_names"] == ["TVC商业广告片专属工程"]
    assert "以产品为绝对核心" in result["library_context"]["prompt_block"]


@pytest.mark.asyncio
async def test_requirement_pipeline_times_out_slow_doubao_first_pass(monkeypatch):
    calls = {"retrieval": 0}

    async def slow_doubao_card(instruction, *, project_context, **kwargs):
        await asyncio.sleep(1)
        return {"initial_brief": "too late", "demand_type": "short_drama"}

    def fake_retrieve(query, **kwargs):
        calls["retrieval"] += 1
        return {"matched": [{"name": "local match", "prompt_text": "local prompt"}]}

    monkeypatch.setattr(requirement_pipeline, "_call_doubao_requirement_card", slow_doubao_card)
    monkeypatch.setattr(requirement_pipeline, "retrieve_prompt_matches", fake_retrieve)

    start = time.perf_counter()
    result = await requirement_pipeline.build_requirement_pipeline(
        "night delivery short drama",
        project_context={"project_id": "p1"},
        llm_timeout_seconds=0.01,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5
    assert result["source"] == "local_fallback"
    assert "timeout" in result["llm_error"].lower()
    assert result["initial_brief"] == "night delivery short drama"
    assert calls["retrieval"] == 1
    assert result["library_context"]["matched_names"] == ["local match"]


def test_continue_project_from_brain_uses_enriched_product_ad_card(monkeypatch):
    storage = Path("storage") / "test-requirement-pipeline" / uuid.uuid4().hex
    monkeypatch.setattr(project_workspace, "STORAGE", storage)
    try:
        requirement = {
            "version": "requirement_pipeline_v1",
            "source": "doubao",
            "demand_type": "product_ad",
            "sufficient_for_storyboard": True,
            "missing_fields": [],
            "understanding_card": {
                "demand_type": "product_ad",
                "subject": "睫毛广告",
                "selling_points": ["根根分明", "自然卷翘"],
                "visual_anchors": ["眼部微距", "睫毛根根分明"],
                "prop_anchors": ["睫毛膏", "睫毛夹", "镜子"],
                "action_anchors": ["涂睫毛膏", "夹睫毛", "展示睫毛效果"],
                "tone_anchors": ["高级美妆质感", "柔光", "干净奢华"],
                "must_not": ["不要短剧冲突", "不要对手方施压", "不要电视剧质感"],
            },
            "library_context": {
                "matched_names": ["TVC商业广告片专属工程"],
                "prompt_block": "TVC商业广告片专属工程：以产品为绝对核心，每一秒服务产品质感与品牌调性。",
                "matched": [
                    {
                        "id": "50",
                        "name": "TVC商业广告片专属工程",
                        "prompt_text": "以产品为绝对核心，每一秒服务产品质感与品牌调性。",
                    }
                ],
            },
        }

        result = project_continue.continue_project_from_brain(
            "product-ad-lash",
            instruction="睫毛广告，豆包你帮我做个设计",
            name="睫毛广告",
            story_understanding=requirement,
        )

        prompts = "\n".join(row["prompt"] for row in result["shot_rows"])
        assert result["intent_constraints"]["story_type"] == "product_ad"
        assert "TVC商业广告片专属工程" in result["intent_constraints"]["library_context_summary"]
        assert "睫毛广告" in prompts
        assert "睫毛膏" in prompts or "睫毛夹" in prompts
        assert "眼部微距" in prompts
        assert "涂睫毛膏" in prompts or "夹睫毛" in prompts
        assert "展示睫毛效果" in prompts
        assert "高级美妆质感" in prompts
        assert "主角" not in prompts
        assert "对手方" not in prompts
        assert "情绪压迫" not in prompts
        assert "电视剧质感" not in prompts
    finally:
        shutil.rmtree(storage.parent, ignore_errors=True)
