# Project Map

## Purpose

This repository is a multi-tenant AI short-drama production SaaS. The current
product center is the agent-driven production chain, not the older direct task
submission screens.

The authoritative production chain is:

```text
goal
-> agent_run
-> unified facts
-> decision tick
-> dispatch gateway
-> lane handler
-> terminal observation
-> next decision
```

## Runtime Stack

- Backend: FastAPI, SQLAlchemy async sessions, PostgreSQL, Redis.
- Workers: Celery queues for video, image, text, default, and admin work.
- Frontend: Vue 3, Vite, Pinia, vue-router.
- Tests: pytest for backend unit/integration/contract/e2e suites, vue-tsc and
  Vite build for frontend compile verification.

## Backend Map

### Application Entry

- `app/main.py`
  Creates the FastAPI app, installs middleware and monitoring, includes
  `app.routes.api_router`, and keeps platform-only direct task endpoints:
  `/api/batch/generate-videos`, `/api/batch/generate-images`, and
  `/api/tts/generate`.

- `app/routes/__init__.py`
  Registers the `/api` route tree.

- `app/config.py`
  Loads environment settings and shared provider configuration.

- `app/db.py`
  Owns the async SQLAlchemy engine and session factory.

- `app/celery_app.py`
  Defines Celery imports, queues, routing, and periodic maintenance jobs.

### Main API Areas

- `app/routes/auth.py`, `app/routes/users.py`
  Authentication, current user, and API key management.

- `app/routes/tasks.py`
  Task listing, detail, and cancellation for platform tasks.

- `app/routes/credits.py`, `app/routes/payment.py`, `app/routes/reports.py`
  Credits, pricing, payment orders, callbacks, and usage reporting.

- `app/routes/admin.py`
  Admin overview, users, tasks, credits, provider costs, dead-letter queue,
  key pool, system health, and rate limits.

- `app/routes/workbench.py`
  Project CRUD, workspace files, project brain, agent events, agent runs,
  production start, shot rows, assets, visual plan, media, scenes, and reports.

- `app/routes/director.py`
  Director tools, legacy director tasks, final cut planning, reference images,
  project memory, and diagnostics.

- `app/routes/agent_runs.py`
  Agent Studio entry point, run snapshots, SSE/events, human follow-up actions,
  retry/change-provider/cancel actions, keyframe pool actions, and run-level
  safety gates.

### Agent Main Chain

- `app/services/run_coordination.py`
  Defines unified facts and the canonical decision tick. This is the policy
  source for wait, recover, complete, blocked, and execute decisions.

- `app/services/run_dispatch_gateway.py`
  Validates executable packets, lane capability, runtime requirements, and
  routes authorized work to handlers.

- `app/services/main_chain_controller.py`
  Applies a decision packet, submits it to the decision mailbox, dispatches it
  when executable, or publishes wait/blocked/recover/complete state.

- `app/services/main_chain_terminal.py`
  Re-enters the main chain after a terminal task, observes writeback, and asks
  the controller to apply the next decision.

- `app/services/main_chain_handlers.py`
  Builds handlers used by the gateway to execute approved main-chain actions.

- `app/tasks/_shared.py`
  Shared worker lifecycle helpers, task locking, completion/error publishing,
  OSS persistence, dead-letter handling, and terminal hook integration.

### Production Services

- `app/services/project_brain.py`
  Builds project state, signals, next actions, ledgers, and final delivery
  readiness from workspace, shot rows, tasks, assets, and run state.

- `app/services/agent_run_snapshot.py`
  Builds the run snapshot consumed by the frontend and by run coordination.

- `app/services/video_production_runner.py`
  Full production runner: context, story, assets, shot planning, keyframes,
  videos, voice, subtitles, edit strategy, ffmpeg export, quality check, and
  writeback.

- `app/services/state_machine/`
  Production stage policy, gates, progress stats, and evaluator exports.

- `app/services/director_preflight.py`,
  `app/services/visual_consistency_checker.py`,
  `app/services/vision_review.py`
  Preflight and quality checks before and after generation.

- `app/services/final_edit.py`, `app/services/video_edit.py`,
  `app/services/final_delivery.py`, `app/services/final_video_storage.py`
  Final cut normalization, ffmpeg export, delivery report, and final video
  asset storage.

### Provider And Media Services

- `app/services/seedream.py`, `app/services/seedance.py`,
  `app/services/kling.py`, `app/services/comfy_video.py`,
  `app/services/doubao.py`, `app/services/tts.py`
  Provider integrations and media generation adapters.

- `app/services/provider_prompt_adapter.py`,
  `app/services/prompt_compiler.py`, `app/services/prompt/`
  Provider prompt adaptation and prompt template logic.

- `app/services/storage.py`, `app/services/media_proxy.py`
  Object/local storage and media proxy support.

### Credit And Cost Control

- `app/services/credits/service.py`
  Atomic reserve, charge, refund, direct charge, and price lookup.

- `app/services/cost_guard.py`, `app/services/provider_costs.py`,
  `app/services/usage_meter.py`, `app/services/volc_billing.py`
  Budget limits, provider cost ledger, usage metering, and billing import.

## Frontend Map

### Entry And Shared Infrastructure

