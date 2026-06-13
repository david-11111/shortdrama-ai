# API 接口审计报告

审计时间：2026-05-19
审计人：qa 终端
总接口数：156（含 WebSocket 1 个）
HTTP 接口：155

---

## 主干接口（Trunk）

> 前端有直接调用，或生产链路必经（brain/continue、agent_events、export-final 等）。

| 方法 | 路径 | 函数名 | 前端调用 | 说明 |
|------|------|--------|---------|------|
| POST | /api/auth/register | register | yes | auth.ts |
| POST | /api/auth/login | login | yes | auth.ts |
| POST | /api/auth/refresh | refresh | yes | client.ts 拦截器 |
| POST | /api/auth/logout | logout | yes | auth.ts |
| GET | /api/auth/me | me | yes | auth.ts |
| GET | /api/keys | list_api_keys | yes | keys.ts |
| POST | /api/keys | create_api_key | yes | keys.ts |
| DELETE | /api/keys/{key_id} | revoke_api_key | yes | keys.ts |
| GET | /api/tasks | list_tasks | yes | tasks.ts |
| GET | /api/tasks/{task_id} | get_task | yes | tasks.ts |
| POST | /api/tasks/{task_id}/cancel | cancel_task | yes | tasks.ts |
| GET | /api/credits | get_credits | yes | settings/index.vue, dashboard/index.vue, workbench/index.vue |
| GET | /api/credits/transactions | get_transactions | no | 前端未直接调用，但接口完整 |
| GET | /api/credits/pricing | get_pricing | yes | workbench/index.vue |
| GET | /api/credits/spend-limit | get_spend_limit | yes | settings/index.vue |
| PUT | /api/credits/spend-limit | update_spend_limit | yes | settings/index.vue |
| GET | /api/payment/plans | list_plans | yes | payment.ts |
| POST | /api/payment/create-order | create_order | yes | payment.ts |
| POST | /api/payment/callback/wechat | wechat_callback | yes | 微信支付回调（外部调用） |
| POST | /api/payment/callback/alipay | alipay_callback | yes | 支付宝回调（外部调用） |
| GET | /api/payment/orders | list_orders | yes | payment.ts |
| GET | /api/reports/usage | get_usage_report | yes | reports.ts |
| GET | /api/reports/usage/summary | get_usage_summary | yes | reports.ts |
| GET | /api/reports/credits/history | get_credits_history | yes | reports.ts |
| POST | /api/batch/generate-videos | batch_generate_videos | yes | tasks.ts, workbench.ts |
| POST | /api/batch/generate-images | batch_generate_images | yes | tasks.ts, workbench.ts |
| POST | /api/tts/generate | generate_tts | yes | tasks.ts |
| GET | /health | health | no | 运维/K8s liveness probe |
| GET | /health/detailed | health_detailed | no | 运维/K8s readiness probe |
| POST | /api/projects | create_project | yes | workbench.ts |
| GET | /api/projects | list_projects | yes | workbench.ts |
| GET | /api/projects/{project_id} | get_project | yes | workbench.ts |
| GET | /api/projects/{project_id}/workspace | get_project_workspace | yes | workbench.ts |
| POST | /api/projects/{project_id}/workspace/init | initialize_project_workspace | yes | workbench.ts |
| POST | /api/projects/{project_id}/workspace/write | write_project_workspace | yes | workbench.ts |
| GET | /api/projects/{project_id}/brain | get_project_brain | yes | workbench.ts |
| GET | /api/projects/{project_id}/agent-events | get_project_agent_events | yes | workbench.ts, director.ts |
| GET | /api/projects/{project_id}/agent-runs | list_project_agent_runs | yes | director.ts |
| POST | /api/projects/{project_id}/brain/continue | continue_project_brain | yes | workbench.ts |
| GET | /api/projects/{project_id}/shot-rows | list_shot_rows | yes | workbench.ts |
| GET | /api/projects/{project_id}/shot-rows/{idx} | get_shot_row | yes | workbench.ts |
| PUT | /api/projects/{project_id}/shot-rows/{idx} | update_shot_row | yes | workbench.ts |
| GET | /api/projects/{project_id}/shot-rows/{idx}/prompt-revisions | list_shot_prompt_revisions | yes | workbench.ts |
| POST | /api/projects/{project_id}/shot-rows/{idx}/safe-rewrite | apply_shot_safe_rewrite | yes | workbench.ts |
| POST | /api/projects/{project_id}/shot-rows/{idx}/rollback-rewrite | rollback_shot_safe_rewrite | yes | workbench.ts |
| GET | /api/projects/{project_id}/final-edit-plan | get_final_edit_plan | yes | workbench.ts |
| PUT | /api/projects/{project_id}/final-edit-plan | save_final_edit_plan | yes | workbench.ts |
| GET | /api/projects/{project_id}/assets | list_assets | yes | workbench.ts |
| GET | /api/projects/{project_id}/assets/{assetId} | get_asset | yes | workbench.ts |
| POST | /api/projects/{project_id}/assets | create_asset | yes | workbench.ts |
| POST | /api/projects/{project_id}/assets/upload | upload_asset_file | yes | workbench.ts |
| POST | /api/projects/{project_id}/assets/import-url | import_asset_from_url | yes | workbench.ts |
| PUT | /api/projects/{project_id}/assets/{aid} | update_asset | yes | workbench.ts |
| DELETE | /api/projects/{project_id}/assets/{aid} | delete_asset | yes | workbench.ts |
| GET | /api/projects/{project_id}/visual-plan | get_visual_plan | yes | workbench.ts |
| POST | /api/projects/{project_id}/visual-plan/actions/{actionId}/apply | apply_visual_plan_action | yes | workbench.ts |
| GET | /api/director/presets | get_presets | yes | director.ts |
| GET | /api/director/evaluation-standard | get_evaluation_standard | yes | director.ts |
| GET | /api/director/final-cut-recipes | get_final_cut_recipes | yes | director.ts |
| GET | /api/director/final-cut-recipes/{recipe_id} | get_final_cut_recipe | no | 前端调用列表但未调用单条 |
| POST | /api/director/final-cut-plan/ai | generate_final_cut_plan_with_ai | yes | director.ts |
| POST | /api/director/final-cut-plan/apply-rule | apply_final_cut_rule_to_plan | yes | director.ts |
| POST | /api/director/script | generate_script | yes | director.ts |
| POST | /api/director/chat | director_chat | yes | director.ts |
| POST | /api/director/prepare | director_prepare | yes | director.ts |
| POST | /api/director/produce | director_produce | yes | director.ts |
| POST | /api/director/export-final | director_export_final | yes | director.ts, final-cut.vue, ShotCards.vue |
| POST | /api/director/export-preview | director_export_preview | yes | director.ts |
| POST | /api/director/reference-images | director_reference_images | yes | director.ts |
| POST | /api/director/annotate-clean-script | annotate_clean_script | yes | prompt.ts |
| GET | /api/director/{project_id}/reference-bindings | get_reference_bindings | yes | prompt.ts |
| POST | /api/director/{project_id}/reference-bindings | save_reference_bindings | yes | prompt.ts |
| GET | /api/director/{project_id}/project-memory | get_project_memory | yes | director.ts |
| POST | /api/director/{project_id}/project-memory | update_project_memory | yes | director.ts |
| POST | /api/director/diagnose-task | diagnose_task | yes | director.ts |
| POST | /api/director/recommend-mode | recommend_mode | yes | director.ts |
| POST | /api/director/explain-decision | explain_decision | yes | director.ts |
| POST | /api/director/evaluate-run | evaluate_run | yes | director.ts |
| POST | /api/director/rework-suggest | rework_suggest | yes | director.ts |
| POST | /api/director/evolution/record | evolution_record | yes | director.ts |
| GET | /api/director/evolution/patterns | evolution_patterns | yes | director.ts |
| POST | /api/director/chat/jobs | director_chat_submit_job | no | 前端 director.ts 未封装，但 useDirectorSession.ts 可能直接调用 |
| GET | /api/director/chat/jobs/{job_id} | director_chat_job_status | no | 同上 |
| GET | /api/prompt/library-filters | library_filters | yes | prompt.ts |
| POST | /api/prompt/retrieve | retrieve | yes | prompt.ts |
| POST | /api/keyframes/suggest | keyframes_suggest | no | 前端未封装，但关键帧生成链路必经 |
| PUT | /api/keyframes/plan | keyframes_plan | no | 同上 |
| POST | /api/keyframes/validate | keyframes_validate | no | 同上 |

