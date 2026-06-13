import pytest

from app.services.director_preflight import analyze_shot_risk


pytestmark = [pytest.mark.unit]


def test_empty_template_storyboard_is_blocked_before_keyframe_generation():
    report = analyze_shot_risk({
        "prompt": "第1集第1场，建立镜头：主角进入核心场景，环境空间关系清楚，人物正面可辨识，情绪克制但有目标。",
    })

    assert report["risk_level"] == "blocked"
    assert any(item["code"] == "empty_template_storyboard" for item in report["risks"])
    assert report["can_generate_image"] is False


def test_storyboard_must_preserve_actor_drama_requirement_from_project_goal():
    report = analyze_shot_risk(
        {
            "prompt": "第1集第1场，关系镜头：主角与对手方形成明确对话关系，画面不超过两个人。",
        },
        project_goal="我想复拍最近很火的张嘉益演的电视剧主角的前一分钟戏。",
    )

    assert report["risk_level"] == "blocked"
    assert any(item["code"] == "intent_entity_missing" for item in report["risks"])


def test_concrete_actor_storyboard_is_not_empty_template_blocked():
    report = analyze_shot_risk(
        {
            "prompt": "第1集第1场，建立镜头：张嘉益演的电视剧主角推门进入派出所调解室，半身正面可辨，手里攥着旧文件袋，眼神克制但压着火。",
        },
        project_goal="我想复拍最近很火的张嘉益演的电视剧主角的前一分钟戏。",
    )

    assert not any(item["code"] == "empty_template_storyboard" for item in report["risks"])
    assert not any(item["code"] == "intent_entity_missing" for item in report["risks"])


def test_audience_readability_text_does_not_count_as_crowd_overload():
    report = analyze_shot_risk({
        "prompt": "第1集第1场，师承压力：张嘉益饰演的胡三元在戏台边压低声音训戏，近景强调脸部和手上鼓槌，让观众识别他是秦腔剧团司鼓，不允许变成空镜或无身份路人。",
    })

    assert not any(item["code"] == "crowd_overload" for item in report["risks"])
    assert report["can_generate_image"] is True


def test_actual_crowd_language_still_blocks_generation():
    report = analyze_shot_risk({
        "prompt": "全景展示戏台边围观人群和拥挤后台，很多人同时看向主角。",
    })

    assert any(item["code"] == "crowd_overload" for item in report["risks"])
    assert report["risk_level"] == "blocked"