- `frontend/src/router/index.ts`
  Declares public auth routes, legacy task routes, director routes, agent-run
  routes, and admin routes.

- `frontend/src/api/client.ts`
  Axios instance, token refresh, request dedupe, cancellation helper, and global
  error handling.

- `frontend/src/stores/auth.ts`, `frontend/src/stores/tasks.ts`
  Thin global auth/task stores.

### Main User Surfaces

- `frontend/src/pages/director/agent-run/index.vue`
  Agent Studio launch page. Creates runs through `POST /api/agent-runs`.

- `frontend/src/pages/director/agent-run/[runId].vue`
  Run observation and control page. Uses snapshot, events, stream, actions,
  output board, run graph, and evidence views.

- `frontend/src/pages/director/produce/`
  Production console, shot cards, flow panel, asset pool, visual planner, and
  execution observer for a project.

- `frontend/src/pages/director/final-cut.vue`
  Final cut plan, preview/final export, and asset import workflow.

- `frontend/src/pages/workbench/`
  Project workbench and older shot/asset operations.

- `frontend/src/pages/tasks/`
  Legacy platform task submission and task detail pages. These call direct
  platform endpoints, not the agent main-chain entry point.

### Frontend API Modules

- `frontend/src/api/director.ts`
  Director endpoints plus agent-run snapshot/events/actions.

- `frontend/src/api/workbench.ts`
  Project, workspace, brain, shot rows, final edit plan, assets, and visual plan.

- `frontend/src/api/tasks.ts`
  Platform direct task submission and task queries.

- `frontend/src/api/admin.ts`, `frontend/src/api/payment.ts`,
  `frontend/src/api/auth.ts`, `frontend/src/api/prompt.ts`
  Admin, payment, auth, and prompt APIs.

## Data And Migrations

- `alembic/versions/001_initial_schema.py` through
  `alembic/versions/023_add_reconcile_attempts.py`
  Define users, tasks, orders, workbench tables, media, security, cost ledgers,
  final edit/video assets, agent runtime tables, production runs, and task
  reconciliation fields.

- `data/prompt_libs/` and `app/data/prompt_libs/`
  Prompt library data and generated catalogs.

- `data/final_cut_recipes/`
  Editing rules and final cut recipes.

## Testing Map

- `tests/unit/`
  Broad unit coverage for project brain, run coordination, dispatch gateway,
  main-chain controller/terminal/observer, agent-run UI contract, task
  submission, task dispatcher, provider adapters, final edit, quality rules,
  and many production services.

- `tests/integration/`
  DB-backed tests for agent events, agent budget, main-chain loop, rate limits,
  payment, signing, credits, and entrypoint guard.

- `tests/contract/`
  API contract checks and API audit notes.

- `tests/bugs/`
  Reproduction tests for known QA bugs.

- `tests/e2e/`
  End-to-end browser or pipeline-oriented tests.

## Chain Boundaries

### Authoritative Main-Chain Entry Points

- `POST /api/agent-runs`
- `POST /api/agent-runs/{run_id}/actions/continue-step`
- `POST /api/projects/{project_id}/brain/continue`
- Terminal task hook through `app/tasks/_shared.py`

### Platform-Only Direct Task Entry Points

- `POST /api/batch/generate-videos`
- `POST /api/batch/generate-images`
- `POST /api/tts/generate`

These are valid manual SaaS task paths. They must not become autonomous agent
production paths unless wrapped by the canonical decision packet and dispatch
gateway.

## Current Shape And Risks

### P0: Main Chain Authority

The main-chain contract in `docs/main-chain-implementation-contract.md` should
remain the source of truth. Production writes inside an agent run must pass
through `dispatch_authoritative_packet`, and canonical packets should come from
`load_run_facts_from_snapshot -> evaluate_decision_tick`.

### P1: Large Coordination Files

Several files are intentionally central but large:

- `app/routes/agent_runs.py`
- `app/routes/workbench.py`
- `app/services/project_brain.py`
- `app/services/agent_run_snapshot.py`
- `app/services/video_production_runner.py`
- `frontend/src/pages/director/produce/ShotCards.vue`

Do not split these opportunistically. First pin behavior with focused tests,
then extract small helper groups only when a change requires it.

### P1: Legacy And Manual Paths

The older task pages and direct batch APIs still exist. Treat them as manual
platform capabilities. Keep their API surface stable, but do not route agent
autopilot production through them directly.

### P2: Verification Discipline

Useful focused checks:

```powershell
python -m pytest -q tests/unit/test_state_machine_package_exports.py tests/unit/test_run_coordination.py tests/unit/test_run_dispatch_gateway.py tests/unit/test_task_shared_run_coordination_hook.py
```

```powershell
npm run build
```

Run integration tests only when the DB and Redis test environment is available.

## Near-Term Cleanup Queue

1. Keep `docs/project-map.md` current when entry points or main-chain authority
   change.
2. Remove tracked backup or stray files only after confirming they have no
   references.
3. Add or update tests around any future changes to `agent_runs.py`,
   `workbench.py`, and the main-chain services before refactoring.
4. Prefer small fixes that strengthen P0 chain correctness over broad style
   cleanup.
