from app.services.agent_run_state_machine import evaluate_action_gate, evaluate_production_stages, infer_continue_action, infer_continue_action_decision, recommend_next_action, validate_policy_graph


def test_script_intent_forces_story_plan_action():
    assert infer_continue_action("从建立剧本开始，先生成故事和分镜规划") == "generate_story_plan"
    decision = infer_continue_action_decision("从建立剧本开始，先生成故事和分镜规划")

    assert decision.action == "generate_story_plan"
    assert decision.confidence >= 0.9
    assert "剧本" in decision.matched


def test_script_intent_has_priority_over_visual_terms():
    assert infer_continue_action("从建立剧本开始，再规划角色视觉资产") == "generate_story_plan"


def test_intent_normalizes_full_width_english():
    assert infer_continue_action("ＳＣＲＩＰＴ first") == "generate_story_plan"


def test_visual_assets_are_blocked_without_story_rows():
    gate = evaluate_action_gate("plan_visual_assets", shots=[], tasks=[])

    assert gate["allowed"] is False
    assert "shot_rows" in gate["missing"]


def test_policy_graph_is_valid_and_commercial_flow_is_explicit():
    result = validate_policy_graph()

    assert result["valid"] is True
    assert result["stage_count"] == 12
    assert result["duplicate_ids"] == []
    assert result["missing_dependencies"] == {}
    assert result["cycles"] == []


def test_unattended_flow_recommends_story_plan_before_visual_assets_when_empty():
    recommendation = recommend_next_action(shots=[], tasks=[])

    assert recommendation["action"] == "generate_story_plan"
    assert recommendation["allowed"] is True


def test_video_generation_requires_selected_keyframe():
    shots = [{"shot_index": 1, "prompt": "shot", "selected_image": "", "selected_video": ""}]

    gate = evaluate_action_gate("generate_videos", shots=shots, tasks=[])

    assert gate["allowed"] is False
    assert "selected_image" in gate["missing"]


def test_video_generation_blocks_failed_keyframe_review():
    shots = [
        {
            "shot_index": 1,
            "prompt": "shot",
            "selected_image": "image.png",
            "selected_video": "",
            "image_candidates": [
                {"url": "image.png", "review": {"status": "regenerate", "score": 38}},
            ],
        }
    ]

    gate = evaluate_action_gate("generate_videos", shots=shots, tasks=[])

    assert gate["allowed"] is False
    assert "image_review_blockers" in gate["missing"]
    assert gate["recovery"] == "generate_keyframes"


def test_video_generation_blocks_keyframe_that_needs_review():
    shots = [
        {
            "shot_index": 1,
            "prompt": "shot",
            "selected_image": "image.png",
            "selected_video": "",
            "image_candidates": [
                {"url": "image.png", "review_status": "needs_review", "review_score": 61},
            ],
        }
    ]

    gate = evaluate_action_gate("generate_videos", shots=shots, tasks=[])

    assert gate["allowed"] is False
    assert "image_review_blockers" in gate["missing"]


def test_later_stages_block_wrong_flow_jumps_without_real_outputs():
    shots = [{"shot_index": 1, "prompt": "shot", "selected_image": "image.png", "selected_video": ""}]

    final_cut = evaluate_action_gate("plan_final_edit", shots=shots, tasks=[])
    quality = evaluate_action_gate("quality_check", shots=shots, tasks=[], production_run={})

    assert final_cut["allowed"] is False
    assert "selected_video" in final_cut["missing"]
    assert quality["allowed"] is False
    assert "final_video_url" in quality["missing"]


def test_final_edit_blocks_failed_video_review():
    shots = [
        {
            "shot_index": 1,
            "prompt": "shot",
            "selected_image": "image.png",
            "selected_video": "video.mp4",
            "video_variants": [
                {"url": "video.mp4", "review_status": "regenerate", "review_score": 39},
            ],
        }
    ]

    gate = evaluate_action_gate("plan_final_edit", shots=shots, tasks=[])

    assert gate["allowed"] is False
    assert "video_review_blockers" in gate["missing"]
    assert gate["recovery"] == "generate_videos"


