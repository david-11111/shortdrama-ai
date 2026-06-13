from app.services.agent_control_tools import (
    classify_control_intent,
    diagnose_keyframe_pool_from_snapshot,
    diagnose_outputs_from_snapshot,
    diagnose_provider_writeback_from_snapshot,
    diagnose_script_from_snapshot,
    diagnose_tasks_from_snapshot,
    render_output_diagnostic_answer,
    render_keyframe_pool_diagnostic_answer,
    render_provider_writeback_answer,
    render_script_diagnostic_answer,
    render_task_diagnostic_answer,
)


def test_control_intent_detects_output_display_diagnostic():
    intent = classify_control_intent("有几张参考图没显示，查一下原因")

    assert intent is not None
    assert intent.intent_type == "ui_diagnostic"
    assert intent.tool_name == "diagnose_outputs"
    assert intent.action == "status_query"
    assert intent.dispatch_ready is True


def test_control_intent_detects_missing_image_repair():
    intent = classify_control_intent("把之前没显示的补上，里面有提示词")

    assert intent is not None
    assert intent.intent_type == "production_action"
    assert intent.tool_name == "repair_missing_images"
    assert intent.action == "generate_keyframes"


def test_diagnose_outputs_finds_signed_urls_and_empty_selected_images():
    snapshot = {
        "outputs": {
            "summary": {"image_count": 2, "shot_count": 3},
            "images": [
                {"url": "https://cdn.test/a.png?Expires=100&Signature=abc", "shot_index": 1, "kind": "selected_image"},
                {"url": "/storage/project/shot-2.png", "shot_index": 2, "kind": "selected_image"},
            ],
            "shots": [
                {"shot_index": 1, "selected_image": "https://cdn.test/a.png?Expires=100&Signature=abc"},
                {"shot_index": 2, "selected_image": "/storage/project/shot-2.png"},
                {"shot_index": 3, "selected_image": ""},
            ],
        }
    }

    result = diagnose_outputs_from_snapshot(snapshot)

    assert result["tool_name"] == "diagnose_outputs"
    assert len(result["images"]) == 2
    assert result["risky_images"][0]["shot_index"] == 1
    assert result["empty_image_rows"] == [{"shot_index": 3, "status": "", "reason": "selected_image 为空"}]
    assert result["likely_cause"] == "selected_image_missing"
    assert result["recommended_action"] == "repair_missing_images"


def test_render_output_diagnostic_answer_is_evidence_based():
    diagnosis = {
        "images": [{"shot_index": 1, "reason": "签名 URL 可能过期或被拒绝"}],
        "broken_images": [],
        "risky_images": [{"shot_index": 1, "reason": "签名 URL 可能过期或被拒绝"}],
        "empty_image_rows": [{"shot_index": 3}],
        "recommended_action": "repair_missing_images",
    }

    answer = render_output_diagnostic_answer(
        diagnosis,
        current_status="dispatching",
        active_tasks={"count": 0, "items": [], "task_ids": [], "statuses": []},
    )

    assert "记录到 1 张参考图/关键帧" in answer
    assert "第 1 镜" in answer
    assert "第 3" in answer
    assert "补齐没有 selected_image" in answer


def test_control_intent_detects_task_and_provider_diagnostics():
    task_intent = classify_control_intent("task stuck in queue")
    provider_intent = classify_control_intent("seedance result did not writeback selected_video")

    assert task_intent is not None
    assert task_intent.tool_name == "diagnose_tasks"
    assert provider_intent is not None
    assert provider_intent.tool_name == "diagnose_provider_writeback"


def test_control_intent_detects_script_diagnostic():
    intent = classify_control_intent("把前三秒钩子和产品卖点加强，重写剧本分镜")

    assert intent is not None
    assert intent.intent_type == "script_diagnostic"
    assert intent.tool_name == "diagnose_script"
    assert intent.action == "status_query"


def test_control_intent_prefers_final_edit_when_script_is_context():
    intent = classify_control_intent("根据剧本情况自行剪辑，配音，配字幕，配音乐")

    assert intent is not None
    assert intent.intent_type == "production_action"
    assert intent.tool_name == "plan_final_edit"
    assert intent.action == "plan_final_edit"


def test_control_intent_routes_missing_final_edit_question_to_output_diagnostic():
    intent = classify_control_intent("为什么还没剪辑成片")

    assert intent is not None
    assert intent.intent_type == "ui_diagnostic"
    assert intent.tool_name == "diagnose_outputs"
    assert intent.action == "status_query"


