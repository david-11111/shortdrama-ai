# Agent Run Commercial Chain Audit

Date: 2026-06-12

This document maps the current `/director/agent-run` commercial production chain. It is intentionally written as an engineering control document: every chain has an owner module, data ledger, provider boundary, billing point, and known release risk.

## 1. Runtime Entrypoints

### Frontend

- Launch page: `frontend/src/pages/director/agent-run/index.vue`
  - Calls `createAgentRun()` from `frontend/src/api/director.ts`.
  - Fresh project defaults to:
    - `action=production_run`
    - `provider_mode=real`
    - `image_provider=seedream`
    - `video_provider=ltx2.3`
    - `allow_local_placeholders=false`
  - Existing project defaults to `action=continue_project`.
- Observe page: `frontend/src/pages/director/agent-run/[runId].vue`
  - Snapshot: `GET /api/agent-runs/{run_id}/snapshot`.
  - SSE: `GET /api/agent-runs/{run_id}/stream?token=...`.
  - Human follow-up: `POST /api/agent-runs/{run_id}/actions/continue-step`.
  - Output panel actions:
    - keyframe batch: `POST /api/agent-runs/{run_id}/actions/generate-keyframe-batch`
    - video from pool: `POST /api/agent-runs/{run_id}/actions/generate-video-from-pool`
    - provider switch: `POST /api/agent-runs/{run_id}/actions/change-provider`

### Backend

- `app/routes/agent_runs.py:74` creates agent runs.
- `app/routes/agent_runs.py:95` branches `production_run`.
- `app/routes/agent_runs.py:103` routes missing storyboard production runs back to `continue_project_brain`.
- `app/routes/agent_runs.py:133` starts `VideoProductionRunner` only when storyboard shots already exist.
- `app/routes/agent_runs.py:188` serves snapshot.
- `app/routes/agent_runs.py:241` serves SSE.
- `app/routes/agent_runs.py:382` handles human continue-step.
- `app/routes/agent_runs.py:1290` handles keyframe batch.
- `app/routes/agent_runs.py:1500` handles video from pool.

## 2. Two Production Chains Exist

### Chain A: Brain Continue Chain

Primary files:

- `app/routes/workbench.py:1093` `continue_project_brain`
- `app/routes/workbench.py:1465` `_dispatch_action_after_planning`
- `app/routes/workbench.py:1474` `_should_continue_planning_chain`
- `app/routes/workbench.py:1656` `_dispatch_production_action`
- `app/routes/workbench.py:2515` `_continue_generate_keyframes`
- `app/routes/workbench.py:2521` `_continue_generate_videos`

Flow:

1. User starts/continues a run.
2. `continue_project_brain` builds or updates `shot_rows`.
3. Planning loop decides next action.
4. `_dispatch_action_after_planning` maps next action to production actions.
5. `_dispatch_production_action` gates via state machine / dispatch gateway.
6. Keyframe/video actions enqueue child `tasks`.
7. Workers write provider results back to `shot_rows.selected_image` / `shot_rows.selected_video`.
8. Snapshot builds output from `shot_rows`, tasks, artifacts, and production ledger.

Recent fix:

- `fix_preflight_risks` is now allowed to continue in autopilot. Before that, autopilot could mark the run `completed` before keyframe/video dispatch.

### Chain B: VideoProductionRunner Full Chain

Primary files:

- `app/routes/workbench.py:804` `start_video_production`
- `app/tasks/director_tasks.py:42` `video_production_run_task`
- `app/services/video_production_runner.py:61` `VideoProductionRunner`
- `app/services/video_production_runner.py:44` `PRODUCTION_STAGES`
- `app/services/video_production_runner.py:121` `run`

Stages:

1. read_context
2. plan_story
3. lock_assets
4. plan_shots
5. generate_keyframes
6. generate_videos
7. generate_voice
8. select_bgm
9. generate_subtitles
10. build_edit_strategy
11. ffmpeg_export
12. quality_check
13. writeback

Media dispatch:

- keyframes: `app/services/video_production_runner.py:320`
- videos: `app/services/video_production_runner.py:371`
- task insertion/dispatch: `app/services/video_production_runner.py:724`
- child task wait/requeue: `app/services/video_production_runner.py:935`
- final export: `app/services/video_production_runner.py:552`