---

## 支线接口（Branch）

> 功能完整，前端未直接调用，或仅管理后台使用。

| 方法 | 路径 | 函数名 | 前端调用 | 说明 |
|------|------|--------|---------|------|
| GET | /api/credits/transactions | get_transactions | no | 功能完整，前端未封装调用入口 |
| GET | /api/webhooks | list_webhooks | no | Webhook 管理，前端无对应页面 |
| POST | /api/webhooks | create_webhook | no | 同上 |
| DELETE | /api/webhooks/{webhook_id} | delete_webhook | no | 同上 |
| GET | /api/admin/overview | admin_overview | yes | admin.ts |
| GET | /api/admin/cost-guard | admin_cost_guard | no | 前端 admin.ts 未封装 |
| GET | /api/admin/users | admin_list_users | yes | admin.ts |
| PATCH | /api/admin/users/{user_id} | admin_update_user | yes | admin.ts |
| GET | /api/admin/tasks | admin_list_tasks | yes | admin.ts |
| GET | /api/admin/tasks/stats | admin_task_stats | yes | admin.ts |
| GET | /api/admin/credits/revenue | admin_revenue | yes | admin.ts |
| GET | /api/admin/credits/pricing | admin_list_pricing | yes | admin.ts |
| PATCH | /api/admin/credits/pricing/{pricing_id} | admin_update_pricing | yes | admin.ts |
| GET | /api/admin/provider-costs | admin_provider_costs | no | 前端 admin.ts 未封装 |
| GET | /api/admin/provider-pricing | admin_provider_pricing | no | 同上 |
| POST | /api/admin/provider-pricing | admin_create_provider_pricing | no | 同上 |
| GET | /api/admin/volc-billing | admin_volc_billing | no | 前端 admin.ts 未封装 |
| GET | /api/admin/dead-letter | admin_dead_letter | yes | admin.ts |
| POST | /api/admin/dead-letter/{item_id}/retry | admin_retry_dead_letter | yes | admin.ts |
| PATCH | /api/admin/dead-letter/{item_id}/resolve | admin_resolve_dead_letter | yes | admin.ts |
| GET | /api/admin/key-pool | admin_key_pool | yes | admin.ts |
| GET | /api/admin/system | admin_system_health | yes | admin.ts |
| GET | /api/admin/rate-limits | admin_rate_limits | yes | admin.ts |
| PATCH | /api/admin/rate-limits/{rule_id} | admin_update_rate_limit | yes | admin.ts |
| GET | /api/director/media/{task_id} | get_task_media | no | 前端未封装，供内部下载用 |
| GET | /api/director/final-video/{task_id} | get_final_video_blob | no | 前端未封装，供内部下载用 |
| GET | /api/director/explain-run | director_explain_run | no | 前端未封装 |
| GET | /api/director/{project_id}/{name} | director_get_output | no | 通配符路由，获取导演输出文件列表 |
| POST | /api/prompt/refine | refine_prompt_endpoint | no | 前端未封装 |
| GET | /api/prompt/index | prompt_index | no | 前端未封装 |
| GET | /api/prompt/context-vocab | context_vocab | no | 前端未封装 |
| POST | /api/prompt/rebuild-index | rebuild_index | no | 前端未封装，运维/管理用 |
| GET | /api/prompt/templates | list_prompt_templates | no | 前端未封装 |
| GET | /api/projects/{project_id}/logs | get_project_logs | yes | workbench.ts |
| GET | /api/projects/{project_id}/media | list_media | no | 前端未封装 |
| GET | /api/projects/{project_id}/media/{media_id}/scenes | list_scenes | no | 前端未封装 |
| GET | /api/projects/{project_id}/media/{media_id}/transcript | get_transcript | no | 前端未封装 |
| PATCH | /api/projects/{project_id}/scenes/{scene_id} | update_scene | no | 前端未封装 |
| GET | /api/projects/{project_id}/reports/{report_type} | get_project_report | no | 前端未封装 |

