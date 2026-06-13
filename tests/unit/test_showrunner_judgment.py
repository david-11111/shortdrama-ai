from app.services.showrunner_judgment import (
    build_goal_card,
    judge_existing_media_review,
    judge_prompt_fidelity,
    judge_shot_responsibility,
    judge_story_alignment,
    make_showrunner_decision,
)


REAL_PROJECT_GOAL = "我做这个工具快一个月了，从开始立项，到现在，经历了很多，我希望你能把这个过程做成短剧"


def test_build_goal_card_for_real_project_process_sets_durable_target():
    card = build_goal_card(REAL_PROJECT_GOAL, project_name="real-provider-e31ba157")

    assert card.source_type == "real_project_process"
    assert "链路能跑" in card.central_conflict
    assert "不会判断" in card.central_conflict
    assert "电脑屏幕" in card.visual_anchors
    assert "测试日志" in card.visual_anchors
    assert "电视剧主角" in " ".join(card.must_not)
    assert "项目ID" in " ".join(card.must_not)


def test_build_goal_card_does_not_treat_generic_workspace_project_as_real_process():
    card = build_goal_card(
        "agent_test_project\n项目工作区初始化，等待用户补充内容。\nShot 0: a dramatic scene in the rain",
        project_name="agent_test_project",
    )

    assert card.source_type == "fiction_short_drama"
    assert card.visual_anchors == []


def test_build_goal_card_for_gold_product_listing_video():
    card = build_goal_card(
        "我准备上架这个黄金产品，用图片监督整个链条生成，视频不超过10秒，要有创意。古法拉丝竹节手串，不带叶子，金重9.25g。",
        project_name="古法拉丝竹节手串",
    )

    assert card.source_type == "product_listing_video"
    assert card.format == "product_listing_video"
    assert "古法拉丝手串" in card.visual_anchors
    assert "金重9.25g" in card.visual_anchors
    assert "视频超过10秒" in " ".join(card.must_not)


def test_product_listing_prompt_blocks_generic_gold_bracelet():
    card = build_goal_card(
        "黄金产品上架视频，不超过10秒，古法拉丝竹节手串，金重9.25g。",
        project_name="古法拉丝竹节手串",
    )
    report = judge_prompt_fidelity(card, "高级金色手链，奢华背景，慢动作展示。")

    assert report.status in {"regenerate", "blocked"}
    assert "missing_product_identity" in report.problem_codes


def test_product_listing_prompt_passes_when_product_facts_are_locked():
    card = build_goal_card(
        "黄金产品上架视频，不超过10秒，古法拉丝竹节手串，金重9.25g，不带叶子。",
        project_name="古法拉丝竹节手串",
    )
    shot = {
        "shot_index": 1,
        "prompt": "10秒产品镜头：手持实拍古法拉丝手串，微距特写竹节结构和黄金质感，标签露出金重9.25g，不带叶子，干净木色背景，缓慢旋转形成购买记忆点。",
    }

    shot_report = judge_shot_responsibility(card, shot)
    prompt_report = judge_prompt_fidelity(card, shot["prompt"], shot=shot)

    assert shot_report.status == "pass"
    assert prompt_report.status == "pass"


def test_product_ad_prompt_uses_dynamic_gold_jewelry_anchors():
    card = build_goal_card(
        "商业广告测试：为一款黄金项链做15秒高质感短视频。画面要真实、明亮、突出黄金质感，不要抽象色块。",
        context={
            "project": "商业广告，类型为产品广告；核心卖点是产品质感、可见效果；画面必须围绕黄金首饰、首饰盒、镜面台面、产品微距、金属高光、反光细节、佩戴效果和佩戴首饰、旋转展示、展示产品细节展开。",
        },
    )
    shot = {
        "shot_index": 1,
        "prompt": "商业广告开场，画面先给黄金首饰、产品微距、金属高光、反光细节、佩戴效果，用干净柔和光线建立轻奢、高级、精致、光影质感。",
    }

    shot_report = judge_shot_responsibility(card, shot)
    prompt_report = judge_prompt_fidelity(card, shot["prompt"], shot=shot)

    assert card.source_type == "product_listing_video"
    assert "黄金首饰" in card.visual_anchors
    assert "产品微距" in card.visual_anchors
    assert "15秒" in " ".join(card.market_constraints)
    assert "视频超过10秒" not in " ".join(card.must_not)
    assert shot_report.status == "pass"
    assert prompt_report.status == "pass"
    assert "missing_visual_anchors" not in prompt_report.problem_codes


