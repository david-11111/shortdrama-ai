from app.services.agent_runtime_contracts import RuntimeFeedback
from app.services.main_chain_feedback import feedback_event_payload


def test_feedback_event_payload_user_visibility():
    payload = feedback_event_payload(
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        feedback=RuntimeFeedback(
            status="executing",
            summary="Generating video for shot 1.",
            next_step="Wait for writeback verification.",
            progress={"current": 2, "total": 5, "percentage": 40},
        ),
    )

    assert payload["source"] == "main_chain"
    assert payload["event_type"] == "feedback"
    assert payload["visibility"] == "user"
    assert payload["meta"]["feedback"]["progress"]["percentage"] == 40


def test_feedback_event_payload_debug_visibility():
    payload = feedback_event_payload(
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        feedback=RuntimeFeedback(
            status="observing",
            summary="Raw packet observed.",
            audience="debug",
        ),
    )

    assert payload["visibility"] == "debug"
