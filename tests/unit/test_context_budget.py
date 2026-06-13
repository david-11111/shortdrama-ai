from app.services.context_budget import (
    ContextBudget,
    PromptMessageBudget,
    TRIM_MARKER,
    build_prompt_messages,
    limit_text,
    trim_messages,
)


def test_trim_messages_preserves_latest_user_request():
    messages = [
        {"role": "user", "content": "old " * 200},
        {"role": "assistant", "content": "answer " * 200},
        {"role": "user", "content": "final requirement must stay"},
    ]

    trimmed, report = trim_messages(
        messages,
        ContextBudget(max_messages=2, max_message_chars=100, max_total_chars=120),
    )

    assert trimmed[-1]["role"] == "user"
    assert trimmed[-1]["content"] == "final requirement must stay"
    assert report.dropped_messages >= 1


def test_trim_messages_reports_truncation_and_budget_reason():
    trimmed, report = trim_messages(
        [{"role": "user", "content": "x" * 5000}],
        ContextBudget(max_messages=4, max_message_chars=200, max_total_chars=400),
    )

    assert len(trimmed) == 1
    assert TRIM_MARKER.strip() in trimmed[0]["content"]
    assert report.truncated_messages == 1
    assert report.output_chars <= 220


def test_trim_messages_never_exceeds_total_budget_when_preserving_latest_user():
    trimmed, report = trim_messages(
        [
            {"role": "assistant", "content": "old " * 200},
            {"role": "user", "content": "final " * 200},
        ],
        ContextBudget(max_messages=2, max_message_chars=1000, max_total_chars=120),
    )

    assert trimmed[-1]["role"] == "user"
    assert sum(len(msg["content"]) for msg in trimmed) <= 120
    assert report.output_chars <= 120


def test_limit_text_keeps_head_and_tail():
    text = "A" * 120 + "MIDDLE" + "Z" * 120
    compact = limit_text(text, 80)

    assert compact.startswith("A")
    assert compact.endswith("Z")
    assert TRIM_MARKER.strip() in compact
    assert len(compact) <= 80


def test_build_prompt_messages_obeys_total_budget_and_preserves_final_user():
    history = [
        {"role": "user", "content": "old user " * 200},
        {"role": "assistant", "content": "old answer " * 200},
        {"role": "user", "content": "middle user " * 200},
    ]
    messages, report = build_prompt_messages(
        system_prompt="system " * 500,
        history=history,
        final_user_prompt="final request must remain " + ("x" * 2000),
        budget=PromptMessageBudget(
            max_system_chars=500,
            max_user_chars=600,
            max_total_chars=1200,
            history_budget=ContextBudget(max_messages=3, max_message_chars=300, max_total_chars=700),
        ),
    )

    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "final request must remain" in messages[-1]["content"]
    assert sum(len(msg["content"]) for msg in messages) <= 1200
    assert report.total_chars <= 1200


def test_build_prompt_messages_never_exceeds_total_budget():
    messages, report = build_prompt_messages(
        system_prompt="s" * 5000,
        history=[],
        final_user_prompt="u" * 5000,
        budget=PromptMessageBudget(
            max_system_chars=5000,
            max_user_chars=5000,
            max_total_chars=100,
        ),
    )

    assert report.total_chars <= 100
    assert report.total_chars == sum(len(msg["content"]) for msg in messages)
    assert messages[-1]["role"] == "user"
