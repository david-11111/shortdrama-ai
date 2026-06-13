# Orchestrator 操作日志

> 按时间倒序记录关键操作。每条记录自包含，不依赖上下文。

---

## 2026-05-19

### [PROJECT-BRAIN-FEEDBACK-LOOP-AUDIT] Step 8 now proves write-back and next-run continuity

Scope:
- Added `context.feedback_loop_audit` to `app/services/project_brain.py`.
- The audit verifies:
  - execution decisions are persisted to `memory/decisions.md`,
  - shot row status/media results are persisted to `shot_rows`,
  - successful media results write `selected_image` / `selected_video`,
  - media failures write `shot_rows.last_error` and now append `memory/failures.md`,
  - final edit plans are read from `final_edit_plans`,
  - `continueProjectBrain.after` and frontend `refreshProjectState()` refresh the next brain state.
- Updated `workbench.py` so autonomous keyframe/video continue writes bounded dispatch decisions to `memory/decisions.md`.
- Updated worker shared writeback so media task failures append durable failure memory.
- Updated `/director/produce` execution trace to show “展开回写复盘审计”.

Evidence:
- `python -m py_compile app/services/project_brain.py app/routes/workbench.py app/tasks/_shared.py tests/unit/test_project_brain_ledgers.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py tests/unit/test_final_edit_delivery.py -q` passed: 22 passed.
- `cd frontend; npm run build` passed.
- Hot-copied backend, worker, and frontend files into running containers.
- Restarted `saas--api-1`, `saas--worker-image-1`, `saas--worker-video-1`, and `saas--nginx-1`.
- Container compile passed for API files and worker `_shared.py`.
- Runtime checks passed:
  - `GET /health` returned HTTP 200.
  - `GET /director/produce` returned HTTP 200.

Boundary:
- This proves persistent write-back paths and next brain read paths. It does not run a real provider task in this pass.
- Full end-to-end replay with an actual failed provider response remains a separate pressure/chaos test.

### [FINAL-DELIVERY-HARD-GATE] Final preview/export now enforces delivery completeness

Scope:
- Added `validate_delivery_plan()` in `app/services/final_edit.py`.
- `director_export_preview` and `director_export_final` now load the current saved edit plan when no plan is passed and validate it before queueing export.
- Missing enabled clips, BGM, required subtitles, or explicitly required voiceover/TTS now returns HTTP 400 instead of allowing an incomplete commercial export.

Evidence:
- `python -m pytest tests/unit/test_final_edit_delivery.py tests/unit/test_project_brain_ledgers.py -q` passed: 9 passed.
- API container compile passed for `final_edit.py` and `director.py`.

### [PROJECT-BRAIN-FINAL-DELIVERY-AUDIT] Step 6 now proves final delivery completeness

Scope:
- Added `context.final_delivery_audit` to `app/services/project_brain.py`.
- The audit verifies:
  - video completeness across all shot rows,
  - voiceover/TTS readiness when dialogue/voiceover exists,
  - BGM readiness through `final_edit_plan.settings.bgm_path`,
  - final edit plan coverage and enabled video clips,
  - subtitle readiness when `burn_subtitles` is enabled,
  - review blockers,
  - preview/export readiness.
- Updated `/director/produce` execution trace to show “展开成片交付审计”.
- Extended unit tests with both blocked and ready delivery scenarios.

Evidence:
- `python -m py_compile app/services/project_brain.py tests/unit/test_project_brain_ledgers.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 18 passed.
- `cd frontend; npm run build` passed.
- Hot-copied backend and frontend dist into running containers.
- Restarted `saas--api-1` and `saas--nginx-1`.
- Container compile passed for project brain.
- Runtime checks passed:
  - `GET /health` returned HTTP 200.
  - `GET /director/produce` returned HTTP 200.

Boundary:
- This pass audits delivery readiness from stored shot rows and edit plan data. It does not render a new preview video.
- Export endpoints already reject zero exportable videos, but do not yet hard-block every missing BGM/subtitle/voice issue. The audit exposes those gaps before export.
- No provider calls or pressure tests were run.

### [PROJECT-BRAIN-COST-GUARDRAIL-AUDIT] Step 5 now proves bounded dispatch and cost controls

Scope:
- Added `context.cost_control_audit` to `app/services/project_brain.py`.
- The audit verifies:
  - keyframe small-step dispatch,
  - video small-step dispatch,
  - asset reuse first,
  - Seedream budget gate,
  - credit reserve/refund guard,
  - rate/concurrency guard,
  - story handoff risk entering cost/risk review.
- Updated `app/routes/workbench.py` so autonomous brain continue does not queue all pending keyframes:
  - `BRAIN_KEYFRAME_BATCH_MAX = 4`
  - `BRAIN_VIDEO_BATCH_MAX = 1`
- Updated `cost_risk_ledger.limits.video_batch_max` to match the actual video execution cap of 1.
- Updated `/director/produce` execution trace to show “展开成本风控审计”.
- Extended unit tests to assert the cost audit and batch caps are present.

Evidence:
- `python -m py_compile app/services/project_brain.py app/services/project_brain_ledgers.py app/routes/workbench.py tests/unit/test_project_brain_ledgers.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 17 passed.
- `cd frontend; npm run build` passed.
- Hot-copied backend and frontend dist into running containers.
- Restarted `saas--api-1` and `saas--nginx-1`.
- Container compile passed for project brain, ledgers, and workbench route.
- Runtime checks passed:
  - `GET /health` returned HTTP 200.
  - `GET /director/produce` returned HTTP 200.

Boundary:
- No real Seedream, Seedance, Doubao, or TTS provider calls were made.
- Manual batch buttons may still allow larger user-initiated batches; this pass specifically hardens autonomous project-brain continue behavior.
- Full pressure testing remains pending.

### [PROJECT-BRAIN-CONTINUITY-HANDOFF-AUDIT] Step 4 now proves scene/minute/adjacent-scene awareness

Scope:
- Added `context.continuity_handoff_audit` to `app/services/project_brain.py`.
- The audit verifies:
  - current episode/scene key,
  - current minute range and generated/remaining/target seconds,
  - previous scene handoff,
  - next scene handoff,
  - continuity gaps and handoff questions,
  - whether continuity is consumed by phase/next_action/risk/debug flow.
- Added story handoff risk signal in `project_brain_ledgers.py` for multi-scene handoff gaps.
- Updated `/director/produce` execution trace to show “展开剧情承接审计”.
- Extended unit tests so a multi-scene long plan proves:
  - current segment is `E01S02`,
  - previous segment ends at shot 2,
  - minute position is covered,
  - handoff gaps include `scene_handoff_check`,
  - risk list includes `story_handoff_gap`.