def test_shot_responsibility_blocks_generic_project_id_leakage():
    card = build_goal_card(REAL_PROJECT_GOAL, project_name="real-provider-e31ba157")
    report = judge_shot_responsibility(
        card,
        {
            "shot_index": 1,
            "prompt": "第1集第1场，建立镜头：real-provider-e31ba157，围绕电视剧主角的开场段落戏，先理解人物身份、处境、动作目标和情绪推进，再拆成可拍分镜。",
        },
    )

    assert report.status == "blocked"
    assert report.root_cause_layer == "shot"
    assert "generic_protagonist" in report.problem_codes
    assert "project_id_leakage" in report.problem_codes
    assert report.suggested_action == "rewrite_shots_and_prompts"


def test_prompt_fidelity_blocks_prompt_that_loses_goal_card():
    card = build_goal_card(REAL_PROJECT_GOAL, project_name="real-provider-e31ba157")
    report = judge_prompt_fidelity(
        card,
        "cinematic short drama opening, real-provider-e31ba157, 电视剧主角 enters the core scene",
        shot={"shot_index": 1},
    )

    assert report.status == "blocked"
    assert report.root_cause_layer == "prompt"
    assert "project_id_leakage" in report.problem_codes
    assert "generic_protagonist" in report.problem_codes
    assert "missing_visual_anchors" in report.problem_codes


def test_story_judge_requires_hook_conflict_and_premium_texture():
    card = build_goal_card(REAL_PROJECT_GOAL)
    report = judge_story_alignment(card, "一个主角开始做短剧，然后遇到困难，最后继续努力。")

    assert report.status == "regenerate"
    assert report.root_cause_layer == "story"
    assert "weak_commercial_hook" in report.problem_codes
    assert "missing_central_conflict" in report.problem_codes


def test_showrunner_decision_aggregates_root_cause_and_repair_action():
    card = build_goal_card(REAL_PROJECT_GOAL, project_name="real-provider-e31ba157")
    reports = [
        judge_shot_responsibility(
            card,
            {"shot_index": 1, "prompt": "第1集第1场，建立镜头：real-provider-e31ba157，围绕电视剧主角的开场段落戏。"},
        ),
        judge_prompt_fidelity(card, "电视剧主角 generic opening, real-provider-e31ba157"),
    ]

    decision = make_showrunner_decision(reports, run_id="run-1", stage_id="generate_keyframes")

    assert decision.status == "blocked"
    assert decision.root_cause_layer in {"shot", "prompt"}
    assert decision.action == "rewrite_shots_and_prompts"
    assert decision.selected_lane == "b_lane_agent_runs"
    assert decision.failure_policy["require_human_confirmation"] is False


def test_good_enough_real_project_shot_and_prompt_passes_text_gates():
    card = build_goal_card(REAL_PROJECT_GOAL)
    shot = {
        "shot_index": 1,
        "prompt": "第1镜：深夜，开发者盯着第四次失败的测试日志，电脑屏幕反光压在脸上。职责是建立真实困境和前三秒钩子。",
    }

    shot_report = judge_shot_responsibility(card, shot)
    prompt_report = judge_prompt_fidelity(
        card,
        "深夜办公室，一名疲惫但克制的工具开发者盯着电脑屏幕上的失败测试日志，屏幕冷光压在脸上，桌面散落项目文档和提示词草稿，真实、克制、高级感，前三秒建立问题钩子。",
        shot=shot,
    )

    assert shot_report.status == "pass"
    assert prompt_report.status == "pass"


def test_existing_media_review_is_converted_to_showrunner_evidence():
    card = build_goal_card(REAL_PROJECT_GOAL)
    report = judge_existing_media_review(
        card,
        media_type="image",
        artifact_ref={"url": "https://cdn.test/shot-1.png", "shot_index": 1},
        review={
            "status": "regenerate",
            "score": 41,
            "notes": ["画面像通用办公室素材，没有开发者、测试日志或失败提示。"],
        },
    )

    assert report.status == "regenerate"
    assert report.root_cause_layer == "keyframe"
    assert "existing_review_failed" in report.problem_codes
    assert report.suggested_action == "regenerate_keyframe"
