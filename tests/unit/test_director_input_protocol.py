from app.services.director_input_protocol import (
    DIRECTOR_PROTOCOL_VERSION,
    build_director_input_protocol,
    director_protocol_allows_next_step,
    director_protocol_prompt_block,
)


def test_build_director_input_protocol_defaults_to_live_action_guardrails():
    protocol = build_director_input_protocol(
        {
            "task_type": "reference_image",
            "asset_kind": "character",
            "creative_intent": "lock live action role reference",
            "subject": {"name": "Lu Chenzhou"},
        }
    )

    assert protocol["version"] == DIRECTOR_PROTOCOL_VERSION
    assert protocol["project_style"].startswith("photorealistic live-action")
    assert "anime" in protocol["global_must_avoid"]
    assert protocol["approval_status"] == "draft"
    assert protocol["allowed_next_step"] is False
    assert protocol["subject"]["name"] == "Lu Chenzhou"


def test_director_protocol_prompt_block_contains_execution_constraints():
    protocol = build_director_input_protocol(
        {
            "task_type": "reference_image",
            "asset_kind": "character",
            "creative_intent": "show someone used to being ignored",
            "must_keep": ["real fabric", "restrained eyes"],
            "must_avoid": ["anime face", "game costume"],
        }
    )

    block = director_protocol_prompt_block(protocol, target="seedream")

    assert "[director_input_protocol_v1]" in block
    assert "project_style=photorealistic live-action" in block
    assert "creative_intent=show someone used to being ignored" in block
    assert "must_keep=real fabric; restrained eyes" in block
    assert "must_avoid=anime; manga; cartoon" in block
    assert "anime face" in block


def test_director_protocol_allows_next_step_only_when_approved():
    draft = build_director_input_protocol({"approval_status": "draft", "allowed_next_step": True})
    approved = build_director_input_protocol({"approval_status": "approved", "allowed_next_step": True})

    assert director_protocol_allows_next_step(draft) is False
    assert director_protocol_allows_next_step(approved) is True