Evidence:
- `python -m py_compile app/services/project_brain.py app/services/project_brain_ledgers.py tests/unit/test_project_brain_ledgers.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 17 passed.
- `cd frontend; npm run build` passed.
- Hot-copied backend and frontend dist into running containers.
- Restarted `saas--api-1` and `saas--nginx-1`.
- Container compile passed for project brain and ledgers.
- Runtime checks passed:
  - `GET /health` returned HTTP 200.
  - `GET /director/produce` returned HTTP 200.

Boundary:
- This pass adds visibility and risk signaling. It does not yet hard-block all generation when a handoff gap exists.
- Strong blocking should be decided in Step 5 cost/risk policy so it can distinguish small safe probes from large generation batches.
- No provider calls or pressure tests were run.

### [PROJECT-BRAIN-CREATIVE-LOWERING-AUDIT] Step 3 now proves whether creator techniques reach execution boundaries

Scope:
- Added `context.creative_lowering_audit` to `app/services/project_brain.py`.
- The audit separates page-level technique visibility from actual lowering into execution surfaces:
  - `matched_libraries` -> `shot.matched_libraries` / per-shot creative ledger.
  - `visual_quality_rules` -> Seedream/Seedance prompt payloads through `ref_resolver.apply_visual_quality_controls`.
  - `human_performance_controls` -> micro-expression/body-linkage prompt controls.
  - `video_motion_controls` -> Seedance video prompt through `apply_video_motion_controls`.
  - `voice_delivery_rules` -> TTS text/speed/volume/delivery profile through `prepare_tts_payload`.
  - `final_cut_recipes` -> `final_edit_plan.recipe_id` / final-cut rule application.
  - `content_humanizer` -> script/prompt rewrite markers and humanizer boundary.
- Updated `/director/produce` execution trace to show “展开创作技巧下沉审计”.
- The UI now shows `covered / partial / missing`, candidate/applied counts, lowered target, execution boundary, examples, and gaps.

Evidence:
- `python -m py_compile app/services/project_brain.py tests/unit/test_project_brain_ledgers.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py tests/unit/test_visual_quality_rules.py tests/unit/test_voice_delivery_rules.py -q` passed: 28 passed.
- `cd frontend; npm run build` passed.
- Hot-copied backend and frontend dist into running containers.
- Restarted `saas--api-1` and `saas--nginx-1`.
- Container compile passed: `docker exec saas--api-1 python -m py_compile /app/app/services/project_brain.py`.
- Runtime checks passed:
  - `GET /health` returned HTTP 200.
  - `GET /director/produce` returned HTTP 200.

Boundary:
- This is a dry-run/code-boundary and UI audit. It does not call Seedream, Seedance, Doubao, or TTS providers.
- A technique is only marked `covered` when current project data reached the relevant execution boundary; available code hooks without actual project execution are shown as `partial`.
- No pressure test was run in this pass.

## 2026-05-18

### [PRODUCE-TO-FINAL-CUT-BRIDGE] Production page now routes users into the editing software

Scope:
- Updated `/director/produce` so the final-cut stage is a visible bridge in the main production flow.
- Added a state-aware "Final Cut Chain" card:
  - shows whether any `selected_video` exists,
  - explains how many shots are already cuttable,
  - routes to `/director/final-cut/:projectId` when ready.
- Changed the header shortcut text to `进入剪辑台`.
- Updated shot-card primary action behavior:
  - when a shot reaches the edit/done phase, the primary action now opens the final-cut workbench instead of bypassing it with a direct final export.
- Kept the older direct final export control as a secondary fallback, but the customer-facing main path is now:
  - produce clips -> final-cut workbench -> preview sample -> final export.
- Added `scripts/verify_final_cut_preview_chain.py` as a repeatable deep verification script.

Evidence:
- Frontend `npm run build` passed.
- Published frontend dist into `saas--nginx-1` and restarted nginx.
- Runtime page checks:
  - `GET /director/produce` returned HTTP 200.
  - `GET /director/final-cut/test_project` returned HTTP 200.
  - `GET /health` returned `{"status":"ok"}`.
  - unauthenticated `POST /api/director/export-preview` returned HTTP 401, so the protected preview API is still mounted.
- Deep chain verification passed:
  - generated two temporary MP4 clips in `saas--worker-admin-1`,
  - created a temporary user/project/credit account/shot rows,
  - verified `GET /api/projects/{project_id}/final-edit-plan` produced 2 clips from `selected_video`,
  - saved an edited plan with trim/transition changes,
  - submitted `POST /api/director/export-preview`,
  - task finished `done`,
  - result had `export_kind=preview`, `clip_count=2`, `storage_mode=db_blob`,
  - authenticated GET of `/api/director/final-video/{task_id}` returned MP4 bytes,
  - preview size was 25312 bytes,
  - temporary DB rows and worker temp videos were cleaned.
- Worker log confirms `director_export_preview_task` succeeded in about 2.9s.

Boundary:
- This pass connected the product workflow and verified executable preview output. It did not add new advanced FFmpeg effects or segmentation-based creator templates.
- The UI still preserves a direct export fallback for operational continuity, but the intended commercial path is now through the final-cut workbench.

### [FINAL-CUT-PREVIEW-SAMPLE] Low-res FFmpeg preview sample for visible editing feedback

Scope:
- Added low-res preview export support to the final-cut chain.
- Added backend endpoint `POST /api/director/export-preview`.
- Added Celery task `app.tasks.director_tasks.director_export_preview_task`.
- Reused the same structured edit-plan payload as final export: enabled clips, order, trim start/end, transitions, burn-in subtitles, BGM path, and BGM volume.
- Updated `app/services/video_edit.py` so `export_final_video(..., preview=True)` renders a smaller MP4. A vertical 720x1280 source previews at about 480x852 with faster/lower bitrate encoding.
- Updated `/director/final-cut` UI with `生成预览小样`, separate preview progress, and direct playback in the right-side video panel.

Cost behavior:
- Preview export does not call Doubao/DeepSeek and does not consume text tokens.
- It is an FFmpeg task over existing project media and records `credits_reserved=0`.

Evidence:
- Local backend py_compile passed for `video_edit.py`, `director_tasks.py`, and `director.py`.
- Frontend `npm run build` passed.
- Hot-copied backend files and frontend dist into running containers.
- Restarted `saas--api-1`, `saas--worker-admin-1`, and `saas--nginx-1`.
- `GET /health` returned `{"status":"ok"}`.
- Unauthenticated `POST /api/director/export-preview` returned HTTP 401, proving the authenticated API route is mounted.
- Worker startup log lists `app.tasks.director_tasks.director_export_preview_task`.
- Container FFmpeg preview smoke generated two temporary 720x1280 clips and called `export_final_video(..., preview=True)`.
- Smoke output: `clip_count=2`, `file_size=7752`, `duration_sec=1.52`, probed size `480x852`, audio stream present.

Boundary:
- This is a visible preview of the currently executable edit plan. It does not yet implement AI segmentation effects such as person cutout/freeze-frame outlines.
- Preview still uses the existing `/api/director/final-video/{task_id}` DB blob fallback when OSS is unavailable.
- Real user preview submission requires login and produced clips in the selected project.

## 2026-05-14

### [DIRECTOR-PRODUCE-FIX] 修复生产中台关键闭环

**修复内容：**
- `app/routes/director.py`：`/api/director/produce` 派发前校验项目分镜，空分镜或部分缺失直接 400，避免先扣费后空成功；`credits_reserved` 改为真实价格。
- `app/tasks/director_tasks.py`：一键生产成功后回写 `shot_rows.selected_image/selected_video`、候选数组和状态；无分镜直接失败；全镜头失败不 finalize charge。
- `app/tasks/image_tasks.py`、`app/tasks/video_tasks.py`：批量出图/视频成功后按 `project_id + shot_index` 回写分镜；视频任务补齐 `prompt/duration/image_url` 映射。
- `app/main.py`：批量端点返回的 `total_credits_reserved` 使用 DB 价格。
- `frontend/src/pages/director/produce/ShotCards.vue`：批量任务 payload 携带 `project_id/selected_image`，并追踪全部子任务。
- `frontend/src/pages/director/produce/ChatPanel.vue`：恢复可编译版本；生成脚本读取当前输入；轮询超时可收口。
- `frontend/src/composables/useDirectorSession.ts`：参考图和锚点锁加入本地持久化。

**验证证据：**
- Python 语法检查通过：`python -m py_compile app/routes/director.py app/tasks/director_tasks.py app/tasks/image_tasks.py app/tasks/video_tasks.py app/main.py`
- 前端构建通过：`cd frontend; npm run build`
- 已热替换并重启：`saas--api-1`、`saas--worker-admin-1`、`saas--worker-image-1`、`saas--worker-video-1`、`saas--nginx-1`
- API 证据：`POST /api/director/produce` with `shot_indices:[999]` 返回 `400 {"detail":"No shot rows to produce"}`
- DB 证据：修复后最近 2 分钟 `director_produce` 新任务数 `0`；测试用户新增积分交易 `0`

**未验证：**
- 未跑真实外部图片/视频生成，避免消耗生产资源；生产成功后的媒体 URL 回写路径已在代码层补齐，仍需一次真实低成本任务验证。

## 2026-05-12

### [P8-OPS-1/2/4/5] devops 终端第一波交付（含越权警示）

**产出（经 orchestrator 独立核实）：**
- `alembic/versions/006_add_rate_limit_resources.py` — 补 5 资源 × 3 档 tier，ON CONFLICT DO NOTHING
- `alembic/versions/007_add_constraints.py` — balance CHECK≥0 + shot_rows CHECK + FK
- `alembic/versions/008_add_security_tables.py`（从 006 重命名并改 down_revision = 007）
- 迁移链重排：`005 → 006 → 007 → 008` 串接正确
- `monitoring/grafana-dashboard.json`、`monitoring/prometheus.yml`、`scripts/backup.sh`

**越权警示（记录备案）：**
devops 初版创建了 `app/routes/health.py` 并改了 `app/main.py` — 两处都超出 devops 权限边界（app/ 下属 api-biz/worker 领地）。
终端自觉撤销并迁至 `monitoring/health.py`（devops 合法领地）。orchestrator 独立核实：
- `app/routes/health.py` 确实不存在
- `app/main.py` 保留 Phase 7 原有 /health 实现，无 devops 新增痕迹

**处置决定：**
- 收编合规产出，本次越权不计过（因自觉撤销且无残留）
- 但在 changelog 留痕，避免后续"默许式越权"成为惯例
- orchestrator 将在 `.claude/team/devops.md` 的"禁止访问"章节前添加醒目警示

**未完成（P8-OPS-3，转为阻塞项）：**
/health/detailed 缺 Celery 检查。devops 不可改 app/main.py，此任务需 api-biz 在 P8-BIZ 批次中顺手完成：
参考 monitoring/health.py:_check_celery() 实现，在 app/main.py:health_detailed() 补充 Celery inspect。

### [PHASE-8-START] 集成修复与质量加固

**团队扩编：** 1 + 6 → 1 + 8
- 新增 `qa` 终端（端到端测试、契约、回归、冒烟）
- 新增 `security` 终端（支付签名、审计、Token 黑名单、HMAC）
- 原因：现有 6 个终端专注纵深，无人负责横向集成验证与安全专项；Phase 7 结束后集成审查发现导演链派发断裂、支付签名未实现等 46 项缺陷，需专人收口。

**缺陷审查结论（来自 orchestrator 深度全盘检查）：**
- P0：16 项（链路断裂 / 财务漏洞 / 生产不可用）
- P1：19 项（功能缺陷 / 安全隐患 / 体验问题）
- P2：11 项（质量 / 性能 / 约束）

**产出文件：**
- `.claude/team/qa.md`、`.claude/team/security.md`（新建）
- `CLAUDE.md` 更新团队结构表为 1+8
- `.claude/orchestrator/state.md` 重写为 Phase 8 任务分发表（50 个任务按 8 终端分派）
- `.claude/orchestrator/qa_issues.md` 新建，46 项缺陷入表跟踪

**下一步：** 各终端拉取自己分支，按 state.md 分发的优先级领任务。orchestrator 每日汇总进度到本 changelog。

---

## 2026-05-11

### [COMPLETE] Phase 1 — 基础设施搭建

- T1 devops: config.py + db.py + redis_client.py + docker-compose + alembic 9表迁移
- T2 worker: celery_app.py + key_pool.py + credits.py + 4类任务(video/image/text/admin)
- T3 api-biz: main.py 异步化 + routes/tasks.py + ws/task_updates.py + schemas

**Phase 1 产出文件总计：**
```
app/config.py, app/db.py, app/redis_client.py, app/celery_app.py, app/worker.py,
app/main.py, app/routes/__init__.py, app/routes/tasks.py,
app/schemas/__init__.py, app/schemas/tasks.py,
app/tasks/__init__.py, app/tasks/_shared.py, app/tasks/video_tasks.py,
app/tasks/image_tasks.py, app/tasks/text_tasks.py, app/tasks/admin_tasks.py,
app/services/key_pool.py, app/services/credits.py,
app/ws/__init__.py, app/ws/task_updates.py,
docker-compose.yml, Dockerfile, requirements.txt, .env.example,
alembic.ini, alembic/env.py, alembic/versions/001_initial_schema.py
```

---

### [INIT] 建立团队护栏体系

- 创建 `CLAUDE.md` 全局规则
- 创建 6 个终端指令文件：api-auth、api-biz、worker、fe-core、fe-pages、devops
- 建立权限矩阵和 Git 分支策略
- 建立 orchestrator 防崩溃机制

**结果：** 团队结构就绪，等待用户确认开发优先级后开始分发任务。
---

## 2026-05-14

### [DIRECTOR-PRODUCE-HARDENING] Reduced crash surface after produce fix

Scope:
- Moved director media writeback helpers into `app/tasks/_shared.py` so image/video/director workers share one implementation and no longer import private helpers from `director_tasks.py`.
- Added `director.py` input normalization helpers for `/api/director/produce`; invalid `shot_indices` types now fail with 400 before task dispatch or credit reservation.
- Kept the prior business behavior: missing shot rows fail fast, successful media generation writes back to `shot_rows`.

Evidence:
- `python -m py_compile app/routes/director.py app/tasks/_shared.py app/tasks/director_tasks.py app/tasks/image_tasks.py app/tasks/video_tasks.py` passed.
- `cd frontend; npm run build` passed.
- Hot replacement completed for `saas--api-1`, `saas--worker-admin-1`, `saas--worker-image-1`, `saas--worker-video-1`.
- `GET /health` returned `{"status":"ok"}`.
- `POST /api/director/produce` with `shot_indices:[999]` returned `400 {"detail":"No shot rows to produce"}`.
- `POST /api/director/produce` with `shot_indices:["abc"]` returned `400 {"detail":"shot_indices must be integers"}`.
- DB check after failed calls: recent `director_produce` task count was `0`; user `6` recent credit transaction rows were `0`.

Not verified:
- Real external image/video provider generation was not executed in this pass to avoid consuming production resources. URL writeback is code/build verified, but still needs one low-cost real provider smoke test.
---

## 2026-05-14

### [BILLING-USAGE-METERING] Provider input/output metering added

Scope:
- Added `app/services/usage_meter.py` to normalize provider usage into `{provider, service, model, billing_basis, input, output, total, raw_usage}`.
- `app/services/doubao.py` now preserves Doubao `prompt_tokens`, `completion_tokens`, `total_tokens`, and returns `billing_usage`.
- `app/services/seedream.py` now returns Seedream input/output billing basis: prompt chars, negative prompt chars, reference image count, generated image count, width, height, pixels, and raw provider usage if returned.
- `app/services/seedance.py` now returns Seedance input/output billing basis: prompt chars, reference image count, output video count, duration seconds, resolution, aspect ratio, and raw provider usage if returned.
- Added `scripts/analyze_volc_billing.py` to parse the Volcengine billing TSV template using the `变动金额` column so small and large consumption rows are both included.

Evidence:
- `python -m py_compile app/services/usage_meter.py app/services/doubao.py app/services/seedream.py app/services/seedance.py scripts/analyze_volc_billing.py` passed.
- Billing template parse for `C:\Users\福星1号\Desktop\新建 文本文档.txt` returned 37 rows, 35 consumption rows, 2 recharge rows, consumption `243.48`, recharge `80.00`, net `-163.48`.
- Usage structure smoke test produced separate input/output records for Doubao, Seedream, and Seedance.
- Hot replacement completed for API/text/image/video/admin workers.
- Runtime evidence: `GET /health` returned `{"status":"ok"}`; container py_compile passed for the changed service files.

Not verified:
- No real external provider call was executed after this metering change. The next real Doubao/Seedream/Seedance calls should include `billing_usage` in task result JSON.
---

## 2026-05-15

### [PROVIDER-COST-LEDGER] Task-level provider cost ledger

Scope:
- Added migration `010_add_provider_cost_ledger.py`.
- Added `provider_pricing_rules` for editable provider price formulas.
- Added `provider_usage_costs` for task-level provider usage/cost records.
- Added `app/services/provider_costs.py` to extract nested `billing_usage` records and write cost ledger rows.
- `publish_complete()` now records provider usage before persisting task completion.
- Director script/reference-image outputs now preserve nested `billing_usage` so cost rows are not lost.
- Admin endpoints added:
  - `GET /api/admin/provider-costs`
  - `GET /api/admin/provider-pricing`
  - `POST /api/admin/provider-pricing`

Evidence:
- `alembic upgrade head` ran successfully: `009_add_media_tables -> 010_add_provider_cost_ledger`.
- DB tables exist: `provider_pricing_rules`, `provider_usage_costs`.
- Container py_compile passed for `provider_costs.py`, `_shared.py`, `director_tasks.py`, and `admin.py`.
- Verification insert used a temporary Doubao pricing rule: 1,000,000 input tokens + 500,000 output tokens estimated to `2.000000` yuan.
- Temporary verification rows and temporary pricing rule were deleted after verification; remaining verification rows = `0`.
- `alembic current` returned `010_add_provider_cost_ledger (head)`.
- `GET /health` returned `{"status":"ok"}`.
- API/text/image/video/admin containers restarted and are running.

Not verified:
- No real provider call was executed after this ledger change. The next real Doubao/Seedream/Seedance task should create task-level rows in `provider_usage_costs`.
- Official provider price values have not been seeded yet; use `POST /api/admin/provider-pricing` after confirming current Volcengine pricing.
---

## 2026-05-15

### [CREDIT-PRICING-STOPLOSS] Conservative credit price update

Scope:
- Updated runtime `credit_pricing` to conservative stop-loss prices:
  - `llm_director_chat`: 3
  - `llm_refine`: 3
  - `image_gen`: 6
  - `video_gen_5s`: 80
  - `video_gen_8s`: 120
  - `video_gen_10s`: 160
  - `pipeline_analysis`: 10
- Updated `app/services/credits.py` `DEFAULT_PRICING` to match the DB prices.
- Hot replaced `credits.py` into API/text/image/video/admin containers and restarted them.

Evidence:
- Pre-update DB prices were `image_gen=2`, `llm_director_chat=1`, `llm_refine=1`, `pipeline_analysis=5`, `video_gen_5s=10`, `video_gen_8s=15`, `video_gen_10s=20`.
- DB update affected 7 rows.
- Post-update DB prices match the stop-loss table above.
- `python -m py_compile app/services/credits.py` passed locally.
- Container py_compile passed for `/app/app/services/credits.py`.
- `GET /health` returned `{"status":"ok"}`.
- API/text/image/video/admin containers restarted and are running.

Note:
- This is a conservative stop-loss adjustment based on the user's Volcengine cash bill totaling `243.48` yuan for 35 consumption rows. It is not yet a final per-model official-price match. Final pricing should be recalculated after real `provider_usage_costs` rows accumulate and current Volcengine model prices are confirmed.
---

## 2026-05-15

### [CREDIT-PRICING-STOPLOSS] Conservative credit price update

Scope:
- Updated runtime `credit_pricing` to conservative stop-loss prices:
  - `llm_director_chat`: 3
  - `llm_refine`: 3
  - `image_gen`: 6
  - `video_gen_5s`: 80
  - `video_gen_8s`: 120
  - `video_gen_10s`: 160
  - `pipeline_analysis`: 10
- Updated `app/services/credits.py` `DEFAULT_PRICING` to match the DB prices.
- Hot replaced `credits.py` into API/text/image/video/admin containers and restarted them.

Evidence:
- Pre-update DB prices were `image_gen=2`, `llm_director_chat=1`, `llm_refine=1`, `pipeline_analysis=5`, `video_gen_5s=10`, `video_gen_8s=15`, `video_gen_10s=20`.
- DB update affected 7 rows.
- Post-update DB prices match the stop-loss table above.
- `python -m py_compile app/services/credits.py` passed locally.
- Container py_compile passed for `/app/app/services/credits.py`.
- `GET /health` returned `{"status":"ok"}`.
- API/text/image/video/admin containers restarted and are running.

Note:
- This is a conservative stop-loss adjustment based on the user's Volcengine cash bill totaling `243.48` yuan for 35 consumption rows. It is not yet a final per-model official-price match. Final pricing should be recalculated after real `provider_usage_costs` rows accumulate and current Volcengine model prices are confirmed.
---

## 2026-05-15

### [BILLING-RULES-CACHE] Volcengine billing rules captured

Scope:
- Updated Doubao usage metering to include `cached_tokens` and `cache_storage_token_hours`.
- Updated provider cost estimation for text models to support:
  - `input_yuan_per_million_tokens`
  - `output_yuan_per_million_tokens`
  - `cached_yuan_per_million_tokens`
  - `cache_storage_yuan_per_million_token_hour`
- Confirmed PromptPilot reference pricing from user-provided material:
  - Standard plan: 39.9 yuan/month includes 39,900 credits => 1 yuan = 1000 credits.
  - Team plan: 239 yuan/month includes 250,950 credits => 1 yuan = 1050 credits.
  - Add-on packs: 1 yuan = 700/750/800 credits depending package.

Evidence:
- Local py_compile passed for `usage_meter.py`, `doubao.py`, `provider_costs.py`.
- Container py_compile passed for the same files.
- Usage smoke test produced input fields `prompt_tokens`, `cached_tokens`, `cache_storage_token_hours` and output field `completion_tokens`.
- `GET /health` returned `{"status":"ok"}` after restart.

Interpretation:
- Volcengine model service billing is usage based: prompt tokens, completion tokens, cached tokens, and cache storage can be separate billing items.
- PromptPilot-style credits are very small-denomination accounting units. If this product adopts a similar 1 yuan ~= 700-1050 credits model, task credit prices must be much higher numerically than the current stop-loss table.
---

## 2026-05-15

### [VOLC-BILLING-IMPORT] Actual Volcengine bill ledger

Scope:
- Added migration `011_add_volc_billing_rows.py`.
- Added `volc_billing_rows` table for imported Volcengine account billing rows.
- Added `app/services/volc_billing.py` to parse Volcengine TSV exports and upsert rows by transaction number.
- Added `scripts/import_volc_billing.py`.
- Added admin endpoint `GET /api/admin/volc-billing`.
- Imported the user's billing file from `C:\Users\福星1号\Desktop\新建 文本文档.txt`.

Evidence:
- Local py_compile passed for migration, service, import script, admin route, and billing-metering service files.
- `alembic upgrade head` succeeded: `010_add_provider_cost_ledger -> 011_add_volc_billing_rows`.
- Import result: 37 rows, inserted 37, updated 0, consume `243.48`, recharge `80.00`, net `-163.48`.
- DB verification: `volc_billing_rows` rows = 37, consume = `243.480000`, recharge = `80.000000`, net = `-163.480000`.
- `alembic current` returned `011_add_volc_billing_rows (head)`.
- `GET /health` returned `{"status":"ok"}` after API restart.

Accounting rule:
- `provider_usage_costs.estimated_cost_yuan` remains theoretical model-list cost.
- `volc_billing_rows` stores actual account cash movements.
- Later matching should update `provider_usage_costs.actual_cost_yuan` and `match_status` when provider task/order IDs or reliable time-window matching are available.
---

## 2026-05-15

### [CREDIT-PRICING-ENTERPRISE-BREAKEVEN] Text/image pricing raised for enterprise package breakeven

Scope:
- Updated runtime `credit_pricing`:
  - `llm_director_chat`: 6
  - `llm_refine`: 6
  - `image_gen`: 12
  - `pipeline_analysis`: 15
- Left video stop-loss prices unchanged:
  - `video_gen_5s`: 80
  - `video_gen_8s`: 120
  - `video_gen_10s`: 160
- Updated `app/services/credits.py` defaults to match DB.

Evidence:
- User screenshot showed visible Volcengine bill lines totaling `1.177588` yuan: image lines `0.880000` yuan plus token lines `0.297588` yuan.
- Matching local system flow was 2 x `llm_director_chat` plus 1 x `image_gen`.
- New credit total for that flow is `6 + 6 + 12 = 24` credits.
- Enterprise package value is `499 / 10000 = 0.0499` yuan/credit, so 24 credits = `1.1976` yuan.
- Enterprise-package margin for the visible bill is `1.1976 - 1.177588 = 0.020012` yuan.
- DB update affected 4 rows and post-update prices matched the table above.
- Local and container py_compile passed for `app/services/credits.py`.
- API/text/image/video/admin containers were restarted; `GET /health` returned ok.

Note:
- This is still a breakeven floor, not a healthy gross-margin commercial price. It prevents loss at the current enterprise package rate for the observed text+image case.
---

## 2026-05-15

### [COST-GUARD] Daily platform and user spend guard

Scope:
- Added config defaults:
  - `platform_daily_cost_limit_yuan = 300.0`
  - `platform_daily_cost_warn_ratio = 0.8`
  - `user_daily_credit_limit = 1000`
- Added `app/services/cost_guard.py`.
- Enforced cost guard before credit reservation in:
  - Director task dispatch.
  - Batch image generation.
  - Batch video generation.
  - TTS generation.
- Added admin endpoint `GET /api/admin/cost-guard`.

Evidence:
- Local py_compile passed for `config.py`, `cost_guard.py`, `director.py`, `main.py`, `admin.py`.
- API/text/image/video/admin containers restarted.
- Container py_compile passed for the same API files.
- `GET /health` returned `{"status":"ok"}`.
- Container runtime guard status for user 4 returned platform observed cost `228.090000` yuan against limit `300.0`, usage ratio `0.76030`, blocked `False`; user daily consumed `30` credits against limit `1000`, blocked `False`.

Note:
- This guard blocks new paid generation when the platform daily observed cost reaches the configured limit, or when a user's daily credit spend plus the requested reservation exceeds the configured user daily limit.
---

## 2026-05-15

### [USER-SPEND-LIMIT-SETTINGS] Customer daily credit limit and unlimited toggle

Scope:
- Added migration `013_add_user_spend_limits.py`.
- Added `user_spend_limits` table with one row per user, nullable daily limit, and `is_unlimited`.
- Added `GET /api/credits/spend-limit` and `PUT /api/credits/spend-limit`.
- Updated `cost_guard.py` to read the user setting:
  - Custom daily limit overrides the system default.
  - `is_unlimited=true` bypasses only the user's own limit.
  - Platform daily cost guard still runs before user-limit logic.
- Rebuilt `/settings` page content to include a friendly daily spend limit card with used/remaining/default stats, numeric limit input, unlimited checkbox, save, and refresh.

Evidence:
- Local py_compile passed for the backend files and migration.
- `cd frontend; npm run build` passed.
- Hot-copied backend/frontend files into API/nginx containers.
- Ran `alembic upgrade head`; `alembic current` returned `013 (head)`.
- DB table inspection confirmed `user_spend_limits` exists with FK, unique user constraint, and positive-limit check constraint.
- API health returned ok after restart.
- API verification:
  - `GET /api/credits/spend-limit` returned default `1000` credits for a new test user.
  - `PUT` custom limit `1` persisted and returned remaining `1`.
  - `PUT` unlimited persisted and returned `daily_credit_limit=null`, `is_unlimited=true`.
  - A batch image request under a `1` credit daily limit returned HTTP `429` with `User daily credit limit reached`, before provider dispatch.
  - Direct service check allowed unlimited user reservation simulation.
  - Direct service check with temporary platform limit `1` returned 429, confirming global platform guard still overrides user unlimited.

Operational note:
- Full compose rebuild was blocked by Docker gRPC `x-docker-expose-session-sharedkey` non-printable header error. Runtime was updated by hot-copy plus API restart.
---

## 2026-05-15

### [DIRECTOR-FINAL-EXPORT] Async FFmpeg final video export

Scope:
- Added async endpoint `POST /api/director/export-final`.
- Added Celery task `director_export_final_task`.
- Extended `video_edit.py` with `export_final_video()` for:
  - local/HTTP video sources,
  - input download safety limit,
  - stream probing,
  - H.264/AAC/yuv420p normalization,
  - silent audio injection for no-audio clips,
  - final MP4 concatenation.
- Final export uploads `final.mp4` to OSS and writes `final_url` plus metadata into `tasks.result`.
- Added `/director/produce` UI control for "导出最终成片" with task polling, progress, and final URL display.
- Updated `Dockerfile` to install `ffmpeg`.

Evidence:
- Local py_compile passed for backend files.
- Frontend `npm run build` passed.
- Local FFmpeg smoke test exported two generated one-second clips into a valid `final.mp4`, `10812` bytes, about `2.021` seconds.
- API/worker/frontend files were hot-copied into running containers.
- Container py_compile passed.
- API and worker-admin restarted; `/health` returned `ok`.
- Celery inspect showed `app.tasks.director_tasks.director_export_final_task` registered on the default/admin worker node.
- Empty export API verification returned `400 No produced videos found for export` before task dispatch.

Blocker:
- Current `worker-admin` runtime image lacks the `ffmpeg` binary.
- Rebuild is still blocked by Docker Desktop gRPC header error in this environment.
- In-container apt installation timed out and did not install FFmpeg.
- Do not claim real container export completion until the image is rebuilt with the updated Dockerfile and a real export task produces an OSS `final_url`.

---

## 2026-05-15

### [PAYMENT-UPGRADE-CHAIN] Free -> Tier upgrade chain + callback success-path evidence

Scope:
- Added migration and runtime support for tier-upgrade orders:
  - `users.tier_expires_at`
  - `orders.order_type/plan_id/tier_target/tier_days`
- Extended payment APIs:
  - `GET /api/payment/plans` now returns `credit_plans` + `tier_plans` (plus legacy `plans`)
  - `POST /api/payment/create-order` accepts `order_type` (`topup` / `tier_upgrade`)
- Added front-end upgrade flow on recharge page (topup + tier upgrade tabs).
- Fixed tier-upgrade callback processing:
  - asyncpg type ambiguity on tier update SQL
  - `credit_transactions.balance_after` NOT NULL compatibility for topup/bonus rows
- Improved create-order error handling:
  - unconfigured channel now returns HTTP 400 (`WeChat Pay not configured` / `Alipay not configured`) instead of generic 500.

Evidence:
- Alembic:
  - `docker exec saas--api-1 alembic current` -> `013 (head)`
- DB schema:
  - `\d+ users` includes `tier_expires_at`
  - `\d+ orders` includes `order_type/plan_id/tier_target/tier_days` and `idx_orders_order_type`
  - `\d+ user_spend_limits` exists
- API:
  - `GET /api/payment/plans` returns both credit and tier plan arrays
  - `GET /api/auth/me` returns `tier_expires_at`
- Success-path callback verification (repeatable script):
  - Added `scripts/verify_payment_upgrade_callback.py`
  - Executed in API container:
    - `docker cp scripts/verify_payment_upgrade_callback.py saas--api-1:/app/scripts/verify_payment_upgrade_callback.py`
    - `docker exec saas--api-1 python /app/scripts/verify_payment_upgrade_callback.py`
  - Output confirmed:
    - callback HTTP 200 `"success"`
    - order -> `status=paid`, `order_type=tier_upgrade`
    - user -> `tier=pro`, `tier_expires_at` set
    - bonus transaction exists with non-null `balance_after`
  - Script cleans temporary test rows after evidence capture.

Residual notes:
- The script verifies callback success path by mocking `verify_alipay_callback` (focus: route/process/update chain).
- Real gateway signature trust still depends on runtime payment channel credentials and production callback requests.

---

## 2026-05-15

### [DIRECTOR-FINAL-EXPORT-RUNTIME] FFmpeg installed in running API/worker containers

Scope:
- Installed FFmpeg in `saas--worker-admin-1` for the new async final export task.
- Installed FFmpeg in `saas--api-1` as well, so the legacy synchronous concat path is not left without the binary.
- Restarted `saas--worker-admin-1` after worker install.

Evidence:
- `saas--worker-admin-1`: `ffmpeg version 7.1.4-0+deb13u1`.
- `saas--api-1`: `ffmpeg version 7.1.4-0+deb13u1`.
- Container smoke test in `saas--worker-admin-1` generated two one-second clips and called `export_final_video()`.
- Smoke result:
  - `clip_count`: 2
  - `duration_sec`: `2.021016`
  - `file_size`: `38502`
  - output path inside temporary container directory: `/tmp/ffmpeg_export_container_4l3w_lov/final.mp4`
- `GET /health` returned `ok`.

Remaining boundary:
- Full Celery export task to public `final_url` still requires OSS credentials. Current runtime reports missing `oss_access_key` and `oss_secret_key`, so upload cannot be honestly accepted yet.
- Dockerfile has been updated for durable image builds, but full rebuild is still blocked by the Docker Desktop gRPC header error in this Windows environment.
- Git metadata is currently degraded: workspace `.git` points to unavailable `C:/tmp/saas-git`, so `git status` fails until the gitdir is restored.

---

## 2026-05-15

### [DIRECTOR-FINAL-CUT-WORKBENCH] Visible final editing workbench

Scope:
- Added persistent final edit plans:
  - migration `014_add_final_edit_plans.py`
  - table `final_edit_plans`
  - service `app/services/final_edit.py`
- Added customer-facing APIs:
  - `GET /api/projects/{project_id}/final-edit-plan`
  - `PUT /api/projects/{project_id}/final-edit-plan`
- Updated final export:
  - `POST /api/director/export-final` accepts `edit_plan`
  - Celery task uses enabled clips, order, trim, transitions, generated subtitles, and BGM path from the edit plan
  - `export_final_video()` accepts `{source, trim_start, trim_end}` source specs
- Added front-end page:
  - `/director/final-cut`
  - `/director/final-cut/:projectId`
  - file `frontend/src/pages/director/final-cut.vue`
- Added an entry link from `/director/produce` to the final cut workbench.

User-facing first version:
- Project selector.
- Shot list with video thumbnails.
- Enable/disable each shot.
- Move shots up/down.
- Trim start/end seconds.
- Per-shot transition selector.
- Subtitle edit field.
- Burn subtitles toggle.
- BGM path field.
- Export progress and final link display.

Evidence:
- Local backend py_compile passed for all changed Python files.
- Frontend `npm run build` passed and produced `final-cut` chunks.
- Hot replacement completed into API, worker-admin, and nginx containers.
- Container py_compile passed for API and worker files.
- `alembic upgrade head` succeeded and runtime DB is `014 (head)`.
- Postgres `\d final_edit_plans` verified the table, unique constraint, indexes, and FKs.
- `/health` returned `ok`.
- Authenticated API smoke verified:
  - default edit plan generation from a produced shot,
  - saving trim/subtitle settings,
  - cleanup of temporary verification rows.
- Worker FFmpeg trim smoke verified two generated clips with per-clip trims exported successfully:
  - `clip_count`: 2
  - `duration_sec`: `2.52`
  - `file_size`: `46802`

Remaining boundary:
- Public final URL export still depends on OSS credentials being present in the running containers.
- BGM is currently a path/URL field, not yet a polished asset picker.
- Cover generation settings are captured but not yet wired to a generated cover asset.

---

## 2026-05-15

### [FINAL-CUT-BGM-ASSETS] BGM upload, URL import, selection, and FFmpeg mix

Scope:
- Added BGM asset controls to `/director/final-cut`:
  - upload audio,
  - import direct audio URL,
  - select project audio asset,
  - preview selected audio,
  - adjust BGM volume,
  - save BGM path and volume into the edit plan.
- Added backend URL import endpoint:
  - `POST /api/projects/{project_id}/assets/import-url`
- Added audio validation for `asset_type=audio`.
- Fixed raw SQL JSONB insert paths for `assets.metadata_json` by using `json.dumps(...)` and `CAST(:metadata_json AS JSONB)`.
- Updated FFmpeg export path:
  - `export_final_video(..., bgm_volume=...)`
  - `/assets/...` audio paths resolve to `storage/projects/...`
  - BGM is mixed through FFmpeg with a `volume` filter before `amix`.
- Updated `director_export_final_task` to pass `bgm_volume` from the edit-plan export payload.

Evidence:
- Local backend py_compile passed.
- Frontend `npm run build` passed.
- Hot replacement completed into API, worker-admin, and nginx containers.
- Container py_compile passed for API and worker files.
- API and worker restarted.
- `/health` returned `ok`.
- Worker FFmpeg BGM smoke produced a valid final MP4:
  - audio stream present,
  - `clip_count`: 2,
  - `duration_sec`: `2.48`,
  - `file_size`: `54975`.
- URL import smoke:
  - local nginx served a generated wav,
  - API imported it as an `audio` asset,
  - `file_url` returned `/assets/...wav`,
  - `listAssets(asset_type=audio)` returned 1 item,
  - `upload_mode=url_import`.
- Multipart upload smoke:
  - generated wav uploaded as `asset_type=audio`,
  - `file_url` returned `/assets/...wav`,
  - `listAssets(asset_type=audio)` returned 1 item,
  - `upload_mode=stream`.
- Temporary verification data and files were cleaned.

Boundary:
- Direct URL import supports direct audio files only, not arbitrary music pages.
- No external music licensing/API provider has been integrated yet.
- For commercial use, third-party music API integration must be chosen with licensing terms first.

---

## 2026-05-16

### [FINAL-EXPORT-LOCAL-FALLBACK] No-OSS export now returns downloadable API video

Issue:
- User exported from final cut workbench and could not find the final video.
- Investigation showed two recent `director_export_final` tasks failed at progress `88`.
- Failure reason: `OSS credentials not configured (OSS_ACCESS_KEY / OSS_SECRET_KEY)`.
- Since FFmpeg output was written in a temporary directory, the failed task cleaned the temporary MP4 and no durable final file remained.

Scope:
- Added migration `015_add_final_video_blobs.py`.
- Added `final_video_blobs` table for local/no-OSS fallback storage.
- Added authenticated endpoint:
  - `GET /api/director/final-video/{task_id}`
- Updated `director_export_final_task`:
  - OSS remains the preferred path,
  - when OSS upload fails, final MP4 bytes are saved to `final_video_blobs`,
  - task completes successfully with `storage_mode=db_blob`,
  - `final_url` becomes `/api/director/final-video/{task_id}`.

Evidence:
- Local py_compile passed.
- API and worker container py_compile passed.
- `alembic upgrade head` succeeded after fixing `task_id` type to UUID.
- Runtime DB is `015 (head)`.
- Postgres `\d final_video_blobs` confirmed table and FKs.
- API and worker restarted; `/health` returned `ok`.
- Full fallback smoke succeeded:
  - temporary user/project,
  - two generated local worker MP4 clips,
  - `POST /api/director/export-final`,
  - task status `done`,
  - result `storage_mode=db_blob`,
  - result `file_size=37768`,
  - authenticated GET of `/api/director/final-video/{task_id}` returned HTTP 200, `Content-Type: video/mp4`, length `37768`.
- Temporary verification data and files were cleaned.

Operational note:
- The user's earlier failed task cannot be recovered because the temporary FFmpeg output was deleted after upload failure.
- Re-exporting after this fix should produce a final video link even without OSS credentials.
- DB blob fallback is for local/dev continuity; production should configure OSS/CDN.
## 2026-05-16

### [FINAL-CUT-RECIPES] Creator editing tutorials became a visible recipe library

Scope:
- Added `data/final_cut_recipes/editing_thinking_rules.json`.
- Added `data/final_cut_recipes/effect_recipes.json`.
- Added `app/services/final_cut_recipes.py`.
- Added APIs:
  - `GET /api/director/final-cut-recipes`
  - `GET /api/director/final-cut-recipes/{recipe_id}`
- Updated `frontend/src/pages/director/final-cut.vue` with a visible "剪辑思维库" panel.
- Updated `frontend/src/api/director.ts` with `getFinalCutRecipes`.

Recipe coverage:
- 古法剪辑镜头组接连续性.
- 旅拍 Vlog 分段剪辑.
- 音乐衔接三法.
- 特写镜头组 + 大全景视觉张力.
- 大片感/高级感慢-快-慢节奏.
- 去雾通透增强.
- 年份数字闪切揭示.
- 音乐播放器效果.
- 人物定格描边效果.

Evidence:
- Backend py_compile passed locally and inside API container.
- Both JSON recipe files passed `python -m json.tool`.
- Frontend `npm run build` passed.
- API runtime loaded 9 recipe IDs.
- `/health` returned ok after API restart.

Boundary:
- This change creates the knowledge and UI layer. It does not yet auto-apply every recipe to FFmpeg output.
- Planning-only rules are separated from executable/approximate effects so the AI does not overclaim.
- Duplicate advanced/大片感 pacing tutorial content was merged into one canonical rule.
## 2026-05-17

### [FINAL-CUT-AI-PLAN] Shared Doubao access now supports AI final-cut planning

Scope:
- Added `app/services/final_cut_ai.py`.
- Added `final_cut_ai_plan` to `DEFAULT_PRICING`.
- Updated `tests/unit/test_credit_pricing.py` expected operation list.
- Added `POST /api/director/final-cut-plan/ai`.
- Updated `frontend/src/api/director.ts`.
- Updated `frontend/src/pages/director/final-cut.vue` with an AI plan application control.

Behavior:
- The endpoint reuses existing Doubao access and `key_pool`.
- The business operation is separated as `final_cut_ai_plan`.
- The AI can only generate a structured edit plan; it does not export video.
- The backend preserves original `video_url`, `prompt`, and `duration`, so AI cannot invent media.
- Generated plans are saved into `final_edit_plans` and can be reviewed before export.

Evidence:
- Local backend py_compile passed.
- Frontend build passed.
- API container py_compile passed.
- Runtime API route registration confirmed `/api/director/final-cut-plan/ai`.
- Runtime pricing check confirmed `final_cut_ai_plan` is available.
- Runtime merge smoke confirmed generated clip ordering is applied safely.
- `/health` returned ok.

Boundary:
- Host unit test run is blocked by missing `asyncpg`.
- API container does not have pytest installed, so container unit test execution is not available.
- Full live Doubao call was not run during this pass to avoid uncontrolled token consumption; the route is wired through the existing configured key pool.
## 2026-05-18

### [FINAL-CUT-LOCAL-RULE-APPLY] Recipe rules can now modify edit plans without AI tokens

Scope:
- Added `app/services/final_cut_rule_apply.py`.
- Added `POST /api/director/final-cut-plan/apply-rule`.
- Updated `frontend/src/api/director.ts`.
- Updated `frontend/src/pages/director/final-cut.vue` with a no-token `本地应用规则` button.
- Tightened `app/services/final_cut_ai.py` token budget and response contract.

Behavior:
- Users can apply selected editing rules directly to the final edit plan without calling Doubao.
- AI planning remains available as a separate enhanced option.
- Supported deterministic rules:
  - slow-fast-slow cinematic/high-end pacing,
  - closeup group to wide-shot release,
  - travel vlog segmented pacing.

Evidence:
- Local backend py_compile passed.
- Frontend build passed.
- API container py_compile passed.
- `/health` returned ok.
- Runtime route registration confirmed `/api/director/final-cut-plan/apply-rule`.
- Runtime slow-fast-slow smoke produced expected plan:
  - opening wide shot kept,
  - middle closeup trimmed from 5s to 3s,
  - middle transition changed to cut,
  - ending slow shot kept with fade.

Observation:
- A controlled Doubao smoke before the tightening produced a reasonable edit plan but consumed 3071 tokens for only 3 demo clips.
- This confirms local rules should be the default path, with AI reserved for ambiguous or higher-value planning.

## 2026-05-18

### [FINAL-CUT-AI-ASYNC] Avoid 30s timeout in editing workbench

Scope:
- Changed `POST /api/director/final-cut-plan/ai` from a blocking Doubao call to a queued Celery task.
- Added `director_final_cut_ai_task` on the text worker.
- Updated `/director/final-cut` to submit the AI plan task, poll progress, and write the returned plan into the editor.
- Added visible AI planning progress and token usage note in the final-cut UI.

Reason:
- The frontend global axios timeout is 30000ms, while Doubao planning can exceed 30s.
- The screenshot error `超时时间超过30000毫秒` was therefore a synchronous AI planning UX failure, not an FFmpeg crash.

Behavior:
- Local rule application remains the recommended zero-token path.
- AI planning now returns `task_id` immediately and runs through the existing cost guard, rate limit, credit reserve/charge/refund, and task status flow.
- Worker saves the final edit plan only after AI returns a validated executable JSON plan.

Evidence:
- Local py_compile passed for `app/routes/director.py`, `app/tasks/director_tasks.py`, `app/services/final_cut_ai.py`.
- `cd frontend; npm run build` passed.
- `python -m pytest tests/unit/test_project_brain.py -q` passed: 11 tests.
- Hot-published backend files to `saas--api-1` and `saas--worker-text-1`.
- Hot-published frontend `dist` to `saas--nginx-1`.
- Restarted `saas--api-1` and `saas--worker-text-1`.
- Container py_compile passed.
- Container import confirmed `app.tasks.director_tasks.director_final_cut_ai_task`.
- `/health` returned ok.

## 2026-05-19

### [PROJECT-BRAIN-PRODUCTION-LEDGER] Long-form progress ledger added to project brain

Scope:
- Added `production_ledger` to `app/services/project_brain.py`.
- Updated `frontend/src/pages/director/produce/ProductionFlowPanel.vue` to show the ledger.
- Added unit coverage in `tests/unit/test_project_brain.py`.

Behavior:
- The project brain now tracks more than "current shot count":
  - target total duration,
  - planned duration,
  - generated video duration,
  - remaining duration,
  - current minute range,
  - current/previous/next scene,
  - scene-level image/video completion,
  - locked and reusable asset anchors.
- Long-form projects such as a 40-minute target can now expose whether the current batch is only a small segment, instead of implying the project is complete after a few clips.

Evidence:
- `python -m py_compile app/services/project_brain.py tests/unit/test_project_brain.py` passed.
- `python -m pytest tests/unit/test_project_brain.py -q` passed: 12 tests.
- `cd frontend; npm run build` passed.
- Hot-published `project_brain.py` to `saas--api-1` and frontend `dist` to `saas--nginx-1`.
- Restarted `saas--api-1`.
- Container py_compile passed for `app/services/project_brain.py`.
- `/health` returned ok.
- Nginx static bundle contains `Production Ledger`.

### [CREATOR-RULES-PROMPT-LAYERS] Creator techniques lowered into executable prompt layers

Scope:
- Added deterministic visual/performance rules in `app/services/visual_quality_rules.py`.
- Wired visual quality and human performance controls into Seedream image payloads and Seedance video payloads.
- Wired camera motion controls only into Seedance video payloads.
- Added `app/services/voice_delivery_rules.py` and wired it into `app/services/tts.py` before Ark TTS calls.
- Added focused unit coverage for visual quality, camera motion, human performance, and TTS delivery shaping.

Behavior:
- AI image/video prompts now get short no-token quality controls for:
  - natural light instead of flat all-over lighting,
  - foreground/midground/background depth,
  - emotional color atmosphere,
  - lower AI/plastic feel,
  - believable micro-expression and body-action linkage.
- Video prompts additionally get camera formula controls:
  - shot type,
  - motion direction,
  - speed/rhythm,
  - subject and environment continuity.
- TTS payloads are compiled before provider call:
  - long plain lines get punctuation pauses,
  - tense delivery can force a mid-line pause,
  - warning/tense/warm contexts infer speed, volume, and `delivery_profile`,
  - acting instructions are not injected into spoken text.

Evidence:
- `python -m py_compile app/services/visual_quality_rules.py app/services/ref_resolver.py app/services/voice_delivery_rules.py app/services/tts.py tests/unit/test_visual_quality_rules.py tests/unit/test_voice_delivery_rules.py tests/unit/test_ref_resolver_prompt_layers.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_visual_quality_rules.py tests/unit/test_voice_delivery_rules.py tests/unit/test_ref_resolver_prompt_layers.py -q` passed: 23 passed, 1 skipped.
- Hot-published prompt/TTS rule files to `saas--api-1`, `saas--worker-image-1`, `saas--worker-video-1`, and `saas--worker-text-1`.
- Restarted api/image/video/text containers.
- Container py_compile passed for api/image/video/text touched files.
- Container smoke check confirmed TTS tense line compiles to `下一个，不是就到我了`, speed `0.86`, volume `0.95`, profile `tense_breathing_pauses`.
- `/health` returned ok.
- The skipped test requires local `asyncpg`; runtime container checks covered imports and compilation.

### [CONTENT-HUMANIZER-WRITE-SCRIPT] Publish copy naturalization layer added

Scope:
- Added `app/services/content_humanizer.py`.
- Wired `/api/director/write-script` to apply the deterministic humanizer by default.
- Added `humanize_copy`, `humanize_strength`, and `platform` request support through the existing body.
- Added unit coverage in `tests/unit/test_content_humanizer.py`.

Behavior:
- The humanizer is a no-extra-token post-processing layer for generated scripts/copy.
- It supports `light`, `medium`, and `deep` strengths.
- It preserves paragraph structure while removing common AI cliches, reducing stiff formal wording, splitting long sentences, and optionally adding short human rhythm lines.
- The endpoint now returns `humanize` metadata with enabled state, strength, changed count, changed rules, and a note that this improves readability but does not guarantee platform review results.

Evidence:
- `python -m py_compile app/services/content_humanizer.py app/routes/director.py tests/unit/test_content_humanizer.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_visual_quality_rules.py tests/unit/test_voice_delivery_rules.py tests/unit/test_content_humanizer.py -q` passed: 27 tests.
- Hot-published `content_humanizer.py` and `director.py` to `saas--api-1`.
- Restarted `saas--api-1`.
- Container py_compile passed for touched files.
- Container smoke check transformed `在当今这个快节奏的时代...` into more natural copy and returned `changed_count=4`.
- `/health` returned ok.

### [PROJECT-BRAIN-DIRECTOR-LEDGERS] Project brain upgraded from status checker to director ledger system

Scope:
- Added `app/services/project_brain_ledgers.py`.
- Updated `app/services/project_brain.py` to include four new general-purpose director ledgers in `context` and aggregate their signals into `signals`, `risks`, and `missing`.
- Updated `frontend/src/pages/director/produce/ProductionFlowPanel.vue` to show four compact director ledger panels.
- Added `tests/unit/test_project_brain_ledgers.py`.

Behavior:
- The project brain now exposes:
  - `creative_technique_ledger`: matched creative techniques, applied/candidate/missing stages, per-shot usage, and execution-layer coverage.
  - `story_continuity_ledger`: current/previous/next scene, minute range, scene goals, continuity gaps, and handoff questions.
  - `cost_risk_ledger`: remaining image/video/TTS/final-edit operations and reuse-first guardrail actions.
  - `final_quality_ledger`: final-cut readiness, missing video/BGM/audio, review blockers, subtitle/theme/edit-plan risks.
- The design is generic: it depends on common project/shot/review/edit-plan fields, not a single project or genre.
- Genre-specific or platform-specific strategies can be layered later as inputs while keeping these base ledgers reusable.

Evidence:
- `python -m py_compile app/services/project_brain.py app/services/project_brain_ledgers.py tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 16 tests.
- `cd frontend; npm run build` passed.
- Hot-published `project_brain.py` and `project_brain_ledgers.py` to `saas--api-1`.
- Hot-published frontend `dist` to `saas--nginx-1`.
- Restarted `saas--api-1` and `saas--nginx-1`.
- Container py_compile passed for the touched backend files.
- Container smoke check returned all four ledger keys.
- `/health` returned ok.
- `/director/produce` returned 200.

