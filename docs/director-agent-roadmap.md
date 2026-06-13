# Director Agent Roadmap

This document is the durable working plan for the short-drama director agent. It exists so the project does not depend on chat history.

## Product North Star

Build a Codex-like production agent for premium short drama.

The product should feel like:

1. It understands the project goal and keeps moving toward a usable result.
2. It understands complex production context, collaborates, judges, and corrects.
3. It knows what we want to shoot and how to get it shot.

The core experience:

1. Think clearly before generating.
2. Know where production will fail and fix it early.
3. Turn scattered tools into one reliable production flow.

This is not just an API wrapper. The APIs are capable; our system must provide the production brain, constraints, workflow memory, quality gates, and recovery loop.

## Current Architecture Direction

The project is moving toward a workspace-based agent model:

- A project has durable files such as `PROJECT.md`, story documents, scene plans, shot JSON, decisions, failures, and constraints.
- The project brain reads workspace files plus operational database rows.
- The brain decides the current phase and next action.
- The continue endpoint executes only safe, supported next actions.
- The UI should feel like a production terminal/control tower, not a page full of unrelated buttons.

## Demand First Principle

Planning must be driven by the requested production target, not by a fixed demo size.

Current behavior:

- If the user asks for a 40-minute episode, the system estimates the full production scale first.
- It does not pretend 3 shots are enough.
- It creates a bounded first production batch so the team can validate style, references, and workflow before expanding.
- Reference assets are planned as reusable master references across the whole project; keyframes/videos are produced by scene batch.

## Completed

### File-Backed Workspace

Implemented in `app/services/project_workspace.py`.

Required workspace files include:

- `PROJECT.md`
- `story/characters.md`
- `story/episodes.md`
- `scenes/episode-01-scene-01.md`
- `shots/episode-01-scene-01.json`
- `memory/decisions.md`
- `memory/failures.md`
- `memory/constraints.md`

Endpoints:

- `GET /api/projects/{project_id}/workspace`
- `POST /api/projects/{project_id}/workspace/init`
- `POST /api/projects/{project_id}/workspace/write`

### Project Brain

Implemented in `app/services/project_brain.py`.

Endpoint:

- `GET /api/projects/{project_id}/brain`

It currently returns:

- `phase`
- `next_action`
- `next_action_label`
- `can_continue`
- `missing`
- `risks`
- `signals`
- `context`

Important states already covered:

- `generate_story_plan`
- `generate_keyframes`
- `wait_for_keyframes`
- `generate_videos`
- `wait_for_videos`

### Continue Executor

Endpoint:

- `POST /api/projects/{project_id}/brain/continue`

Implemented actions:

- `generate_story_plan`
- `plan_scene`
- `lock_assets`
- `generate_storyboard`
- `generate_keyframes`
- `generate_videos`

### Deep Verification Already Done

Verified beyond HTTP 200:

- New project starts at `generate_story_plan`.
- Continue writes workspace planning files.
- Continue creates operational shot rows.
- Keyframe continue creates `image_gen` tasks.
- Keyframe continue updates shot rows to `generating_image`.
- Real image worker wrote back selected images for successful test shots.
- Brain waits while keyframes are still generating.
- Brain moves to `generate_videos` after keyframes exist.
- Credit guard blocks video generation when balance is insufficient.
- With test credits, video continue creates `video_gen` tasks.
- Video continue updates shot rows to `generating_video`.
- Brain waits with `wait_for_videos` while videos are generating.

## Current Known Gap

Video generation has now been verified past the earlier write-back gap on a real-keyframe project.

Closed since the original roadmap entry:

- Real `selected_image` URLs were used.
- The video worker called Seedance.
- One-at-a-time Seedance dispatch completed three video tasks.
- Each shot received `selected_video` and `video_variants_json`.
- The brain advanced to `final_edit / plan_final_edit`.
- `plan_final_edit` persisted a saved plan and advanced the brain to `open_final_cut`.

The remaining closure is now final-cut execution:

- Verify preview export from the saved final edit plan.
- Verify final export from the same plan.
- Add an edit-readiness gate for broken or expired video URLs.
- Surface preview/export status back into the project brain.
- Record final export lineage in workspace memory.

## Next Phases

### Phase 1: Close Video Write-Back

Goal: complete the image-to-video loop.

Tasks:

1. Run an end-to-end project with real keyframe URLs.
2. Trigger `generate_videos` through project brain.
3. Verify `video_gen` tasks move from queued/running to done.
4. Verify each shot row receives:
   - `selected_video`
   - `video_variants_json`
   - `status=video_done`
5. Verify project brain no longer waits for videos and advances to final edit.
6. Add or update tests for the state transition from video done to final edit.

Deep checks:

- Confirm task payload contains `shot_row`, `selected_image`, `prompt`, `duration`, `provider`.
- Confirm worker logs have no traceback.
- Confirm credits are charged or refunded correctly.
- Confirm a failed video task writes a useful failure reason.

### Phase 2: Final Edit Brain Action

Goal: after videos are available, the brain should plan and execute final edit preparation.

Tasks:

1. Add `plan_final_edit` as a supported brain action. Done.
2. Generate or refresh final edit plan from available video shots. Done.
3. Persist final edit plan into existing `final_edit_plans` storage and workspace memory. Done.
4. Advance brain to `open_final_cut` after the plan exists. Done.
5. Add tests for:
   - videos available means final edit plan can be generated. Done at brain state level.
   - missing/corrupt video source blocks with a clear risk. Backend action blocks missing `selected_video`; deeper URL validation remains next.

Next final-cut work:

1. Verify preview export from the saved plan.
2. Verify final export from the same plan.
3. Add an edit-readiness gate for broken/expired video URLs.
4. Surface preview/export status back into the project brain.
5. Record final export lineage in workspace memory.

### Phase 3: Production Quality Gates

Goal: make the system smarter than a raw API chain.

Quality gates to strengthen:

- Script understanding gate
- Scene planning gate
- Asset lock gate
- Preflight gate
- Keyframe review gate
- Video review gate
- Edit readiness gate

### Phase 3A: Seedream Image Budget And Reference Reuse

Goal: avoid blindly generating large numbers of keyframes before reusable reference assets are locked.

Completed:

1. The project brain reads visual planner output.
2. The brain estimates Seedream image demand from reference gaps plus pending keyframes.
3. If visual references are missing, the brain chooses `plan_visual_assets` before `generate_keyframes`.
4. The continue endpoint can apply visual asset actions in bulk:
   - bind existing references
   - create planned reference placeholders
   - compress repeated needs into reusable master references
   - write bindings to shot rows
   - record the decision in workspace memory

Next:

1. Turn planned reference placeholders into real Seedream reference generation tasks.
2. Add a per-scene image budget policy:
   - generate one master face reference per important role
   - generate one master scene reference per main scene
   - generate props/costume/style only when reused or high-risk
   - generate keyframes only after core references are locked
3. Add duplicate reference detection so similar shots reuse one reference.
4. Add review gates for reference images before they can drive keyframes.
5. Surface budget estimates in the production terminal.

Each gate should answer:

- What is wrong?
- Why does it matter for premium short drama?
- Can the system fix it automatically?
- If not, what does the user need to decide?

### Phase 4: UI as Production Terminal

Goal: reduce button sprawl and make the front end feel like a Codex-style production session.

UI principles:

- One primary next action.
- Visible stream of what the system is doing.
- Expandable details for references, shots, scenes, costumes, props, people, and locks.
- Problems first, completed items collapsed.
- Background complexity hidden until needed.

Needed UI refinements:

- Clear wait states for keyframes and videos.
- Better labels for project brain action messages.
- A production event stream that shows:
  - workspace read
  - plan writes
  - shot creation
  - keyframe dispatch
  - keyframe review
  - video dispatch
  - video review
  - final edit planning
- Clickable inspection for each step.

### Phase 5: Durable Project Memory

Goal: the project should survive restarts and multiple terminals.

Add durable records for:

- decisions
- failures
- asset locks
- shot revisions
- model/provider choices
- generated media lineage
- review results
- user approvals

The brain should always read these records before deciding the next action.

## Verification Standard

Do not claim a feature is done only because an endpoint returns 200.

For every production action, verify at least:

1. Endpoint response shape.
2. Database row changes.
3. Task rows created when applicable.
4. Worker receives usable payload.
5. Status transitions are correct.
6. Credits are reserved, charged, or refunded correctly.
7. Project brain next state is correct.
8. Frontend can refresh and show the new state.
9. Logs contain no new traceback.

For media actions, additionally verify:

1. Output URL exists.
2. Output URL is written back to the right shot.
3. Review metadata exists or a fallback review is recorded.
4. Failed outputs produce actionable recovery actions.

## Do Not Do

- Do not add more isolated buttons as the main experience.
- Do not let users repeatedly fire the same generation while previous tasks are still running.
- Do not hide blocked or waiting states behind vague errors.
- Do not treat placeholder media URLs as proof of real provider success.
- Do not rely on chat history for project direction.
- Do not bypass preflight, credit guard, task queue, or worker write-back checks.

## Immediate Next Step

Connect final-cut preview/export as the next verified stage:

1. Use the saved `final_edit_plans` row created from real `selected_video` shots.
2. Run preview export and verify the produced media URL exists.
3. Run final export from the same plan.
4. Validate output with ffprobe or the existing delivery checks.
5. Surface export state back into the project brain.
6. Add tests for final-cut readiness, preview export, and final export transition.
