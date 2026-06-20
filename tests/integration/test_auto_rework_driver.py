"""Integration tests for _auto_rework_driver.

Requires a real PostgreSQL database (via conftest.py fixtures).
Mocks Redis, recommend_next_action, should_escalate, dispatch_agent_action,
continue_project_brain, and asyncio.sleep to control the driver.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.agent_action_executor import ActionExecutionResult

pytestmark = [pytest.mark.integration]


class FakeRedis:
    _store: dict[str, str] = {}

    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()

    async def setnx(self, key: str, value: str) -> int:
        if key in self._store:
            return 0
        self._store[key] = value
        return 1

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def expire(self, key: str, ttl: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def close(self) -> None:
        pass


async def _noop_sleep(_seconds: float) -> None:
    pass


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def project_with_shots(db_session, test_user_pro):
    pid = "rework-test-" + uuid.uuid4().hex[:8]
    uid = test_user_pro["id"]
    await db_session.execute(
        text("INSERT INTO projects (project_id, name, user_id, status) VALUES (:pid, 'at', :uid, 'active')"),
        {"pid": pid, "uid": uid},
    )
    for idx in range(3):
        await db_session.execute(
            text("""INSERT INTO shot_rows (project_id, user_id, shot_index, prompt, duration, status,
                selected, selected_image, selected_video, image_candidates_json, video_variants_json)
                VALUES (:pid, :uid, :idx, :p, 5.0, 'pending', true, :si, :sv, '[]'::jsonb, '[]'::jsonb)"""),
            {"pid": pid, "uid": uid, "idx": idx, "p": f"s{idx}", "si": f"/i/{idx}.png", "sv": "" if idx < 2 else f"/v/{idx}.mp4"},
        )
    yield pid
    await db_session.execute(text("DELETE FROM shot_rows WHERE project_id = :pid"), {"pid": pid})
    await db_session.execute(text("DELETE FROM projects WHERE project_id = :pid"), {"pid": pid})


@pytest_asyncio.fixture
async def agent_run(db_session, test_user_pro, project_with_shots):
    from app.services.agent_runtime import create_agent_run
    rid = await create_agent_run(db_session, project_id=project_with_shots, user_id=test_user_pro["id"], goal="t", mode="step")
    await db_session.execute(text("UPDATE agent_runs SET status = 'running' WHERE id = CAST(:rid AS UUID)"), {"rid": str(rid)})
    yield str(rid)


@pytest_asyncio.fixture
async def production_run(db_session, test_user_pro, agent_run, project_with_shots):
    await db_session.execute(
        text("INSERT INTO video_production_runs (agent_run_id, project_id, user_id, status, current_stage) VALUES (CAST(:r AS UUID), :p, :u, 'running', 'gv')"),
        {"r": agent_run, "p": project_with_shots, "u": test_user_pro["id"]},
    )
    yield


# ── Helpers ────────────────────────────────────────────────────────────────


def _mocks(ar, db_session, monkeypatch):
    """Standard mocks: Redis, sleep, get_status (running→completed), prod_state, audit."""
    monkeypatch.setattr(ar, "aioredis", type("_FM", (), {"Redis": FakeRedis}))
    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    sc = [0]
    async def gs(*a, **kw):
        sc[0] += 1
        return "completed" if sc[0] >= 2 else "running"
    monkeypatch.setattr(ar, "_get_run_status_for_update", gs)

    async def ps(*a, **kw):
        return {"shots": [{"shot_index": 0}, {"shot_index": 1}], "tasks": [], "production_run": None}
    monkeypatch.setattr(ar, "_run_production_state", ps)

    ev = []
    async def au(*, user_id, action, run_id, project_id, payload=None):
        ev.append({"action": action, "run_id": run_id, "payload": payload})
    monkeypatch.setattr(ar, "_audit_agent_run_action", au)
    return ev


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_rework_driver_normal_flow(db_session, test_user_pro, project_with_shots, agent_run, production_run, monkeypatch):
    from app.routes import agent_runs as ar
    FakeRedis._store = {}
    ev = _mocks(ar, db_session, monkeypatch)

    rr = {"from_stage": "rv", "rework_to": "gv", "affects_shots": [0, 1], "max_retries": 3, "retry_exhausted_action": "skip_shot"}
    cc = [0]

    def rn(**kw):
        cc[0] += 1
        return {"action": "gv", "rework_redirect": rr} if cc[0] == 1 else {"action": "wr"}

    from app.services import state_machine as sm
    monkeypatch.setattr(sm, "recommend_next_action", rn)
    monkeypatch.setattr(sm, "should_escalate", lambda rw, a: "proceed")

    dc = [False]
    async def dd(ctx, **kw):
        dc[0] = True
        return ActionExecutionResult(status="requested_action", executor="t", audit_action="t")
    monkeypatch.setattr(ar, "dispatch_agent_action", dd)
    monkeypatch.setattr(ar, "continue_project_brain", lambda *a, **kw: None)

    await ar._auto_rework_driver(run_id=agent_run, project_id=project_with_shots, user_id=test_user_pro["id"])
    assert FakeRedis._store.get(f"rework_attempt:{agent_run}") == "1"
    assert f"rework_in_progress:{agent_run}" not in FakeRedis._store
    assert dc[0]
    assert any(e["action"] == "agent_run.rework_auto" for e in ev)


@pytest.mark.asyncio
async def test_auto_rework_driver_skip_shot(db_session, test_user_pro, project_with_shots, agent_run, production_run, monkeypatch):
    from app.routes import agent_runs as ar
    FakeRedis._store = {}
    ev = _mocks(ar, db_session, monkeypatch)

    rr = {"from_stage": "rv", "rework_to": "gv", "affects_shots": [0, 1], "max_retries": 3, "retry_exhausted_action": "skip_shot"}

    def rn(**kw):
        return {"action": "gv", "rework_redirect": rr}

    from app.services import state_machine as sm
    monkeypatch.setattr(sm, "recommend_next_action", rn)
    monkeypatch.setattr(sm, "should_escalate", lambda rw, a: "skip_shot")

    # Track UPDATE calls via monkeypatch on ar.db.execute won't work — it uses internal import.
    # Instead, verify via audit event that skip_shot path executed.
    await ar._auto_rework_driver(run_id=agent_run, project_id=project_with_shots, user_id=test_user_pro["id"])
    assert any(e["action"] == "agent_run.rework_auto_skip" for e in ev)


@pytest.mark.asyncio
async def test_auto_rework_driver_change_provider(db_session, test_user_pro, project_with_shots, agent_run, production_run, monkeypatch):
    from app.routes import agent_runs as ar
    FakeRedis._store = {}
    ev = _mocks(ar, db_session, monkeypatch)

    rr = {"from_stage": "rv", "rework_to": "gv", "affects_shots": [0, 1], "max_retries": 3, "retry_exhausted_action": "change_provider", "current_provider": "kling"}

    def rn(**kw):
        return {"action": "gv", "rework_redirect": rr}

    from app.services import state_machine as sm
    monkeypatch.setattr(sm, "recommend_next_action", rn)
    monkeypatch.setattr(sm, "should_escalate", lambda rw, a: "change_provider")

    obs = {}
    async def rst(db, *, run_id, project_id, user_id):
        obs["reset"] = True
    monkeypatch.setattr(ar, "_reset_retryable_video_shots", rst)

    async def ct(project_id, body, db, current_user):
        obs["continue"] = True
        obs["provider"] = body.get("video_provider")
    monkeypatch.setattr(ar, "continue_project_brain", ct)

    await ar._auto_rework_driver(run_id=agent_run, project_id=project_with_shots, user_id=test_user_pro["id"])
    assert obs.get("reset") is True
    assert obs.get("continue") is True
    assert obs.get("provider") == "kling"  # PROVIDER_FALLBACK[0]
    assert any(e["action"] == "agent_run.rework_auto_change_provider" for e in ev)


@pytest.mark.asyncio
async def test_auto_rework_driver_all_providers_exhausted(db_session, test_user_pro, project_with_shots, agent_run, production_run, monkeypatch):
    from app.routes import agent_runs as ar
    pk = f"rework_provider_idx:{agent_run}"
    FakeRedis._store = {pk: "5"}
    ev = _mocks(ar, db_session, monkeypatch)

    rr = {"from_stage": "rv", "rework_to": "gv", "affects_shots": [0, 1], "max_retries": 3, "retry_exhausted_action": "change_provider"}

    def rn(**kw):
        return {"action": "gv", "rework_redirect": rr}

    from app.services import state_machine as sm
    monkeypatch.setattr(sm, "recommend_next_action", rn)
    monkeypatch.setattr(sm, "should_escalate", lambda rw, a: "change_provider")

    called = False
    async def ct(**kw):
        nonlocal called
        called = True
    monkeypatch.setattr(ar, "continue_project_brain", ct)

    await ar._auto_rework_driver(run_id=agent_run, project_id=project_with_shots, user_id=test_user_pro["id"])
    assert not called


@pytest.mark.asyncio
async def test_auto_rework_driver_redis_unavailable(db_session, test_user_pro, project_with_shots, agent_run, production_run, monkeypatch, caplog):
    import logging
    from app.routes import agent_runs as ar

    class B:
        @classmethod
        def from_url(cls, *a, **kw):
            raise ConnectionError("no redis")
    monkeypatch.setattr(ar, "aioredis", type("_BM", (), {"Redis": B}))
    caplog.set_level(logging.WARNING)
    await ar._auto_rework_driver(run_id=agent_run, project_id=project_with_shots, user_id=test_user_pro["id"])
    assert any("cannot connect to Redis" in m for m in caplog.messages)


@pytest.mark.asyncio
async def test_auto_rework_driver_exits_on_completed_run(db_session, test_user_pro, project_with_shots, agent_run, production_run, monkeypatch):
    from app.routes import agent_runs as ar
    await db_session.execute(text("UPDATE agent_runs SET status = 'completed' WHERE id = CAST(:r AS UUID)"), {"r": agent_run})
    FakeRedis._store = {}
    monkeypatch.setattr(ar, "aioredis", type("_FM", (), {"Redis": FakeRedis}))

    called = False
    def rn(**kw):
        nonlocal called
        called = True
        return {}
    from app.services import state_machine as sm
    monkeypatch.setattr(sm, "recommend_next_action", rn)

    await ar._auto_rework_driver(run_id=agent_run, project_id=project_with_shots, user_id=test_user_pro["id"])
    assert not called