Follow-up deep check:
- Built a synthetic multi-scene project with English `Episode 1 Scene 1/2`, matched libraries, reviews, visual budget, and final edit plan.
- Found and fixed two issues:
  - production ledger scene parsing only handled Chinese `第1集第2场`; now also handles explicit `episode/scene`, `EP1SC2`, and `Episode 1 Scene 2`.
  - creative technique signal count used a different summary denominator than the ledger top-level count; now signals use top-level applied/candidate/total counts.
  - cost risk now respects visual budget `watch` as `watch`, not `ok`.
- Re-ran ledger tests: 16 passed.
- Re-ran synthetic deep check:
  - production current scene and story current segment both returned `E01S02`,
  - creative top-level applied count matched signal count,
  - cost risk returned `watch`,
  - final quality blockers surfaced `missing_video` and `missing_bgm`.
- Rebuilt frontend and hot-published backend/frontend again.
- Container py_compile passed, `/health` ok, `/director/produce` 200.

### [PROJECT-BRAIN-EXECUTION-TRACE] Visible brain process added to produce page

Scope:
- Added `frontend/src/pages/director/produce/BrainExecutionTrace.vue`.
- Updated `frontend/src/pages/director/produce/index.vue` to render it below the production workflow.

Behavior:
- The produce page now shows a readable execution trail for the project brain:
  - workspace read,
  - brain analysis,
  - production progress ledger,
  - creative technique check,
  - story continuity check,
  - cost guardrail check,
  - final quality check,
  - next instruction,
  - latest execution result after `继续推进`.
