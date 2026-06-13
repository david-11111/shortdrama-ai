from app.services.provider_prompt_adapter import adapt_provider_payload


def _gold_jewelry_semantic() -> dict:
    return {
        "intent_brief": {
            "version": "intent_brief_v1",
            "raw_instruction": "我想做一段30秒的黄金首饰广告视频，电影级别，小金饰品牌调性，高级、精致、有光影质感",
            "category": "commercial_video",
            "duration_sec": 30,
            "tone": ["电影级", "高级", "精致", "光影质感"],
            "must_keep": ["黄金首饰是画面主角", "品牌调性优先于剧情冲突"],
            "must_avoid": ["短剧冲突", "廉价电商促销风"],
            "visual_language": {
                "material": "gold jewelry, polished metal, fine highlights",
                "lighting": "cinematic contrast, controlled highlights",
            },
        },
        "constraint_packet": {
            "version": "constraint_packet_v1",
            "must_keep": ["黄金首饰是画面主角", "品牌调性优先于剧情冲突"],
            "must_avoid": ["短剧冲突", "廉价电商促销风"],
            "tone": ["电影级", "高级", "精致", "光影质感"],
            "visual_language": {
                "material": "gold jewelry, polished metal, fine highlights",
                "lighting": "cinematic contrast, controlled highlights",
            },
            "quality_bar": ["结果必须符合用户原始意图", "生产动作不得丢失品牌、主体、风格和负面约束"],
        },
    }


def test_doubao_adapter_injects_story_constraints_into_system_prompt():
    payload = {
        "system_prompt": "Generate a storyboard JSON.",
        "prompt": "gold jewelry ad",
        **_gold_jewelry_semantic(),
    }

    adapted = adapt_provider_payload(payload, task_type="generate_story_plan", provider="doubao")

    assert adapted["provider_adapter"]["constraints_applied"] is True
    assert "agent_control_constraints_v1" in adapted["system_prompt"]
    assert "黄金首饰是画面主角" in adapted["system_prompt"]
    assert "短剧冲突" in adapted["system_prompt"]
    assert "do not drift into generic short-drama conflict" in adapted["system_prompt"]
    assert "raw_user_intent=" in adapted["prompt"]


def test_seedream_adapter_injects_keyframe_constraints_and_negative_prompt():
    payload = {
        "provider": "seedream",
        "prompt": "macro shot of a gold ring on black velvet",
        **_gold_jewelry_semantic(),
    }

    adapted = adapt_provider_payload(payload, task_type="image_gen", provider="seedream")

    assert adapted["provider_adapter"]["constraints_applied"] is True
    assert "agent_control_constraints_v1" in adapted["prompt"]
    assert "黄金首饰是画面主角" in adapted["prompt"]
    assert "gold jewelry, polished metal" in adapted["prompt"]
    assert "短剧冲突" in adapted["negative_prompt"]
    assert "廉价电商促销风" in adapted["negative_prompt"]


def test_seedance_adapter_injects_video_continuity_constraints_and_negative_prompt():
    payload = {
        "provider": "seedance",
        "prompt": "slow dolly across the gold necklace",
        "image_url": "https://example.test/keyframe.png",
        **_gold_jewelry_semantic(),
    }

    adapted = adapt_provider_payload(payload, task_type="video_gen", provider="seedance")

    assert adapted["provider_adapter"]["constraints_applied"] is True
    assert "agent_control_constraints_v1" in adapted["prompt"]
    assert "Animate from the selected keyframe" in adapted["prompt"]
    assert "品牌调性优先于剧情冲突" in adapted["prompt"]
    assert "短剧冲突" in adapted["negative_prompt"]


def test_adapter_is_idempotent_and_legacy_payloads_still_get_quality_controls():
    payload = {"provider": "seedream", "prompt": "product close-up"}

    first = adapt_provider_payload(payload, task_type="image_gen", provider="seedream")
    second = adapt_provider_payload(first, task_type="image_gen", provider="seedream")

    assert first["provider_adapter"]["version"] == "provider_prompt_adapter_v1"
    assert first["provider_adapter"]["constraints_applied"] is False
    assert second["prompt"].count("agent_control_constraints_v1") == 0
