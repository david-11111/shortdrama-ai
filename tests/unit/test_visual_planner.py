from app.services.visual_planner import build_visual_plan


def test_visual_plan_turns_preflight_missing_refs_into_actions():
    plan = build_visual_plan(
        [
            {
                "shot_index": 3,
                "prompt": "顾客在金店柜台前拿出黄金手镯，店员准备称重报价",
                "scene_refs": [],
                "prop_refs": [],
                "director_preflight": {
                    "risk_level": "warning",
                    "required_refs": ["scene", "prop"],
                    "missing_refs": ["scene", "prop"],
                    "risks": [
                        {"code": "missing_scene_ref", "reason": "需要固定金店柜台空间"},
                        {"code": "missing_prop_ref", "reason": "需要固定黄金和称重道具"},
                    ],
                },
            }
        ],
        [],
    )

    shot_plan = plan["shot_plans"][0]
    assert shot_plan["missing_kinds"] == ["scene", "prop"]
    assert plan["action_count"] == 2
    assert [item["title"] for item in shot_plan["action_items"]] == [
        "生成金店柜台场景参考",
        "生成黄金道具参考",
    ]
    assert shot_plan["action_items"][0]["target_ref_field"] == "scene_refs"
    assert shot_plan["action_items"][1]["target_ref_field"] == "prop_refs"


def test_visual_plan_prefers_binding_existing_references():
    plan = build_visual_plan(
        [
            {
                "shot_index": 1,
                "prompt": "店员在金店柜台前报价",
                "director_preflight": {
                    "risk_level": "warning",
                    "required_refs": ["scene"],
                    "missing_refs": ["scene"],
                },
            }
        ],
        [
            {
                "asset_id": "scene-1",
                "asset_type": "image",
                "file_url": "/assets/gold-store.png",
                "metadata_json": {
                    "asset_kind": "scene",
                    "entity_name": "金店柜台主场景",
                },
            }
        ],
    )

    action = plan["shot_plans"][0]["action_items"][0]
    assert action["action_type"] == "bind_existing"
    assert action["title"] == "绑定已有场景参考"
    assert action["recommended_asset_ids"] == ["scene-1"]
