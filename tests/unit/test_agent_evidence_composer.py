from app.services.agent_evidence_composer import composition_from_payload


def test_composer_schema_rejects_disallowed_action():
    composition = composition_from_payload(
        {
            "reply": "我查了证据，先不要重生。",
            "recommended_action": "drop_database",
            "dispatch_ready": True,
            "reason": "bad action",
            "needs_human": False,
        },
        allowed_actions=["repair_missing_images"],
    )

    assert composition is not None
    assert composition.recommended_action == ""
    assert composition.dispatch_ready is False


def test_composer_schema_allows_whitelisted_action():
    composition = composition_from_payload(
        {
            "reply": "第 3 镜没有 selected_image，建议补齐。",
            "recommended_action": "repair_missing_images",
            "dispatch_ready": True,
            "reason": "tool result shows missing selected_image",
            "needs_human": False,
        },
        allowed_actions=["repair_missing_images"],
    )

    assert composition is not None
    assert composition.recommended_action == "repair_missing_images"
    assert composition.dispatch_ready is True
    assert composition.needs_human is False


def test_composer_schema_allows_registered_director_note_revision():
    composition = composition_from_payload(
        {
            "reply": "导演建议需要重写到分镜约束里，下一步改剧本分镜。",
            "recommended_action": "revise_director_notes",
            "dispatch_ready": True,
            "reason": "script evidence includes director notes revision",
            "needs_human": False,
        },
        allowed_actions=["revise_director_notes"],
    )

    assert composition is not None
    assert composition.recommended_action == "revise_director_notes"
    assert composition.dispatch_ready is True


def test_composer_requires_reply():
    assert composition_from_payload(
        {
            "recommended_action": "repair_missing_images",
            "dispatch_ready": True,
        },
        allowed_actions=["repair_missing_images"],
    ) is None
