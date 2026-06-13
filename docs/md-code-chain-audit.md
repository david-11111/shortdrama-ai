# Markdown And Code Chain Audit

**Date:** 2026-05-27  
**Scope:** Markdown inventory, code inventory, and the traceable chain map between the two.

## Scope Rules

This audit treats the repository Markdown in four buckets:

| Bucket | Files | Role |
| --- | ---: | --- |
| Product and architecture docs | 15 | Source of truth for architecture, API, deploy, agent flow, monitoring, frontend/security notes, and contract audit. |
| `.claude` orchestration docs | 41 | Historical implementation task specs and team/process notes. Useful for provenance, not current runtime authority. |
| Runtime project workspaces | 32 projects x 7 MD files | Per-project generated workspace memory: `PROJECT.md`, story docs, scene docs, and memory ledgers. These are runtime state, not global architecture docs. |
| Model/vendor Markdown | 3+ | Model card, safety, and README for local `text2vec` assets. Not part of app orchestration. |

The current authoritative product docs are:

- `docs/superpowers/specs/2026-05-26-main-run-chain-design.md`
- `docs/superpowers/plans/2026-05-27-main-run-chain-phase-1-post-implementation-handoff.md`
- `docs/codex-style-video-agent-process.md`
- `docs/director-agent-roadmap.md`
- `docs/director-agent-status.md`
- `docs/agent-run-client-design.md`
- `saas_architecture_plan.md`
- `saas_interface_protocol.md`

## Top-Level Code Shape

| Area | Main files | Responsibility |
| --- | --- | --- |
| API bootstrap | `app/main.py`, `app/routes/__init__.py` | FastAPI app, middleware, route registration, direct batch generation endpoints, WebSocket endpoint. |
| Auth/security | `app/routes/auth.py`, `app/middleware/auth.py`, `app/security/*`, `frontend/src/stores/auth.ts`, `frontend/src/api/client.ts` | Login/register/refresh/me, JWT injection, token refresh, auth expiry handling. |
| SaaS billing and limits | `app/services/credits.py`, `app/middleware/credits.py`, `app/middleware/rate_limit.py`, `app/services/cost_guard.py`, `app/routes/credits.py` | Balance, reservation, charge/refund, pricing, per-user spend and rate gates. |
| Task dispatch | `app/services/task_submission.py`, `app/celery_app.py`, `app/worker.py`, `app/tasks/*` | Insert task rows, reserve credits, send Celery tasks, route queues, run workers. |
| Task terminal observation | `app/tasks/_shared.py`, `app/services/run_coordination.py`, `app/services/agent_runtime.py` | Persist task progress/result/failure, publish events, run decision tick, finalize run. |
| Project workspace | `app/services/project_workspace.py`, `storage/projects/*` | Durable project Markdown/JSON memory and controlled workspace writes. |
| Project brain, A lane | `app/services/project_brain.py`, `app/services/project_continue.py`, `app/services/project_brain_ledgers.py` | Load workspace and operational facts, decide phase/next action, run planning actions. |
| Agent run, B lane | `app/routes/agent_runs.py`, `app/services/agent_run_snapshot.py`, `app/services/llm_planner.py`, `app/services/agent_evidence_composer.py`, `frontend/src/pages/director/agent-run/*` | Human instruction, snapshot, event stream, diagnostics, pending actions, interactive control. |
| Production execution, C lane | `app/tasks/image_tasks.py`, `app/tasks/video_tasks.py`, `app/tasks/tts_tasks.py`, `app/tasks/director_tasks.py`, `app/services/video_production_runner.py`, `app/services/final_edit.py`, `app/services/final_delivery.py` | Media generation, provider calls, writeback, final edit, preview/final export. |
| Authoritative main chain | `app/services/run_coordination.py`, `app/services/run_dispatch_gateway.py`, `app/routes/workbench.py`, `app/tasks/_shared.py` | Decision packet, central dispatch gateway, compatibility handlers, terminal re-entry. |
| Provider and prompt layer | `app/services/key_pool.py`, `app/services/seedream.py`, `app/services/seedance.py`, `app/services/kling.py`, `app/services/doubao.py`, `app/services/provider_prompt_adapter.py`, `app/services/ref_resolver.py`, `app/services/prompt/*` | Provider payload shaping, key acquisition, generation APIs, prompt compilation and references. |
| Admin/ops | `app/routes/admin.py`, `app/tasks/admin_tasks.py`, `monitoring/*`, `nginx/default.conf`, Docker files | Admin views, dead letter, key pool, pricing, health metrics, deployment. |
| Persistence | `alembic/versions/*.py` | Users, credits, tasks, workbench, media, final edit, agent runtime, production runs, final assets. |
| Frontend shell | `frontend/src/router/index.ts`, `frontend/src/api/*.ts`, `frontend/src/pages/**/*` | Page routing and API adapters for all backend chains. |

