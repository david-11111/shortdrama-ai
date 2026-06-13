import pytest
from fastapi import HTTPException

from app.routes.agent_runs import _build_keyframe_variation_prompts
from app.services.project_continue import _build_initial_batch_shots
from app.services.video_production_runner import VideoProductionRunner


pytestmark = [pytest.mark.unit]


def test_keyframe_batch_rejects_empty_template_storyboard_prompt():
    with pytest.raises(HTTPException) as exc:
        _build_keyframe_variation_prompts(
            {
                "shot_index": 1,
                "prompt": "第1集第1场，建立镜头：主角进入核心场景，环境空间关系清楚，人物正面可辨识，情绪克制但有目标。",
            },
            count=3,
            strategy="mixed",
            instruction="",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["message"] == "shot preflight blocked keyframe batch generation"
    assert "empty_template_storyboard" in exc.value.detail["risk_codes"]


@pytest.mark.asyncio
async def test_video_production_runner_does_not_create_default_template_shots():
    runner = object.__new__(VideoProductionRunner)
    runner.plan = {}

    async def load_no_shots():
        return []

    runner._load_shots = load_no_shots

    with pytest.raises(RuntimeError, match="No storyboard shots found"):
        await runner._plan_shots()


@pytest.mark.asyncio
async def test_video_production_runner_default_shot_helper_is_disabled():
    runner = object.__new__(VideoProductionRunner)

    with pytest.raises(RuntimeError, match="Default template shot creation is disabled"):
        await runner._create_default_shots()


def test_legacy_project_continue_template_storyboard_helper_is_disabled():
    with pytest.raises(RuntimeError, match="Legacy template storyboard generation is disabled"):
        _build_initial_batch_shots("demo", {}, {}, {})