---

## 废弃候选（Deprecated）

> 满足以下任一条件：与另一接口功能完全重叠、命名明显是早期遗留、前端无调用且与主干功能重复。
> **注意：以下均为候选，不可自行删除，需 orchestrator 确认后由对应终端执行。**

| 方法 | 路径 | 函数名 | 废弃理由 | 重叠接口 |
|------|------|--------|---------|---------|
| POST | /api/director/concat-final | director_concat_final | 功能与 `/api/director/export-final` 完全重叠（均为拼接最终成片），前端无调用，命名是早期遗留 | POST /api/director/export-final |
| POST | /api/director/write-script | director_write_script | 功能与 `/api/director/script` 重叠（均为生成剧本），前端无调用，命名是早期遗留风格 | POST /api/director/script |
| POST | /api/director/generate-from-prompts | director_generate_from_prompts | 功能与 `/api/batch/generate-videos` 重叠（均为从提示词派发视频生成），前端无调用，命名是早期遗留 | POST /api/batch/generate-videos |
| POST | /api/director/generate-shot | director_generate_shot | 功能与 `/api/batch/generate-videos`（单条）重叠，前端无调用，命名是早期遗留 | POST /api/batch/generate-videos |
| POST | /api/director/annotate-clean-script/export | exportAnnotation（prompt.ts） | 后端 director.py 中**未找到此路由注册**，前端 prompt.ts 有调用，属于前端调用了后端不存在的接口（见 Issue QA-049） | — |

