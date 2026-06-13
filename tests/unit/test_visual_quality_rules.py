from app.services.visual_quality_rules import (
    apply_video_motion_controls,
    apply_visual_quality_controls,
    build_human_performance_controls,
    build_video_motion_controls,
    build_visual_quality_controls,
)


def test_visual_quality_controls_add_generation_quality_layers():
    prompt = "第1集第1场，建立镜头：主角进入核心控制室。"

    result = apply_visual_quality_controls(prompt)

    assert "画面质感控制" in result
    assert "自然光影" in result
    assert "空间层次" in result
    assert "情绪色调" in result
    assert "真实质感" in result
    assert "避免廉价塑料感" in result
    assert "真人表演" in result
    assert "肢体联动" in result


def test_visual_quality_controls_respect_existing_lighting_and_depth_terms():
    prompt = "近景特写，侧光照亮人物，前景有文件夹，背景虚化，冷峻氛围。"

    controls = build_visual_quality_controls(prompt)

    joined = " ".join(controls)
    assert "光影连续" in joined
    assert "景深透视" in joined
    assert "氛围统一" in joined
    assert "自然光影：避免全画面均匀打光" not in joined


def test_visual_quality_controls_are_idempotent():
    prompt = "人物坐在办公室。\n画面质感控制：自然光影。"

    result = apply_visual_quality_controls(prompt)

    assert result == prompt


def test_human_performance_controls_respect_micro_expression_and_body_terms():
    prompt = "她嘴角轻轻上扬，眼神柔和，单手轻抚嘴角，肩膀微颤。"

    controls = build_human_performance_controls(prompt)

    joined = " ".join(controls)
    assert "微表情执行" in joined
    assert "肢体同步" in joined
    assert "夸张表演" in joined


def test_video_motion_controls_add_camera_formula_layers():
    prompt = "人物站在夜晚街角，背景霓虹虚化。"

    result = apply_video_motion_controls(prompt)

    assert "视频运镜控制" in result
    assert "景别" in result
    assert "运镜" in result
    assert "速度节奏" in result
    assert "主体配合" in result
    assert "环境配合" in result


def test_video_motion_controls_respect_existing_camera_terms():
    prompt = "中景镜头缓慢向前推进，画面稳定顺滑，聚焦人物面部神态。"

    controls = build_video_motion_controls(prompt)

    joined = " ".join(controls)
    assert "景别执行" in joined
    assert "运镜执行" in joined
    assert "移动快慢与情绪一致" in joined
    assert "默认中景或中近景" not in joined


def test_video_motion_controls_are_idempotent():
    prompt = "人物走进房间。\n视频运镜控制：镜头缓慢推进。"

    result = apply_video_motion_controls(prompt)

    assert result == prompt