## Authoritative Main Run Chain

Documented in:

- `docs/superpowers/specs/2026-05-26-main-run-chain-design.md`
- `docs/superpowers/plans/2026-05-26-main-run-chain-handoff.md`
- `docs/superpowers/plans/2026-05-26-authoritative-run-chain-phase-1-decision-packet-central-dispatch-skeleton.md`
- `docs/superpowers/plans/2026-05-27-main-run-chain-phase-1-post-implementation-handoff.md`
- `docs/codex-style-video-agent-process.md`

Code chain:

```text
user goal
-> POST /api/agent-runs or POST /api/projects/{project_id}/brain/continue
-> create_agent_run(...)
-> build_project_brain(...)
-> compatibility DecisionTickResult packet
-> dispatch_authoritative_packet(...)
-> legacy handler for plan_visual_assets / generate_keyframes / generate_videos / plan_final_edit
-> task rows and/or workspace/final edit writes
-> Celery worker execution
-> publish_complete / publish_failed
-> observe_task_terminal_decision_tick(...)
-> agent_events decision_tick
-> agent run snapshot / stream UI
```

Current code anchors:

- Intake: `app/routes/agent_runs.py`, `app/routes/workbench.py`
- Fact load and packet: `app/services/run_coordination.py`
- Gateway: `app/services/run_dispatch_gateway.py`
- Compatibility handlers: `app/routes/workbench.py`
- Terminal hook: `app/tasks/_shared.py`
- Snapshot and UI: `app/services/agent_run_snapshot.py`, `frontend/src/pages/director/agent-run/*`

Coverage status:

- Covered in Markdown: yes.
- Code implemented: Phase 1 backend skeleton exists.
- Open item already documented: real DB-backed end-to-end validation is still pending; the separate production-run route remains an explicit boundary question.

## A Lane: Project Brain And Workspace Chain

Documented in:

- `docs/director-agent-roadmap.md`
- `docs/director-agent-status.md`
- `docs/codex-style-video-agent-process.md`
- `docs/superpowers/specs/2026-05-26-main-run-chain-design.md`

Code chain:

```text
GET /api/projects/{project_id}/brain
-> app.routes.workbench.get_project_brain
-> build_project_brain(...)
-> read_project_workspace(...)
-> storage/projects/{project_id}/PROJECT.md
-> story/characters.md
-> story/episodes.md
-> scenes/episode-01-scene-01.md
-> shots/episode-01-scene-01.json
-> memory/decisions.md / failures.md / constraints.md
-> operational DB shot rows/assets/tasks/final_edit_plan
-> phase + next_action + risks + signals + safety_gates
```

Execution subset:

```text
POST /api/projects/{project_id}/brain/continue
-> continue_project_from_brain(...)
-> project_continue_v2 planning result
-> persist_director_result_to_workspace(...)
-> workspace Markdown/JSON writeback
-> operational shot rows upsert
-> after brain refresh
```

Coverage status:

- Covered in Markdown: yes.
- Runtime workspace Markdown is intentionally part of the chain: project brain reads it every time.
- Current executable planning actions in code: `generate_story_plan`, `plan_scene`, `lock_assets`; production actions are routed through workbench compatibility handlers.

## B Lane: Agent Run, DeepSeek, Control, And UI Chain

Documented in:

- `docs/agent-run-client-design.md`
- `docs/codex-style-video-agent-process.md`
- `docs/superpowers/specs/2026-05-26-main-run-chain-design.md`
- `docs/director-agent-status.md`

Code chain:

```text
frontend /director/agent-run
-> createAgentRun(...)
-> POST /api/agent-runs
-> continue_project_brain(...)
-> /director/agent-run/{runId}
-> GET /api/agent-runs/{run_id}/snapshot
-> GET /api/agent-runs/{run_id}/stream
-> project:{project_id}:events stream
-> action endpoints for continue/retry/provider/export/cancel/keyframe/video-from-pool
-> dispatch_agent_action / diagnostics / pending action
-> optional continue_project_brain or export handlers
```

Current code anchors:

- API: `app/routes/agent_runs.py`
- Snapshot: `app/services/agent_run_snapshot.py`
- Runtime events: `app/services/agent_runtime.py`
- Planner/evidence: `app/services/llm_planner.py`, `app/services/agent_evidence_composer.py`
- Frontend: `frontend/src/pages/director/agent-run/*`, `frontend/src/api/director.ts`

Coverage status:

- Covered in Markdown: mostly yes.
- The broad UI concept, snapshot, stream, and action model are documented.
- Some newer granular action endpoints (`keyframe-batch/preview`, `generate-video-from-pool`, keyframe candidate selection) are code-first and should be added to the Agent Run client design or a dedicated action contract doc.

## C Lane: Production Execution Chain

Documented in:

- `docs/codex-style-video-agent-process.md`
- `docs/director-agent-roadmap.md`
- `docs/director-agent-status.md`
- `saas_architecture_plan.md`
- `saas_interface_protocol.md`

Generic task chain:

```text
route or gateway handler
-> reserve credits
-> INSERT tasks(status='queued')
-> celery_app.send_task(...)
-> worker queue: video / image / text / default / admin
-> key_pool.acquire(...)
-> provider adapter
-> provider API
-> persist_result_to_oss(...)
-> update_shot_media / final_edit writeback
-> maybe_charge or maybe_refund
-> publish_complete or publish_failed
-> Redis task progress + agent_events
-> run coordination terminal tick
```

Media chains:

| Chain | Entry | Worker | Provider/service | Writeback |
| --- | --- | --- | --- | --- |
| Batch image | `POST /api/batch/generate-images` | `app.tasks.image_tasks.generate_image_task` | `seedream` | task result, OSS, shot image writeback when shot payload exists |
| Batch video | `POST /api/batch/generate-videos` | `app.tasks.video_tasks.generate_video_task` | `seedance` or `kling` | `selected_video`, `video_variants_json`, task result |
| TTS | `POST /api/tts/generate` | `app.tasks.tts_tasks.generate_tts_task` | TTS/Kling-style service | task result and optional delivery |
| Director production | `/api/director/produce`, production-run route | `app.tasks.director_tasks.*` | runner + image/video/final edit services | `video_production_runs`, tasks, final delivery |
| Final export | director final/preview export routes and agent-run export action | `director_export_preview_task`, `director_export_final_task` | `final_edit`, `video_edit`, `final_delivery` | final edit settings, final video assets, production run delivery fields |

Coverage status:

- Covered in Markdown: yes for the main image/video/final edit flow.
- Older `app/tasks/media_tasks.py` task family is not part of the current authoritative main chain and is only historically covered by `.claude` task docs.

## SaaS Platform Chain

Documented in:

- `saas_architecture_plan.md`
- `saas_interface_protocol.md`
- `DEPLOY.md`
- `.claude/orchestrator/tasks/T1-devops.md`
- `.claude/orchestrator/tasks/T3-api-biz.md`
- `.claude/orchestrator/tasks/T4-api-auth.md`
- `.claude/orchestrator/tasks/T6-api-biz.md`
- `.claude/orchestrator/tasks/T8-api-biz.md`
- `.claude/orchestrator/tasks/T18-api-biz.md`
- `.claude/orchestrator/tasks/T21-payment.md`

Code chain:

```text
frontend api client
-> Authorization header / token refresh
-> FastAPI auth middleware/dependency
-> route handler
-> concurrent/rate/cost/credit guard
-> service or task submission
-> DB tables via Alembic schema
-> response / events / reports
```

Important note:

- `saas_interface_protocol.md` still names earlier `crud.py`, `job_registry.py`, and `main.py` integration points. The current code has moved to `app/routes/*`, `app/services/task_submission.py`, SQLAlchemy async sessions, and Celery. Treat that protocol as historical unless updated.

## Payment, Credits, Reports, And Admin Chain

Documented in:

- `saas_architecture_plan.md`
- `saas_interface_protocol.md`
- `.claude/orchestrator/tasks/T18-api-biz.md`
- `.claude/orchestrator/tasks/T21-payment.md`
- `tests/contract/api_audit.md`

Code chain:

```text
/api/payment/plans
-> /api/payment/create-order
-> order row
-> callback or manual confirm
-> credit account transaction
-> frontend recharge/payment-success
-> reports/admin credit views
```

Admin and ops:

```text
/api/admin/*
-> overview/users/tasks/credits/dead-letter/key-pool/system/rate-limits
-> admin middleware + audit
-> DB reads/writes
-> frontend admin pages
```

Coverage status:

- Covered in Markdown: partially. The SaaS plan covers concepts; `.claude` task docs cover implementation intent.
- A current endpoint-level admin/payment contract doc would reduce reliance on historical task instructions.

## Prompt, Director, And Reference Chain

Documented in:

- `docs/director-agent-roadmap.md`
- `docs/director-agent-status.md`
- `.claude/orchestrator/tasks/T15-worker.md`
- `.claude/orchestrator/tasks/T16-worker.md`
- `docs/codex-style-video-agent-process.md`

Code chain:

```text
frontend director/prompt pages
-> /api/prompt/* and /api/director/*
-> prompt library / retrieval / annotation / ref binding
-> director reasoning/evaluator/rework/memory/evolution services
-> optional Celery director tasks
-> workspace memory and agent events
```

Coverage status:

- Covered in Markdown: medium.
- The strategy docs explain why these exist, but not every route in `app/routes/director.py` has a concise current contract.

## Frontend Chain

Documented in:

- `docs/agent-run-client-design.md`
- `frontend/docs/token-storage-eval.md`
- `.claude/orchestrator/tasks/T5-fe-core.md`
- `.claude/orchestrator/tasks/T7-fe-pages.md`
- `.claude/orchestrator/tasks/T13-fe-pages.md`
- `.claude/orchestrator/tasks/T14-fe-pages.md`
- `.claude/orchestrator/tasks/T19-fe-pages.md`

Current route families:

- Auth: `/login`, `/register`
- User dashboard/task flow: `/`, `/tasks`, `/tasks/submit-*`, `/tasks/:id`
- Billing/settings/reports: `/settings`, `/recharge`, `/payment/success`, `/reports`
- Workbench/director: `/workbench/:projectId`, `/director/*`, `/director/agent-run/*`, `/director/final-cut/*`
- Admin: `/admin/*`

Code chain:

```text
router page
-> frontend/src/api/*.ts adapter
-> frontend/src/api/client.ts auth/dedupe/error handling
-> backend /api route
-> store/composable refresh
-> WebSocket or EventSource stream where applicable
```

Coverage status:

- Covered in Markdown: yes for Agent Run UI and token storage; older `.claude` docs cover initial page scaffolding.
- Workbench/final-cut detailed UI behavior is mostly code-first.

