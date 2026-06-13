# Main Run Chain Phase 1 Post-Implementation Handoff

**Date:** 2026-05-27  
**Status:** Phase 1 backend skeleton implemented; real database end-to-end validation still pending.

## Read This First Next Session

Start by reading these files in this order:

1. `docs/superpowers/specs/2026-05-26-main-run-chain-design.md`
2. `docs/superpowers/plans/2026-05-26-main-run-chain-handoff.md`
3. `docs/superpowers/plans/2026-05-26-authoritative-run-chain-phase-1-decision-packet-central-dispatch-skeleton.md`
4. `docs/superpowers/plans/2026-05-27-main-run-chain-phase-1-post-implementation-handoff.md`

Do not reopen the already-approved main-chain direction. The target remains:

- one authoritative run chain,
- A lane as project/fact synthesis,
- B lane as agent-run and DeepSeek interaction/explanation,
- C lane as production execution,
- no peer orchestration paths.

## What Was Implemented

Phase 1 backend skeleton was implemented.

Changed code:

- `app/services/run_coordination.py`
  - Expanded `DecisionTickResult` from a thin read-only tick into a Phase 1 decision packet.
  - Added fields including:
    - `packet_version`
    - `selected_lane`
    - `dispatchable`
    - `allowed_writes`
    - `evidence_refs`
    - `budget`
    - `risk`
    - `failure_policy`
    - `mission`

- `app/services/run_dispatch_gateway.py`
  - New central dispatch gateway service.
  - Validates dispatchable authoritative packets.
  - Updates the owning `agent_run`.
  - Publishes a `dispatch_gateway` decision event.
  - Calls existing compatibility handlers for this slice.

- `app/routes/workbench.py`
  - Direct `brain/continue` production actions now route through `_dispatch_production_action(...)`.
  - Post-planning production dispatch also routes through `_dispatch_production_action(...)`.
  - `_dispatch_production_action(...)` builds a compatibility decision packet and calls `dispatch_authoritative_packet(...)`.
  - Existing `_continue_generate_keyframes`, `_continue_generate_videos`, `_continue_plan_visual_assets`, and `_continue_plan_final_edit` remain as compatibility handlers.

Changed tests:

- `tests/unit/test_run_coordination.py`
- `tests/unit/test_run_dispatch_gateway.py`
- `tests/unit/test_project_continue.py`

## Verification Already Run

Command:

```bash
python -m pytest tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_project_continue.py tests/unit/test_task_shared_run_coordination_hook.py tests/unit/test_agent_run_state_machine.py -q
```

Result:

```text
50 passed in 2.47s
```

Integration command attempted:

```bash
python -m pytest tests/integration/test_agent_events.py -q -k decision_tick -rs
```

Result:

```text
SKIPPED [1] tests\integration\test_agent_events.py: TEST_DATABASE_URL is not available
```

## What Is Not Proven Yet

Do not claim that the whole real chain is fully end-to-end verified yet.

Not yet proven in a real DB-backed run:

1. `POST /api/projects/{project_id}/brain/continue`
2. `create_agent_run(...)`
3. `dispatch_authoritative_packet(...)`
4. task rows inserted and queued
5. worker or `_persist_and_publish(...)` terminal path
6. `observe_task_terminal_decision_tick(...)`
7. persisted `agent_events` decision tick with the enriched Phase 1 packet

Reason:

- local integration DB is unavailable because `TEST_DATABASE_URL` is not set/reachable in this environment.

## Important Boundary Still Open

`brain/continue` production dispatch has been routed through the new gateway.

However, the separate production-run entry still creates its own run path in `app/routes/workbench.py` around the `create_agent_run(...)` call inside the production-run route.

Next session should treat that as a remaining architecture question:

- either wrap it behind the gateway,
- or explicitly mark it compatibility-only,
- or add a test that proves it cannot become a peer orchestration path.

## Git State

Git remains unusable in this workspace.

Observed failure:

```text
fatal: not a git repository: C:/tmp/saas-git
```

Do not plan work that depends on commits, branches, PRs, or git diff until this is fixed.

## Recommended Next Step

Before adding new features, run a real-chain validation pass.

Priority order:

1. Restore or provide `TEST_DATABASE_URL`.
2. Run:

```bash
python -m pytest tests/integration/test_agent_events.py -q -k decision_tick -rs
```

3. If the integration test still skips or fails, fix the environment or the actual chain before expanding scope.
4. Add a focused test or design decision for the separate production-run route so it cannot remain a peer orchestrator.

## Short Startup Prompt For Next Session

Use this after clearing context:

```text
Continue from:
docs/superpowers/plans/2026-05-27-main-run-chain-phase-1-post-implementation-handoff.md

Do not re-discuss the main-chain direction. First verify the real DB-backed run chain if TEST_DATABASE_URL is available. If it is not available, report that clearly and handle the remaining production-run route boundary next.
```
