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


@pytest.mark.asyncio
async def test_video_production_runner_real_keyframes_continue_until_all_shots_have_images():
    runner = object.__new__(VideoProductionRunner)
    runner.provider_mode = "real"
    runner.image_provider = "seedream"
    runner.max_image_tasks = 4
    load_calls = 0
    dispatched = []

    def shot(index, *, selected_image=""):
        return {"shot_index": index, "selected_image": selected_image}

    async def load_shots():
        nonlocal load_calls
        load_calls += 1
        if load_calls == 1:
            return [shot(index) for index in range(1, 9)]
        if load_calls == 2:
            return [
                shot(index, selected_image=f"https://cdn.test/{index}.png")
                if index <= 4 else shot(index)
                for index in range(1, 9)
            ]
        return [
            shot(index, selected_image=f"https://cdn.test/{index}.png")
            for index in range(1, 9)
        ]

    async def dispatch_media_tasks(targets, **_kwargs):
        indices = [row["shot_index"] for row in targets]
        dispatched.append(indices)
        return {"task_ids": [f"image-{index}" for index in indices], "credits_reserved": len(indices)}

    async def wait_for_child_tasks(task_ids, *, stage):
        assert stage == "generate_keyframes"
        return {"done": len(task_ids), "failed": 0}

    runner._load_shots = load_shots
    runner._dispatch_media_tasks = dispatch_media_tasks
    runner._wait_for_child_tasks = wait_for_child_tasks

    result = await runner._generate_keyframes()

    assert dispatched == [[1, 2, 3, 4], [5, 6, 7, 8]]
    assert result["queued"] == 8
    assert result["completed"] == 8
    assert result["credits_reserved"] == 8


@pytest.mark.asyncio
async def test_video_production_runner_real_videos_continue_until_all_shots_have_videos():
    runner = object.__new__(VideoProductionRunner)
    runner.provider_mode = "real"
    runner.video_provider = "ltx2.3"
    runner.max_video_tasks = 3
    load_calls = 0
    dispatched = []

    def shot(index, *, selected_video=""):
        return {
            "shot_index": index,
            "selected_image": f"https://cdn.test/{index}.png",
            "selected_video": selected_video,
        }

    async def load_shots():
        nonlocal load_calls
        load_calls += 1
        if load_calls == 1:
            return [shot(index) for index in range(1, 9)]
        if load_calls == 2:
            return [
                shot(index, selected_video=f"https://cdn.test/{index}.mp4")
                if index <= 3 else shot(index)
                for index in range(1, 9)
            ]
        if load_calls == 3:
            return [
                shot(index, selected_video=f"https://cdn.test/{index}.mp4")
                if index <= 6 else shot(index)
                for index in range(1, 9)
            ]
        return [
            shot(index, selected_video=f"https://cdn.test/{index}.mp4")
            for index in range(1, 9)
        ]

    async def dispatch_media_tasks(targets, **_kwargs):
        indices = [row["shot_index"] for row in targets]
        dispatched.append(indices)
        return {"task_ids": [f"video-{index}" for index in indices], "credits_reserved": len(indices)}

    async def wait_for_child_tasks(task_ids, *, stage):
        assert stage == "generate_videos"
        return {"done": len(task_ids), "failed": 0}

    runner._load_shots = load_shots
    runner._dispatch_media_tasks = dispatch_media_tasks
    runner._wait_for_child_tasks = wait_for_child_tasks

    result = await runner._generate_videos()

    assert dispatched == [[1, 2, 3], [4, 5, 6], [7, 8]]
    assert result["queued"] == 8
    assert result["completed"] == 8
    assert result["credits_reserved"] == 8
