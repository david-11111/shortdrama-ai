# Director Agent Status

Last updated: 2026-05-18

## Current Position

The project brain can now drive the production flow from planning to keyframes and then to video task dispatch.

Current supported continue actions:

- `generate_story_plan`
- `plan_scene`
- `lock_assets`
- `generate_storyboard`
- `plan_visual_assets`
- `generate_keyframes`
- `generate_videos`
- `plan_final_edit`

## Demand-Based Planning Fix

The project starter no longer treats every new project as a 3-shot sample.

Completed:

1. `generate_story_plan` now parses explicit duration demand from the instruction:
   - seconds
   - minutes
   - hours
2. It estimates:
   - target duration
   - total shot count
   - scene count
   - average shot duration
   - first production batch size
3. Long-form projects are planned at full scale but produced by scene batches.
4. The first batch is still bounded so the system does not enqueue hundreds of images/videos at once.

Real API proof:

- Project: `6263502c6366447f`
- Instruction: target 40 minutes.
- Result:
  - estimated total shots: 480
  - estimated scene count: 40
  - first batch shot rows: 20
  - first batch duration: 90 seconds
  - brain moved to `asset_locking / plan_visual_assets`
  - visual actions: 29
  - compressed master references: 4
  - pending keyframes: 20
  - estimated Seedream images for current batch: 24

Current wait states:

- `wait_for_keyframes`
- `wait_for_videos`

## Latest Deep Test

Video dispatch and failure recovery were verified with temporary projects:

- Project: `dcd1129c763049ba`
- Test user: `codex-video-e2e-1779064675517@example.com`
- Brain reached `video_generation / generate_videos`
- Credit guard correctly blocked default 50-credit user
- Test account balance was raised to 500 credits
- Continue action created 3 `video_gen` tasks
- 3 shot rows changed to `generating_video`
- Brain then moved to `video_generation / wait_for_videos`

Real-keyframe test:

- Project: `0ac5e185b9984805`
- Test user: `codex-e2e-1779038340192@example.com`
- Used 3 real Seedream `selected_image` URLs.
- Brain reached `video_generation / generate_videos`.
- Continue action created 3 `video_gen` tasks and reserved 240 credits.
- Worker attempted real Seedance calls.
- Seedance key pool returned saturation/no-available-key failures.
- Two tasks reached `dead_letter`; one reached `failed`.

Important result:

- This did not prove `selected_video` write-back because provider keys were unavailable.
- It did prove that real video worker execution starts and that provider saturation is the current blocker.
- A failure-recovery bug was found and fixed: failed video tasks no longer leave shots stuck forever in `generating_video`.
- Provider/key failures on shots with `selected_image` are now warning-level, retryable risks instead of blocked preflight risks.
- Brain now returns to `video_generation / generate_videos` after failed video attempts are marked retryable.

Key-pool diagnosis:

- `.env` does contain Ark keys.
- API and video worker containers both read `SEEDANCE_API_KEYS`.
- Seedance currently has 1 dedicated key configured.
- User confirmed one Seedance API key currently supports only 1 active video task.
- Redis had a stale `ark_key:seedance:seedance_1:load` value after failed/restarted worker activity.
- `app/services/key_pool.py` was updated so load counters now get a TTL and cannot remain forever.
- Current stale Seedance key-pool counters were cleared after the TTL fix was deployed.
- `SERVICE_LIMITS["seedance"]` is now set to 1.
- Project-brain `generate_videos` now queues only 1 eligible shot per continue step.

One-shot video proof:

- Project: `0ac5e185b9984805`
- Continue action queued exactly 1 `video_gen` task.
- Task: `6a80cb7d-9c56-4fcd-b25b-1ba8e85c73a3`
- Ark task: `cgt-20260518113512-4mrx8`
- Task completed with `status=done`.
- Shot 1 changed to `status=video_done`.
- Shot 1 received `selected_video`.
- Shot 1 has `video_variants_json` count 1.
- Brain moved back to `video_generation / generate_videos` because 2 shots still need videos.
- Seedance key load returned to 0 after completion, with TTL protection still present on the key-pool load key.

Full one-at-a-time video loop:

- Project: `0ac5e185b9984805`
- Shot 1 task: `6a80cb7d-9c56-4fcd-b25b-1ba8e85c73a3`, done.
- Shot 2 task: `a9659266-8828-4e29-a99a-e5471eb8b6c6`, done.
- Shot 3 task: `8551520f-c5fc-4820-b62e-1f09524dfcf2`, done.
- All 3 shot rows are now `status=video_done`.
- All 3 shot rows have `selected_video`.
- All 3 shot rows have `video_variants_json` count 1.
- All 3 shot rows have empty `last_error`.
- Brain now reports `phase=final_edit`, `next_action=plan_final_edit`, `video_done_count=3`.

## Next Work Item