def test_control_intent_detects_keyframe_pool_diagnostic():
    intent = classify_control_intent("第3镜多做几张图，角度丰富一点")

    assert intent is not None
    assert intent.intent_type == "keyframe_pool_diagnostic"
    assert intent.tool_name == "diagnose_keyframe_pool"
    assert intent.action == "status_query"


def test_diagnose_keyframe_pool_recommends_batch_generation_for_multi_angle_request():
    snapshot = {
        "outputs": {
            "shots": [
                {
                    "shot_index": 3,
                    "prompt": "主角拿起产品，表情犹豫",
                    "selected_image": "https://cdn.test/shot-3-main.png",
                    "image_candidates": [{"url": "https://cdn.test/shot-3-alt.png", "quality_score": 0.78}],
                    "status": "image_done",
                }
            ],
            "images": [],
        }
    }

    result = diagnose_keyframe_pool_from_snapshot(snapshot, instruction="第3镜多做几张图，角度丰富一点")
    answer = render_keyframe_pool_diagnostic_answer(result)

    assert result["tool_name"] == "diagnose_keyframe_pool"
    assert result["summary"]["candidate_count"] == 2
    assert result["summary"]["selected_count"] == 1
    assert result["summary"]["target_shots"] == [3]
    assert result["summary"]["variation_strategy"] == "angle"
    assert result["recommended_action"] == "generate_keyframe_batch"
    assert result["draft_prompts"]
    assert "图片池" in answer
    assert "generate_keyframes" in answer


def test_diagnose_script_extracts_revision_requirements():
    snapshot = {
        "outputs": {
            "script": {"items": [{"content": "第一镜开场，第二镜展示产品。"}], "content": "第一镜开场，第二镜展示产品。"},
            "director_notes": [{"title": "导演建议", "content": "开场要更强。", "source": "agent_steps"}],
            "shots": [
                {"shot_index": 1, "prompt": "主角推门进入", "duration": 3, "status": "planned"},
                {"shot_index": 2, "prompt": "产品特写", "duration": 4, "status": "planned"},
            ],
        }
    }

    result = diagnose_script_from_snapshot(snapshot, instruction="第1镜前三秒钩子太弱，强化产品卖点和台词")
    answer = render_script_diagnostic_answer(result)

    assert result["tool_name"] == "diagnose_script"
    assert result["summary"]["has_script"] is True
    assert result["extracted_requirements"]["hook"] is True
    assert result["extracted_requirements"]["selling_point"] is True
    assert result["extracted_requirements"]["dialogue"] is True
    assert result["extracted_requirements"]["target_shots"] == [1]
    assert result["recommended_action"] == "revise_story_plan"
    assert "剧本链路" in answer
    assert "generate_story_plan" in answer


def test_diagnose_tasks_recommends_retry_for_failed_video():
    snapshot = {
        "tasks": [
            {"task_id": "task-1", "task_type": "video_gen", "status": "failed", "error_message": "provider timeout", "payload": {"shot_index": 2}},
            {"task_id": "task-2", "task_type": "image_gen", "status": "completed", "payload": {"shot_index": 1}, "result": {"image_url": "https://cdn.test/1.png"}},
        ]
    }

    result = diagnose_tasks_from_snapshot(snapshot)
    answer = render_task_diagnostic_answer(result)

    assert result["failed_tasks"][0]["task_id"] == "task-1"
    assert result["recommended_action"] == "retry_failed_videos"
    assert "失败" in answer
    assert "重试失败视频" in answer


def test_diagnose_provider_writeback_finds_result_not_written_to_shot_rows():
    snapshot = {
        "tasks": [
            {
                "task_id": "task-1",
                "task_type": "image_gen",
                "status": "completed",
                "payload": {"shot_index": 3, "provider": "seedream"},
                "result": {"image_url": "https://cdn.test/shot-3.png"},
            }
        ],
        "outputs": {
            "shots": [{"shot_index": 3, "selected_image": "", "selected_video": ""}],
        },
        "events": {"user": [{"phase": "writeback_selected_image", "status": "done", "summary": "writeback attempted"}]},
    }

    result = diagnose_provider_writeback_from_snapshot(snapshot)
    answer = render_provider_writeback_answer(result)

    assert result["missing_image_writeback"] == [3]
    assert result["recommended_action"] == "repair_missing_images"
    assert "未写回镜头" in answer