Commercial risk:

- Fresh project `production_run` with no storyboard does not immediately enter `VideoProductionRunner`; it first routes to Chain A. Existing storyboard `production_run` enters Chain B. This means one UI can execute two materially different backend chains.

## 3. Core Data Ledgers

Tables are created across these migrations:

- `projects`, `shot_rows`, `assets`: `alembic/versions/005_add_workbench_tables.py`
- media analysis tables: `alembic/versions/009_add_media_tables.py`
- `agent_runs`, `agent_steps`, `agent_events`, `agent_artifacts`, `tasks.run_id`: `alembic/versions/017_add_agent_runtime_tables.py`
- `video_production_runs`: `alembic/versions/019_add_video_production_runs.py`
- `provider_pricing_rules`, `provider_usage_costs`: `alembic/versions/010_add_provider_cost_ledger.py`
- `volc_billing_rows`: `alembic/versions/011_add_volc_billing_rows.py`
- `final_video_assets`: `alembic/versions/022_add_final_video_assets.py`

Snapshot outputs:

- `app/services/agent_run_snapshot.py:67` builds snapshot.
- `app/services/agent_run_snapshot.py:1202` builds output board.
- `app/services/agent_run_snapshot.py:1218` reads `selected_image`.
- `app/services/agent_run_snapshot.py:1240` reads `selected_video`.
- `app/services/agent_run_snapshot.py:1300` reads `final_video_url`.
- `app/services/agent_run_snapshot.py:1347` builds keyframe pool.

Important rule:

- Output board truth is `shot_rows.selected_image`, `shot_rows.selected_video`, and `video_production_runs.final_video_url`. If tasks never exist or provider writeback fails, the UI correctly shows `0 图片 / 0 视频`.

## 4. Doubao API Chain

Provider file:

- `app/services/doubao.py:29` `generate_text`

API:

- Base URL: `settings.ark_base_url`
- Endpoint: `/chat/completions`
- Model: `settings.ark_text_model`, default `doubao-1-5-pro-32k`
- Key source:
  - `doubao_api_keys`
  - fallback `ark_api_keys`
  - key pool service: `doubao`

Direct callers:

- `app/tasks/director_tasks.py:267` `director_script_task`
- `app/tasks/director_tasks.py:365` `director_final_cut_ai_task`
- `app/routes/prompt.py:39` prompt refine endpoint
- `app/services/doubao.py:150` `render_seedance_prompt_en`

Billing:

- `app/services/usage_meter.py:14` creates `billing_usage` for Doubao token usage.
- `app/services/provider_costs.py:48` records provider usage on task completion if `billing_usage` exists.

Risk:

- Some brain/planning paths are deterministic or DeepSeek-oriented and do not necessarily pass through Doubao. Do not assume "agent-run text planning" always equals Doubao billing.

## 5. Seedream API Chain

Provider file:

- `app/services/seedream.py:29` `generate_image`

API:

- Base URL: `settings.ark_base_url`
- Endpoint: `/images/generations`
- Model: `settings.ark_image_model`, default `seedream-3-0`
- Key source:
  - `seedream_api_keys`
  - fallback `ark_api_keys`
  - key pool service: `seedream`

Worker chain:

- `app/tasks/image_tasks.py:42` `generate_image_task`
- `app/tasks/image_tasks.py:93` acquires Seedream key.
- `app/tasks/image_tasks.py:134` writes `selected_image`.
- `app/tasks/image_tasks.py:145` charges credits.
- `app/tasks/image_tasks.py:211` refunds on failure.

Prompt adaptation:

- `app/services/provider_prompt_adapter.py:52` `adapt_seedream_payload`
- injects semantic constraints and visual quality controls.

Billing:

- `app/services/usage_meter.py:48` creates Seedream usage record.
- Usage is written only if the provider result contains `billing_usage`.

## 6. Seedance API Chain

Provider file:

- `app/services/seedance.py:128` `generate_video`

API:

- Base URL: `settings.ark_base_url`
- Submit endpoint: `/contents/generations/tasks`
- Poll endpoint: `/contents/generations/tasks/{task_id}`
- Model: `settings.ark_video_model`, default `seedance-1-0`
- Key source:
  - `seedance_api_keys`
  - fallback `ark_api_keys`
  - key pool service: `seedance`