- The trace is derived from existing workspace/brain/shot/chat state, so it adds no model call and no extra token cost.

Evidence:
- `cd frontend; npm run build` passed.
- Hot-published frontend `dist` to `saas--nginx-1`.
- Restarted `saas--nginx-1`.
- `/health` returned 200.
- `/director/produce` returned 200.
- `大脑执行轨迹` / `Brain Execution Trace` are present in source and built assets.

Note:
- `git diff` still fails because this workspace points git at `C:/tmp/saas-git`; no git config was changed.

### [PROJECT-BRAIN-VERBOSE-DEBUG-FLOW] Detailed process ledger expanded

Scope:
- Updated `frontend/src/pages/director/produce/BrainExecutionTrace.vue`.

Behavior:
- Added a default-expanded `详细流程账本` below the brain execution trace.
- Every step now displays:
  - `输入依据`,
  - `判断逻辑`,
  - `产物/调用`,
  - `停止条件`.
- Added action mapping for brain continue actions:
  - `plan_visual_assets`,
  - `generate_keyframes`,
  - `generate_videos`,
  - `plan_final_edit`,
  - `open_final_cut`.
- Added raw workspace file evidence under `展开原始读取清单`.

Evidence:
- `cd frontend; npm run build` passed.
- Hot-published frontend `dist` to `saas--nginx-1`.
- Restarted `saas--nginx-1`.
- `/health` returned 200.
- `/director/produce` returned 200.
- Built assets contain `详细流程账本`, `Verbose Debug Flow`, `输入依据`, and `停止条件`.

