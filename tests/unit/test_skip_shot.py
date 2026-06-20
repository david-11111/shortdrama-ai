"""skip_shot 功能测试。

覆盖：
1. StatsAccumulator 跳过 selected=false 的 shot
2. _recovery_actions_for_gate 返回 skip_shot
"""
from __future__ import annotations

from app.routes import agent_runs
from app.services.state_machine.stats import StatsAccumulator


def test_stats_accumulator_skips_deselected_shots() -> None:
    acc = StatsAccumulator()
    # 正常的 shot
    acc.add_shot({
        "shot_index": 1,
        "selected": True,
        "selected_image": "/img/1.png",
        "selected_video": "/vid/1.mp4",
        "prompt": "test",
        "image_candidates_json": [],
        "video_variants_json": [],
    })
    # 被跳过的 shot
    acc.add_shot({
        "shot_index": 2,
        "selected": False,
        "selected_image": "",
        "selected_video": "",
        "prompt": "broken",
        "image_candidates_json": [],
        "video_variants_json": [],
    })
    # 又一个正常的 shot
    acc.add_shot({
        "shot_index": 3,
        "selected": True,
        "selected_image": "/img/3.png",
        "selected_video": "/vid/3.mp4",
        "prompt": "test",
        "image_candidates_json": [],
        "video_variants_json": [],
    })
    stats = acc.finalize()

    # _shot_count 应只计入 2 个 selected=true 的 shot
    assert stats.get("shot_count") == 2, f"expected 2, got {stats.get('shot_count')}"
    # selected_video_count 应只计入 2 个有视频的 shot
    assert stats.get("selected_video_count") == 2, f"expected 2, got {stats.get('selected_video_count')}"
    # video_generation_complete 应为 True（所有 selected=true 的 shot 都有视频）
    assert stats.get("video_generation_complete") is True, f"video_generation_complete should be True"


def test_stats_accumulator_deselected_shot_no_video_does_not_block() -> None:
    """跳过的 shot 即使没有 selected_video 也不应阻塞 pipeline。"""
    acc = StatsAccumulator()
    # 正常的 shot — 有视频
    acc.add_shot({
        "shot_index": 1,
        "selected": True,
        "selected_image": "/img/1.png",
        "selected_video": "/vid/1.mp4",
        "prompt": "test",
        "image_candidates_json": [],
        "video_variants_json": [],
    })
    # 被跳过的 shot — 没有 video，不应该阻塞
    acc.add_shot({
        "shot_index": 2,
        "selected": False,
        "selected_image": "",
        "selected_video": "",
        "prompt": "broken",
        "image_candidates_json": [],
        "video_variants_json": [{
            "url": "/vid/fail.mp4",
            "review_status": "failed",
        }],
    })
    stats = acc.finalize()

    assert stats.get("shot_count") == 1
    assert stats.get("video_generation_complete") is True, (
        f"video_generation_complete should be True even with skipped broken shot, "
        f"got {stats.get('video_generation_complete')}"
    )
    assert stats.get("video_review_blocking_count") == 0, (
        f"video_review_blocking_count should be 0 for skipped shot, "
        f"got {stats.get('video_review_blocking_count')}"
    )


def test_recovery_actions_includes_skip_shot_when_video_missing() -> None:
    """selected_video 缺失时，可用动作列表中应包含 skip_shot。"""
    actions = agent_runs._recovery_actions_for_gate(
        "generate_videos",
        {"missing": ["selected_video"]},
    )
    assert "skip_shot" in actions, f"skip_shot not in {actions}"


def test_recovery_actions_not_include_skip_shot_for_image_missing() -> None:
    """selected_image 缺失时，不应包含 skip_shot。"""
    actions = agent_runs._recovery_actions_for_gate(
        "generate_keyframes",
        {"missing": ["selected_image"]},
    )
    assert "skip_shot" not in actions, f"skip_shot should not be in {actions}"
