import json

import pytest

from app.services.decision_mailbox import (
    complete_decision,
    mark_decision_rejected,
    submit_decision,
)


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class FakeDB:
    def __init__(self):
        self.executed = []

    async def execute(self, statement, params):
        self.executed.append((str(statement), params))
        return FakeResult("event-1")


def packet(action="generate_videos"):
    return {
        "status": "execute",
        "action": action,
        "mission": {
            "idempotency_key": f"run-1:{action}",
            "lane": "c_lane_production",
            "action": action,
        },
    }


@pytest.mark.asyncio
async def test_submit_decision_writes_pending_mailbox_event():
    db = FakeDB()

    decision_id = await submit_decision(
        db,
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        packet=packet(),
        parent_decision_id="parent-1",
        decision_rationale="Shot 1 needs video generation.",
        thinking_artifacts=[{"type": "planner_summary", "confidence": 0.8}],
    )

    assert decision_id == "event-1"
    params = db.executed[0][1]
    meta = json.loads(params["meta"])
    assert meta["mailbox"]["status"] == "pending"
    assert meta["mailbox"]["decision_id"] == "run-1:generate_videos"
    assert meta["mailbox"]["packet"]["action"] == "generate_videos"
    assert meta["mailbox"]["parent_decision_id"] == "parent-1"
    assert meta["mailbox"]["decision_rationale"] == "Shot 1 needs video generation."
    assert meta["mailbox"]["thinking_artifacts"][0]["type"] == "planner_summary"


@pytest.mark.asyncio
async def test_complete_decision_writes_completed_mailbox_event():
    db = FakeDB()

    await complete_decision(
        db,
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        decision_id="decision-1",
        result_ref={"queued_count": 1},
    )

    meta = json.loads(db.executed[0][1]["meta"])
    assert meta["mailbox"]["status"] == "completed"
    assert meta["mailbox"]["decision_id"] == "decision-1"
    assert meta["mailbox"]["result_ref"]["queued_count"] == 1


@pytest.mark.asyncio
async def test_mark_decision_rejected_records_reason():
    db = FakeDB()

    await mark_decision_rejected(
        db,
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        decision_id="decision-1",
        reason="lane cannot execute",
    )

    meta = json.loads(db.executed[0][1]["meta"])
    assert meta["mailbox"]["status"] == "rejected"
    assert meta["mailbox"]["reason"] == "lane cannot execute"