### [PROJECT-BRAIN-CONTEXT-COVERAGE] Context read audit made real

Scope:
- Updated `app/services/project_brain.py`.
- Updated `frontend/src/pages/director/produce/BrainExecutionTrace.vue`.
- Added assertions to `tests/unit/test_project_brain.py`.

Behavior:
- `read_files` is now enriched with context audit fields instead of just path/exists/size.
- `context.context_coverage` exposes the same evidence for UI and downstream debugging.
- Each source records role, label, parse status, item count, consumed flag, coverage state, consumers, and missing impact.
- The produce page now shows whether each context file was merely present or actually used by the brain.

Evidence:
- `python -m py_compile app/services/project_brain.py tests/unit/test_project_brain.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 16 tests.
- `cd frontend; npm run build` passed.
- Hot-published backend/frontend to api/nginx containers.
- Restarted api/nginx containers.
- Container py_compile passed for `project_brain.py`.
- `/health` returned 200.
- `/director/produce` returned 200.

### [PROJECT-BRAIN-LEDGER-MERGE-AUDIT] Memory and ledger merge made auditable

Scope:
- Updated `app/services/project_brain.py`.
- Updated `frontend/src/pages/director/produce/BrainExecutionTrace.vue`.
- Added assertions to `tests/unit/test_project_brain.py`.

Behavior:
- Added `context.ledger_merge_audit` to project brain responses.
- The audit explicitly tracks whether progress ledger, role lock, scene lock, asset reuse, creative ledger, cost ledger, final quality ledger, and memory files enter real decisions.
- Each component reports `signals_used`, `consumed_by`, `decision_effect`, and `coverage`.
- The produce page exposes this under `展开账本合并审计`.

Key finding:
- Progress ledger, character lock, scene lock, asset reuse, cost ledger, and quality ledger can influence phase/next_action/risks/missing/final_edit.
- Decision/failure/constraint memory currently remains partial because it is counted and shown but not yet a hard driver of next_action.

Evidence:
- `python -m py_compile app/services/project_brain.py tests/unit/test_project_brain.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 16 tests.
- `cd frontend; npm run build` passed.
- Hot-published backend/frontend to api/nginx containers.
- Restarted api/nginx containers.
- Container py_compile passed for `project_brain.py`.
- `/health` returned 200.
- `/director/produce` returned 200.