## Runtime Markdown Chain

Documented in:

- `docs/director-agent-roadmap.md`
- `app/services/project_workspace.py` docstrings and constants

Runtime files per project:

```text
storage/projects/{project_id}/PROJECT.md
storage/projects/{project_id}/story/characters.md
storage/projects/{project_id}/story/episodes.md
storage/projects/{project_id}/scenes/episode-01-scene-01.md
storage/projects/{project_id}/memory/decisions.md
storage/projects/{project_id}/memory/failures.md
storage/projects/{project_id}/memory/constraints.md
```

Runtime non-MD companion:

```text
storage/projects/{project_id}/shots/episode-01-scene-01.json
```

Code chain:

```text
init_project_workspace
-> bootstrap templates
-> read_project_workspace
-> build_project_brain
-> persist_director_result_to_workspace / write_project_workspace_file
-> memory/decisions.md append audit
```

Coverage status:

- Covered in Markdown as a concept.
- The generated runtime Markdown itself is not a stable global spec; it is per-project state.

## Gaps To Close In Markdown

1. `saas_interface_protocol.md` is stale against the current code layout. It should be rewritten around `app/routes/*`, `task_submission.py`, `agent_runs.py`, and the Alembic schema.
2. Agent Run action endpoints need a current contract table, especially retry/change-provider/continue-step/export/keyframe-batch/select-candidate/video-from-pool/cancel.
3. `app/routes/director.py` has many route-level capabilities that are not fully reflected in a current Markdown contract.
4. Workbench and final-cut UI behavior is mostly implemented in code and only partially covered by docs.
5. `app/tasks/media_tasks.py` and older director-generation task paths should be explicitly marked legacy or compatibility-only.
6. The post-implementation handoff says real DB-backed main-chain validation is pending; that gap should remain visible until `TEST_DATABASE_URL` integration verification runs.

## Chain Coverage Matrix

| Chain | Primary Markdown | Primary code | Coverage |
| --- | --- | --- | --- |
| One authoritative run chain | `docs/superpowers/specs/2026-05-26-main-run-chain-design.md` | `run_coordination.py`, `run_dispatch_gateway.py`, `workbench.py`, `_shared.py` | Covered, DB E2E pending |
| A lane project brain | `docs/director-agent-roadmap.md`, `docs/director-agent-status.md` | `project_brain.py`, `project_workspace.py`, `project_continue.py` | Covered |
| B lane Agent Run UI/control | `docs/agent-run-client-design.md` | `agent_runs.py`, `agent_run_snapshot.py`, `frontend/src/pages/director/agent-run/*` | Mostly covered |
| C lane production tasks | `docs/codex-style-video-agent-process.md`, `saas_architecture_plan.md` | `app/tasks/*`, `task_submission.py`, provider services | Covered for main path |
| Task terminal re-entry | `docs/superpowers/plans/2026-05-27-main-run-chain-phase-1-post-implementation-handoff.md` | `app/tasks/_shared.py`, `run_coordination.py` | Covered |
| Workspace Markdown memory | `docs/director-agent-roadmap.md` | `project_workspace.py`, `storage/projects/*` | Covered |
| Credits/rate/cost | `saas_architecture_plan.md`, `saas_interface_protocol.md` | `credits.py`, `middleware/*`, `cost_guard.py` | Covered |
| Auth/token | `frontend/docs/token-storage-eval.md`, `saas_architecture_plan.md` | `auth.py`, `client.ts`, auth store | Covered |
| Payment/admin/reports | `.claude` task docs, SaaS plan | `payment.py`, `admin.py`, `reports.py`, frontend admin/recharge pages | Partially covered |
| Prompt/director utilities | Roadmap/status docs | `prompt.py`, `director.py`, `app/services/director/*` | Partially covered |
| Monitoring/deploy | `DEPLOY.md`, `monitoring/agent-health-metrics.md` | Docker, nginx, `monitoring/health.py` | Covered |