Strengthen real reference image generation after visual asset planning.

Commercialization hardening added after this status entry:

- Agent Run snapshot now exposes an exact `credit_ledger` from `credit_transactions` when task transaction ids are present, instead of relying only on failed-task reserved-credit estimates.
- Agent Run action endpoints now exist for retrying failed videos, changing video provider and retrying, continuing one step, exporting a partial preview, and cancelling queued run tasks with refunds.
- Final-cut preview/final export now writes export status and delivery reports back into `final_edit_plans.settings`; final export also updates the latest `video_production_runs` delivery fields.
- Project brain now surfaces preview/final export readiness and final delivery pass status in signals and final-delivery audit rows.
- A bug in `plan_final_edit` was fixed where stale gate-check code referenced undefined variables after the plan was saved.

Completed visual asset budget gate:

1. The project brain now reads visual planner output.
2. It reports:
   - `visual_plan_action_count`
   - `visual_bind_existing_count`
   - `visual_reference_generation_count`
   - `seedream_pending_keyframe_count`
   - `seedream_estimated_image_count`
3. If keyframes are pending and visual asset actions exist, the brain moves to `asset_locking / plan_visual_assets` instead of directly generating keyframes.
4. `plan_visual_assets` applies visual actions in bulk:
   - binds recommended existing assets first
   - creates planned reference assets only when no reusable asset exists
   - compresses repeated reference needs into reusable master references
   - writes bindings back to shot rows
   - records the decision in workspace memory
5. The production control tower now shows a specific message for visual asset planning results.

Verification:

- `python -m py_compile app\routes\workbench.py app\services\project_brain.py app\services\visual_planner.py tests\unit\test_project_brain.py`
- `python -m pytest tests\unit\test_project_brain.py tests\unit\test_visual_planner.py tests\unit\test_project_continue.py -q`
- Result: 14 passed.
- Container compile passed.
- `GET /api/projects/4f8f9ec9231a4192/brain` returned visual budget signals:
  - `actions=14`
  - before reference compression: `gen_refs=14`, `seedream_est=22`
  - after reference compression: `compressed_refs=3`, `seedream_est=11`
  - `pending_keyframes=8`

Connect final-cut preview/export as the next verified stage.

Completed final edit planning proof:

1. `plan_final_edit` is supported in the continue endpoint.
2. It requires every shot row to have `selected_video`.
3. It builds a structured final edit plan from `video_done` shot rows.
4. It persists the plan into the existing `final_edit_plans` table used by `/director/final-cut`.
5. It writes a durable decision entry into project workspace memory.
6. After the plan exists, the brain advances from `plan_final_edit` to `open_final_cut`.

Real project proof:

- Project: `0ac5e185b9984805`
- Before action: `phase=final_edit`, `next_action=plan_final_edit`, `video_done_count=3`.
- Continue action saved a plan with 3 clips.
- `GET /api/projects/0ac5e185b9984805/final-edit-plan` returned `source=saved`.
- Each clip had `shot_index`, `order`, `enabled`, `duration`, `transition`, and non-empty `video_url`.
- Database `final_edit_plans.plan_json->clips` count is 3.
- After action: `phase=final_edit`, `next_action=open_final_cut`, `final_edit_plan_ready=true`, `final_edit_clip_count=3`.

Additional recovery proof already done:

1. Failed video attempts keep their `last_error`.
2. Failed video attempts return shot rows to `image_done`.
3. Brain reports warning risks, not blocked risks.
4. Brain allows `generate_videos` retry when no video task is running.

## Commands Already Useful

Backend compile:

```powershell
python -m py_compile app\routes\workbench.py app\services\project_brain.py app\services\project_continue.py
```

Focused tests:

```powershell
python -m pytest tests\unit\test_project_brain.py tests\unit\test_project_continue.py -q
```

Frontend build:

```powershell
cd frontend; npm run build
```

Container compile:

```powershell
docker exec saas--api-1 python -m py_compile /app/app/routes/workbench.py /app/app/services/project_continue.py /app/app/services/project_brain.py
```

Health checks:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost/health
Invoke-WebRequest -UseBasicParsing http://localhost/
```

## Files To Re-Read First

Read these before continuing after a context reset:

1. `docs/director-agent-roadmap.md`
2. `docs/director-agent-status.md`
3. `app/services/project_brain.py`
4. `app/routes/workbench.py`
5. `app/tasks/video_tasks.py`
6. `tests/unit/test_project_brain.py`

## Guardrails

- Do not trust 200-only checks.
- Do not use placeholder image URLs as final media proof.
- Do not allow duplicate generation while shots are generating.
- Do not skip credit guard or preflight guard.
- Do not claim video stage complete until `selected_video` is written back.
- Treat provider/key saturation as retryable unless content/preflight checks fail.
- When testing video generation, keep one active Seedance task per configured key unless the provider quota is increased.
