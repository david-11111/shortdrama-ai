# Main Run Chain Handoff

**Date:** 2026-05-26  
**Status:** Approved direction, ready for implementation planning

## Approved Source Document

The authoritative design to follow is:

- `docs/superpowers/specs/2026-05-26-main-run-chain-design.md`

That document is the current source of truth for the convergence strategy.

## User Approval Marker

The user reviewed the design and approved continuing from it.

Interpretation for the next session:

- do not reopen the question of whether there should be one main chain,
- do not re-evaluate A/B/C as equal peer orchestrators,
- continue from the approved “one authoritative run chain with three capability lanes” model.

## What Has Already Been Decided

1. The project is not blocked by missing features.
2. The main gap is missing command hierarchy.
3. The target architecture is:
   - one authoritative run chain,
   - A lane as project fact synthesis,
   - B lane as agent-run and DeepSeek interaction/explanation,
   - C lane as production execution,
   - `run_coordination` growing into the coordinator.
4. Parallel execution is allowed.
5. Parallel orchestration is not allowed.

## Current Implementation Baseline

Already present in code:

- `app/services/run_coordination.py`
  - read-only decision tick
  - snapshot-backed unified facts
  - terminal observer `observe_task_terminal_decision_tick`
- `app/tasks/_shared.py`
  - terminal task hook re-enters run coordination
- `app/services/agent_run_state_machine.py`
  - final artifact compatibility improvements already landed
- unit coverage already exists around:
  - run coordination
  - task shared coordination hook
  - run snapshot contract
  - project continue

Recent verification already completed:

- `tests/unit/test_run_coordination.py`
- `tests/unit/test_task_shared_run_coordination_hook.py`
- integration-style test added in `tests/integration/test_agent_events.py` for `decision_tick` persistence path

## Important Environment Constraints

1. Git is currently not usable in this workspace.
   - `.git` points to a missing gitdir
   - do not plan work that depends on git operations

2. Local Postgres integration verification is currently blocked.
   - `TEST_DATABASE_URL` checks skip because the local database is not reachable from the environment
   - integration tests may remain skipped until DB connectivity is restored

3. Do not rewrite the architecture from scratch.
   - preserve existing working lanes
   - remove duplicate control authority instead of replacing all code

## Required Next Artifact

Next session should produce:

**Implementation plan for “Authoritative Run Chain Phase 1: Decision Packet + Central Dispatch Skeleton”**

That plan should:

1. use the approved design doc as input,
2. stay backend-first,
3. avoid frontend convergence work until command hierarchy is stable,
4. define exact file touch points,
5. define test-first steps,
6. separate:
   - decision packet expansion,
   - dispatch gateway centralization,
   - compatibility wrappers for legacy paths.

## Session Restart Instruction

When resuming after context cleanup, start by reading:

1. `docs/superpowers/specs/2026-05-26-main-run-chain-design.md`
2. `docs/superpowers/plans/2026-05-26-main-run-chain-handoff.md`

Then continue directly into implementation planning.