def test_final_edit_can_skip_failed_intermediate_image_task_when_videos_exist():
    shots = [
        {"shot_index": 1, "prompt": "shot 1", "selected_image": "image-1.png", "selected_video": "video-1.mp4"},
        {"shot_index": 2, "prompt": "shot 2", "selected_image": "image-2.png", "selected_video": "video-2.mp4"},
        {"shot_index": 3, "prompt": "shot 3", "selected_image": "image-3.png", "selected_video": "video-3.mp4"},
        {"shot_index": 4, "prompt": "extra", "selected_image": "", "selected_video": ""},
    ]
    tasks = [{"task_type": "image_gen", "status": "failed"}]

    gate = evaluate_action_gate("plan_final_edit", shots=shots, tasks=tasks)

    assert gate["allowed"] is True
    assert gate["missing"] == []


def test_flow_reflects_real_keyframe_and_video_outputs():
    shots = [
        {"shot_index": 1, "prompt": "shot 1", "selected_image": "image-1.png", "selected_video": "video-1.mp4"},
        {"shot_index": 2, "prompt": "shot 2", "selected_image": "image-2.png", "selected_video": ""},
    ]

    flow = evaluate_production_stages(shots=shots, tasks=[], production_run=None)
    by_id = {stage["id"]: stage for stage in flow}

    assert by_id["generate_story_plan"]["status"] == "completed"
    assert by_id["generate_story_plan"]["source"] == "project_state"
    assert by_id["generate_story_plan"]["policy"]["version"] == "commercial_production_policy_v2"
    assert by_id["generate_keyframes"]["status"] == "completed"
    assert by_id["generate_keyframes"]["source"] == "project_state"
    assert by_id["generate_videos"]["status"] == "completed"
    assert by_id["final_cut"]["status"] in {"pending", "blocked"}


def test_final_artifact_completes_policy_recommendation():
    shots = [
        {
            "shot_index": 1,
            "prompt": "shot 1",
            "selected_image": "image-1.png",
            "selected_video": "video-1.mp4",
        }
    ]
    production_run = {"status": "completed", "final_video_url": "https://cdn.test/final.mp4"}

    recommendation = recommend_next_action(shots=shots, tasks=[], production_run=production_run)

    assert recommendation["status"] == "completed"
    assert recommendation["action"] == "writeback_review"


def test_final_artifact_marks_downstream_stages_completed():
    shots = [
        {
            "shot_index": 1,
            "prompt": "shot 1",
            "selected_image": "image-1.png",
            "selected_video": "video-1.mp4",
        }
    ]
    production_run = {"status": "completed", "final_video_url": "https://cdn.test/final.mp4"}

    flow = evaluate_production_stages(shots=shots, tasks=[], production_run=production_run)
    by_id = {stage["id"]: stage for stage in flow}

    assert by_id["audio_subtitles"]["status"] == "completed"
    assert by_id["final_cut"]["status"] == "completed"
    assert by_id["quality_check"]["status"] == "completed"
    assert by_id["writeback_review"]["status"] == "completed"


def test_flow_marks_running_tasks_as_run_evidence():
    shots = [{"shot_index": 1, "prompt": "shot", "selected_image": "", "selected_video": ""}]
    tasks = [{"task_type": "image_gen", "status": "running"}]

    flow = evaluate_production_stages(shots=shots, tasks=tasks)
    by_id = {stage["id"]: stage for stage in flow}

    assert by_id["generate_keyframes"]["status"] == "running"
    assert by_id["generate_keyframes"]["source"] == "run_evidence"


def test_policy_gate_metadata_explains_blocking_rule():
    flow = evaluate_production_stages(shots=[], tasks=[])
    by_id = {stage["id"]: stage for stage in flow}

    assert by_id["plan_visual_assets"]["status"] == "blocked"
    assert by_id["plan_visual_assets"]["policy"]["gate_rules"][0]["missing"] == "shot_rows"


def test_human_feedback_intent_routes_to_precise_production_stage():
    assert infer_continue_action("剧本不够好，再润色一下") == "generate_story_plan"
    assert infer_continue_action("参考图不行，重新生成 seedream 产品图") == "plan_visual_assets"
    assert infer_continue_action("关键帧画面不行，重新出图") == "generate_keyframes"
    assert infer_continue_action("视频动作不行，重新生成视频") == "generate_videos"
    assert infer_continue_action("剪辑节奏不行，调整 BGM 和字幕") == "plan_final_edit"
    assert infer_continue_action("跳过，直接生成剪辑视频") == "plan_final_edit"