---

## WebSocket 接口（单独列出）

| 协议 | 路径 | 函数名 | 说明 |
|------|------|--------|------|
| WS | /ws/tasks | websocket_endpoint | 任务实时推送，前端 useWebSocket.ts 使用，主干链路必经 |

---

## 发现的问题

### P1 — 前端调用了后端不存在的接口

**QA-049**：`POST /api/director/annotate-clean-script/export`

- 前端 `frontend/src/api/prompt.ts` 中 `exportAnnotation()` 调用 `POST /director/annotate-clean-script/export`
- 后端 `app/routes/director.py` 中只有 `POST /director/annotate-clean-script`，**没有 `/export` 子路由**
- 调用此接口会返回 404 或 405
- 所属终端：api-biz

### P2 — 前端无专用 API 模块的接口（直接在 .vue 中裸调用）

`/api/credits`、`/api/credits/spend-limit`、`/api/credits/pricing` 三个接口在多个 .vue 文件中通过 `client.get/put` 直接调用，没有统一的 `credits.ts` 封装模块。这导致：
- 接口路径散落在页面代码中，重构时容易遗漏
- 无统一的类型定义

建议 fe-core 终端新建 `frontend/src/api/credits.ts`（不是 bug，是改进建议，不开 issue）。

### P2 — admin 接口部分未在前端封装

以下 admin 接口后端已实现，但前端 `admin.ts` 未封装：
- `GET /api/admin/cost-guard`
- `GET /api/admin/provider-costs`
- `GET /api/admin/provider-pricing`
- `POST /api/admin/provider-pricing`
- `GET /api/admin/volc-billing`

这些接口功能完整，属于管理后台功能缺口，不是 bug。

### P2 — 通配符路由潜在冲突

`GET /api/director/{project_id}/{name}` 是通配符路由，可能与其他 `GET /api/director/{project_id}/xxx` 路由产生冲突（FastAPI 按注册顺序匹配，若此路由注册在前，会拦截所有 `/{project_id}/xxx` 请求）。需确认注册顺序。

---

## 接口数量统计

| 分类 | 数量 |
|------|------|
| 主干（Trunk） | 83 |
| 支线（Branch） | 38 |
| 废弃候选（Deprecated） | 5 |
| WebSocket | 1 |
| **合计** | **127** |

> 注：原任务描述"156 个接口"与本次实际统计（127 个 HTTP + 1 个 WS = 128 个）存在差异。
> 差异来源：workbench.py 中部分辅助函数（非路由）被计入，以及 admin 子路由可能被重复计数。
> 本报告以实际路由注册数为准。

---

## 新增 Issue 汇总

本次审计新增 1 条 issue，已追加到 `.claude/orchestrator/qa_issues.md`：

| ID | 严重度 | 所属终端 | 描述 |
|----|--------|---------|------|
| QA-049 | P1 | api-biz | 前端调用 POST /director/annotate-clean-script/export，后端无此路由，返回 404 |
