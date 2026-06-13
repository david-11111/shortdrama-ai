import pytest


@pytest.mark.asyncio
async def test_continue_main_chain_after_task_ignores_non_dispatchable(monkeypatch):
    from app.services import main_chain_terminal

    async def fake_observe(task_id):
        return {
            "packet_version": "main_run_chain_phase1",
            "status": "wait",
            "action": "wait_for_tasks",
            "stage_id": "",
            "selected_lane": "main_chain",
            "dispatchable": False,
            "allowed": False,
            "reason": "Active production tasks are still running.",
            "missing": [],
            "fallback_action": "",
            "active_task_count": 1,
            "failed_task_count": 0,
            "allowed_writes": [],
            "evidence": {},
            "evidence_refs": [],
            "candidate_actions": [],
            "success_criteria": [],
            "budget": {},
            "risk": {},
            "failure_policy": {},
            "mission": {},
        }

    async def fake_context(session, task_id):
        return {
            "run_id": "run-1",
            "project_id": "project-1",
            "user_id": 7,
            "user_tier": "pro",
            "run_mode": "autopilot",
        }

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    monkeypatch.setattr(main_chain_terminal, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(main_chain_terminal, "observe_task_terminal_decision_tick", fake_observe)
    monkeypatch.setattr(main_chain_terminal, "task_run_context_for_main_chain", fake_context)

    observed = {"observer_task_id": None}

    async def fake_active_observer(session, task_id):
        observed["observer_task_id"] = task_id
        return []

    monkeypatch.setattr(main_chain_terminal.main_chain_observer, "observe_task_writeback", fake_active_observer)

    async def fake_apply(session, *, packet, context, handlers):
        return main_chain_terminal.MainChainResult("waiting", False, packet.as_dict())

    monkeypatch.setattr(main_chain_terminal, "apply_decision_packet", fake_apply)

    result = await main_chain_terminal.continue_main_chain_after_task("11111111-1111-1111-1111-111111111111")

    assert result["status"] == "waiting"
    assert result["dispatched"] is False
    assert observed["observer_task_id"] == "11111111-1111-1111-1111-111111111111"