Worker chain:

- `app/tasks/video_tasks.py:39` `generate_video_task`
- `app/tasks/video_tasks.py:139` acquires provider key for Seedance/Kling.
- `app/tasks/video_tasks.py:187` writes `selected_video`.
- `app/tasks/video_tasks.py:198` charges credits.
- `app/tasks/video_tasks.py:247` refunds on failure.

Prompt adaptation:

- `app/services/provider_prompt_adapter.py:63` `adapt_seedance_payload`
- injects motion controls, continuity, temporal position, semantic constraints.
- `app/services/doubao.py:150` may render Chinese prompt to English Seedance prompt.

Special handling:

- `PolicyViolationError` triggers prompt sanitization and retry.

Billing:

- `app/services/usage_meter.py:90` creates Seedance usage record.

## 7. LTX API / Wan2.1 / ComfyUI Chain

Worker entry:

- `app/tasks/video_tasks.py:94` imports `generate_comfy_video`.
- `app/tasks/video_tasks.py:103` calls `generate_comfy_video`.

Provider router:

- `app/services/comfy_video.py:691` `generate_comfy_video`

LTX inference API path:

- Providers: `ltx2.3`, `wan`, `wan2.1`, `wan2_1`
- `app/services/comfy_video.py:452` `_generate_ltx_inference_api_video`
- Upload/reference handling:
  - remote/local image converted to inference file id
  - `/v1/files/upload`
- Submit:
  - `app/services/comfy_video.py:411` `_submit_inference_job`
  - endpoint `/v1/video/generate`
- Poll:
  - `app/services/comfy_video.py:419` `_poll_inference_job`
  - endpoint `/v1/tasks/{task_id}`
- Download:
  - `app/services/comfy_video.py:309` `_download_ltx_output_locally`
  - local storage: `storage/ltx_downloads`
  - returned URL: `/api/media/local/ltx/{filename}`

Plain ComfyUI workflow path:

- Provider `ltx` uses `_ltx_workflow`.
- `_WORKFLOW_BUILDERS` also contains `wan`, but `wan` is currently caught by the inference API provider set first.
- `app/services/comfy_video.py:491` submits workflow to `/prompt`.
- `app/services/comfy_video.py:603` polls `/history/{prompt_id}`.

Commercial risks:

- LTX/Wan2.1 does not use `key_pool`.
- LTX/Wan2.1 result currently has no `billing_usage`, so provider cost ledger and platform cost guard do not naturally see its actual cost.
- Provider capability naming in dispatch still treats non-Seedance image-to-video providers as `seedance_image_to_video`, which is semantically misleading for operations, analytics, and support.

## 8. FFmpeg / FFprobe Editing Chain

Binary resolution:

- `app/config.py:123` `_resolve_binary`
- `app/config.py:130` `FFMPEG`
- `app/config.py:131` `FFPROBE`

Export:

- `app/services/video_edit.py:83` `export_final_video`
- `app/services/video_edit.py:204` resolves local/remote input videos.
- `app/services/video_edit.py:260` probes input media.
- `app/services/video_edit.py:395` `concat_scenes_with_transitions`
- `app/services/video_edit.py:481` falls back to plain concat when filter export fails.

Plan and delivery:

- `app/services/final_edit.py:136` converts edit plan to export payload.
- `app/services/final_edit.py:165` validates delivery plan.
- `app/services/final_delivery.py:39` builds final delivery report using ffprobe.

Commercial risk:

- FFmpeg filter failure can degrade to plain concat. That may remove transitions/subtitles/BGM but still produce a file. This must be surfaced as a visible degraded-delivery state.

## 9. Credit and Cost Chain

User credit service:

- `app/services/credits/service.py:32` default pricing.
- `app/services/credits/service.py:75` reserve.
- `app/services/credits/service.py:105` charge.
- `app/services/credits/service.py:142` refund.
- `app/services/credits/service.py:237` DB pricing lookup.
- `app/middleware/credits.py` exposes `reserve_credits`.

Task submission:

- `app/services/task_submission.py:52` batch task submission.
- `app/services/task_submission.py:139` single task submission.
- `app/services/task_dispatcher.py` applies rate/concurrency/cost guard for generic dispatch.

Platform cost guard:

- `app/services/cost_guard.py:128` blocks when platform or user daily limits are exceeded.
- Uses:
  - `provider_usage_costs.estimated_cost_yuan`
  - `volc_billing_rows.amount_yuan`
  - `credit_transactions`

Provider usage ledger:

- `app/services/provider_costs.py:48` extracts `billing_usage` and writes `provider_usage_costs`.
- `app/services/usage_meter.py` covers Doubao, Seedream, Seedance.

Commercial risks:

- LTX/Wan2.1 missing usage records means platform cost guard can undercount real GPU/inference cost.
- Credits and provider costs are separate ledgers. A task can charge user credits without corresponding provider cost usage if provider result lacks `billing_usage`.
- Provider usage recording is best-effort in `_shared.publish_complete`; failure logs a warning but does not fail the task.

## 10. Prompt Library Chain

Prompt library engine:

- `app/services/prompt/engine.py:2025` `retrieve_prompt_matches`
- `app/services/prompt/engine.py:2381` `compose_prompt_with_libraries`
- `app/routes/prompt.py:14` `/prompt/retrieve`
- `app/routes/prompt.py:39` `/prompt/refine`

Execution prompt compiler:

- `app/services/prompt_compiler.py:23` `compile_execution_prompt`
- Calls prompt library retrieval and Doubao Seedance prompt rendering.

Provider prompt adapter:

- `app/services/provider_prompt_adapter.py:11` `adapt_provider_payload`
- `app/services/provider_prompt_adapter.py:42` Doubao adapter
- `app/services/provider_prompt_adapter.py:52` Seedream adapter
- `app/services/provider_prompt_adapter.py:63` Seedance/video adapter

Storage split:

- `prompt.engine` resolves libraries under `app/data/prompt_libs`.
- `vector_store` resolves libraries under root `data/prompt_libs`.
- Both folders exist. They currently appear duplicated, but this is a drift risk.

Confirmed issue:

- `app/services/vector_store.py:135` references `_embeddions`, which is undefined. Semantic search can fail and be swallowed by `prompt.engine`, causing silent degradation to keyword/rule retrieval.

## 11. Key Commercial Release Risks

### P0

1. One UI triggers two different production chains depending on whether storyboard rows exist.
2. Agent run can appear completed while no media tasks were dispatched if planning chain exits early.
3. Prompt vector retrieval has a concrete typo and can silently fail.
4. LTX/Wan2.1 provider costs are not metered into provider usage ledger.

### P1

1. LTX/Wan2.1 has no key-pool/circuit-breaker equivalent.
2. FFmpeg export can silently degrade to plain concat.
3. Prompt library data path is split between `app/data` and root `data`.
4. Provider capability names conflate Seedance and other image-to-video providers.
5. Task/provider events use actor labels that can show Seedance for generic video tasks, including LTX.
6. Some provider-cost writes are best-effort warnings rather than hard ledger guarantees.
7. Current source/log output shows Chinese text encoding problems in multiple files when inspected from PowerShell.

## 12. Recommended Fix Order

1. Define one canonical commercial agent-run state machine.
   - New and existing projects must enter the same production controller after storyboard creation.
   - `completed` must require terminal criteria: storyboard exists, required media tasks terminal, expected outputs present or explicitly skipped.
2. Normalize provider contract.
   - Provider request, response, billing usage, artifact, retry policy, timeout, and capability names must be explicit per provider.
   - Add LTX/Wan2.1 cost usage records.
3. Harden prompt library.
   - Fix `_embeddions`.
   - Make vector retrieval failure visible in health/snapshot/debug evidence.
   - Collapse `app/data/prompt_libs` and root `data/prompt_libs` to one authoritative path.
4. Harden final export.
   - If FFmpeg filter graph falls back, write delivery report issue and show degraded status in output board.
5. Add end-to-end acceptance tests.
   - Fresh agent-run commercial flow.
   - Existing project continue flow.
   - Seedream writeback.
   - Seedance writeback.
   - LTX writeback and cost record.
   - FFmpeg final export with subtitles/BGM.
   - Provider failure refund and visible recovery action.

