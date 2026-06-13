# Orchestrator 状态文件

> **每次执行关键操作后必须更新此文件。** 崩溃后新会话第一件事：读 misconduct.md，然后读这个文件。

---

## 更新时间：2026-05-19

## 当前阶段：项目大脑 8 步流程深度审计

## 已完成（有实际验证证据的）

1. 后端基础链路打通：视频生成（Seedance）、图片生成（Seedream）、文本生成（Doubao）
2. Docker 容器运行正常（9 个服务全部在线）
3. 导演编排引擎迁移：`app/services/director_chat_engine.py`（654 行）
4. director_chat_task 能返回结构化分镜（DB 证据：shot_rows 表有数据，task result 包含 shot_rows 数组）
5. 前端深色主题 UI 已部署（produce 页面）
6. 提示词库数据已复制（21 个 JSON + text2vec 模型 391MB）
7. 提示词检索端点可用（`/api/prompt/retrieve` 返回 3 条匹配）
8. `director/produce` 空分镜保护已修复（API 证据：`shot_indices:[999]` 返回 400 `No shot rows to produce`；DB 证据：最近 2 分钟 `director_produce` 新任务数 0、积分交易 0）
9. 前端 `director/produce` 构建恢复通过（`cd frontend; npm run build` 成功；nginx 已热替换 dist）
10. 项目大脑第 1 步“读取上下文”已加入 `context_coverage`，能显示文件是否存在、解析、消费、缺失影响。
11. 项目大脑第 2 步“合并记忆与账本”已加入 `ledger_merge_audit`，能显示进度账本、角色锁、场景锁、资产复用、成本、质量等是否进入判断。
12. 项目大脑第 3 步“映射创作技巧”已加入 `creative_lowering_audit`，能显示剪辑技巧、光影/景深、真人表演、视频运镜、配音规则、final-cut 配方是否下沉到分镜、Seedream/Seedance/TTS/final_edit_plan 执行边界。
13. 项目大脑第 4 步“检查剧情承接”已加入 `continuity_handoff_audit`，能显示第几集第几场、属于第几分钟、前一场、下一场、承接缺口以及是否进入风险/下一步判断。
14. 项目大脑第 5 步“成本与风控”已加入 `cost_control_audit`，并把自动继续推进限制为关键帧最多 4 个、视频最多 1 个；同时展示资产复用、预算闸门、积分预扣、限流并发是否生效。
15. 项目大脑第 6 步“成片可交付检查”已加入 `final_delivery_audit`，能逐项显示视频、配音/TTS、BGM、剪辑方案、字幕、素材审查、预览/导出是否齐全。
16. 项目大脑第 8 步“回写与复盘”已加入 `feedback_loop_audit`，能显示执行决策、shot_rows 媒体结果、失败记忆、final_edit_plan、after/refresh 是否会进入下一轮大脑。
17. 成片导出硬阻断已补：`export-preview/export-final` 会校验 clips、BGM、字幕、必需配音，不再只靠页面提示。

## 已知未解决问题（诚实清单）

### 严重
1. **前端分镜卡片不显示** — 已补生产/批量任务回写 `shot_rows` 的代码路径，但未做真实外部图片/视频生成验证
2. **35 个原版端点未迁移** — 完整清单见审计报告（misconduct.md 同期产出）
3. **6 个服务模块未迁移**：cover.py, job_registry.py, probe.py, prompt_compiler.py, scene_detect.py, video_edit.py
4. **prompt_engine_stub.py 存在于 director/ 子目录** — 可能与 prompt/engine.py 冲突
5. **项目大脑第 7 步仍需同等深度审计** — 执行指令还需要按“真覆盖/半覆盖/伪覆盖”继续补证据链。
6. **剧情承接目前是风险提示，不是全局强阻断** — multi-scene handoff gap 会进入 `story_handoff_gap` 风险；第 5 步已显示它进入风控审计，但尚未禁止全部生成。
7. **手动批量按钮仍需另做风控审计** — 本轮收紧的是项目大脑自动 continue；手动批量图片/视频按钮还需要在后续商业化风控里统一限额。
8. **真实 provider 失败回写尚未做混沌测试** — 失败路径已写 `memory/failures.md`，但本轮未真实触发 Seedream/Seedance provider 失败。

### 中等
5. 向量模型（text2vec-base-chinese）未部署到 Docker 容器内 — 容器内向量检索不可用
6. `project_memory` 表不存在 — director_chat 加载记忆时 warning（不阻塞主流程）
7. Docker 镜像无法 rebuild（pytest-cache 文件被 Windows 锁定）— 当前靠 docker cp 热替换

### 低
8. 前端 localStorage 残留旧会话数据干扰测试
9. Doubao 响应时间 60-150 秒

## 下一步（按优先级）

1. 精简 `director/produce` 分镜校验，避免非法 `shot_indices` 触发 500
2. 将媒体回写 helper 下沉到 `_shared.py`，减少图片/视频任务对导演任务模块的反向依赖
3. 如需彻底验收生产闭环，使用少量真实图片/视频生成跑一条完整链路，并查 `shot_rows.selected_image/selected_video`
4. 补充 QA 回归：空分镜 produce 返回 400 且不扣费；批量任务 payload 包含 `project_id/shot_index`
5. 继续项目大脑第 7 步“发布执行指令”的深度审计：确认 next_action、endpoint、任务类型、队列、预期产物和停止条件是否一致。

## 阻塞项

- misconduct.md 惩罚机制已生效
- 本轮不做真实外部视频/图片生成验证，避免消耗生产资源；用无效分镜拒绝、任务落库、代码级回写路径和构建验证收口

## 当前阶段

phase: `Phase 8 — 集成修复与质量加固`
updated_at: `2026-05-12`
team_structure: `1 + 8`（新增 qa、security 终端）

---

## Phase 8 背景

Phase 1-7 快速迭代出了完整功能，但集成验证时发现：
- **导演链派发全断**（`_dispatch_director_task` 硬编码发到 text_tasks）
- **排队机制仅覆盖 `/api/batch/*`，导演链与 TTS 完全裸奔**
- **支付签名验签未实现**（生产不可用）
- **多处财务漏洞**（取消任务不退积分、批量预扣失败不回滚）
- **缺乏端到端测试**，新增 qa 终端专门防回归
- **缺乏安全专项**，新增 security 终端专注签名/审计/加密

Phase 8 目标：修完 P0 断点 → 建立 qa 冒烟测试 → 修完 P1 安全与体验问题。

---

## 任务分发表（P0 — 立即启动）

### api-biz 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-BIZ-1 | 重写 `_dispatch_director_task`，按 task_type 路由到正确的 Celery 任务 | `app/routes/director.py:174-199` | 5 种导演链任务各自发到对应 task，队列正确（text/default/image） |
| P8-BIZ-2 | 为 `_dispatch_director_task` 加三件套：reserve_credits + check_concurrent_limit + check_rate_limit | 同上 | 参考 `/api/batch/generate-videos` 的实现 |
| P8-BIZ-3 | `/api/tts/generate` 加 check_concurrent_limit + check_rate_limit | `app/main.py:240-280` | 超限返回 429 |
| P8-BIZ-4 | 修 `str(item)` → `json.dumps(item)` 存 tasks.payload | `app/main.py:137, 212` | DB 里 payload 字段是合法 JSON |
| P8-BIZ-5 | 批量端点积分预扣失败回滚 | `app/main.py:105-110, 184-189` | 任一预扣失败，前面已扣全部退还 |
| P8-BIZ-6 | 清理 `workbench.py` 重复的 asset 端点 | `app/routes/workbench.py:155-503` | 每个端点只定义一次 |
| P8-BIZ-7 | 批量端点接入 `workbench_orchestrator.validate_batch_* + prepare_*_payloads` | `app/main.py` batch 端点 | 参考图解析、视角匹配在派发前完成 |
| P8-BIZ-8 | 实现 `tasks.py:124` 的 TODO — 取消任务退预扣积分 | `app/routes/tasks.py:124` | 取消后 credit_account 恢复原值 |
| P8-BIZ-9 | 硬编码积分值改为从 credit_pricing 表读取 | `app/main.py:138, 213, 268` | 调价不用改代码 |
| P8-BIZ-10 | reports.py 分页响应格式统一 | `app/routes/reports.py` | 统一 `{items, total, page, page_size}` |

### worker 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-WRK-1 | 修 `_save_shot_rows` / `_load_shot_rows` 的 PostgreSQL 专用语法 | `app/tasks/director_tasks.py` | 与 alembic/005 表结构对齐（JSONB 用 SQLAlchemy 参数化） |
| P8-WRK-2 | `services/credits.py` 同步包装异步的 asyncio.run 改为原生异步 | `app/services/credits.py:40-50` | 不在异步上下文里 asyncio.run |
| P8-WRK-3 | `key_pool.py` RLock → asyncio.Lock（如确定要异步用）；否则记录同步使用约束 | `app/services/key_pool.py` | Redis 调用不阻塞事件循环 |
| P8-WRK-4 | 修 key_pool cooldown TTL 与时间戳语义错 | `app/services/key_pool.py:~103` | cooldown 按 Redis TTL 过期即可，不存时间戳 |
| P8-WRK-5 | `_shared.py` SYNC_REDIS 改用 asyncio 版本 | `app/tasks/_shared.py` | 任务运行时不阻塞事件循环 |
| P8-WRK-6 | director 任务加积分 charge/refund | `app/tasks/director_tasks.py` | 所有 produce/ref_images/script 成功扣费、失败退款 |

### api-auth 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-AUTH-1 | 注册接口加密码强度校验 | `app/routes/auth.py` | 长度/复杂度规则 |
| P8-AUTH-2 | 配合 security 终端接入 Token 黑名单检查 | `app/middleware/auth.py` | 登出后 Token 失效 |
| P8-AUTH-3 | 登录失败日志记录 | `app/routes/auth.py` | 连续失败 5 次锁定 15 分钟 |
| P8-AUTH-4 | 修 `/auth/me` 的 user_id 字段混淆 | `app/routes/auth.py:94` | 返回 users.id（整数），不混用 user_id 字符串 |

### security 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-SEC-1 | 微信 V3 签名验签 | `app/services/payment.py:204` + `app/security/signing.py` | 回调验签通过才处理订单 |
| P8-SEC-2 | 支付宝 RSA2 签名验签 | `app/services/payment.py:250` + `app/security/signing.py` | 同上 |
| P8-SEC-3 | 支付回调幂等 | `app/services/payment.py` | 订单已处理则直接返回成功，不重复充值 |
| P8-SEC-4 | Token 黑名单服务 | `app/security/token_blacklist.py` + 迁移 | 登出、强制下线可用 |
| P8-SEC-5 | API Key 加盐 HMAC 替代裸 SHA256 | `app/security/hmac.py` | 历史 key 迁移一次 |
| P8-SEC-6 | 管理员审计日志 | `app/security/audit.py` + `app/middleware/audit.py` + audit_log 迁移 | admin 路由全部有审计 |

### devops 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-OPS-1 | 新增 migration 006，补 rate_limit_config 资源：tts_gen、director_script、director_produce、director_ref_images、llm_chat | `alembic/versions/006_*.py` | 三档 tier 都有对应限流配置 |
| P8-OPS-2 | 新增迁移为关键表加约束 | `alembic/versions/007_*.py` | credit_accounts.balance CHECK>=0；shot_rows CHECK、外键约束 |
| P8-OPS-3 | 实现 `/health`、`/health/detailed` 端点规划（与 api-biz 协作接入） | `app/main.py`（协调）+ `monitoring/` | DB/Redis/Celery 状态一目了然 |
| P8-OPS-4 | Prometheus metrics 采集验证 | `monitoring/` | Grafana dashboard 可用 |
| P8-OPS-5 | 备份脚本实现并跑通 | `scripts/backup.sh` | cron 每日备份 PG + Redis snapshot |

### fe-core 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-FEC-1 | Token 刷新后自动重连 WebSocket | `frontend/src/api/client.ts` + `composables/useWebSocket.ts` | 刷新期间不丢消息 |
| P8-FEC-2 | 刷新 Token 失败无限递归保护 | `frontend/src/api/client.ts` | 失败直接登出跳登录页 |
| P8-FEC-3 | 请求去重（幂等按钮） | `frontend/src/api/client.ts` 或 composable | 批量生成狂点只发一次 |
| P8-FEC-4 | 全局错误处理器 + toast | `frontend/src/plugins/` | 替代各页面 alert |
| P8-FEC-5 | 评估 Token 存储方案（httpOnly Cookie vs localStorage+CSP） | — | 给出建议文档，orchestrator 决策 |

### fe-pages 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-FEP-1 | 资产上传改用流式或分片，不全量 Base64 | `frontend/src/pages/workbench/index.vue:140-152` | 100MB 文件不 OOM |
| P8-FEP-2 | 批量生成前端积分预检 | `frontend/src/pages/workbench/index.vue:166-190` | 积分不足提示，不派发 |
| P8-FEP-3 | 所有删除/取消操作加确认弹窗 | 多页面 | 二次确认 |
| P8-FEP-4 | 微信充值二维码用图片展示，替代 alert | `frontend/src/pages/recharge/index.vue:~105` | 原生扫码体验 |
| P8-FEP-5 | `ShotTable.vue` 图片 URL 校验白名单 | `frontend/src/pages/workbench/ShotTable.vue` | 非法 URL 回退占位图 |
| P8-FEP-6 | 任务列表 WebSocket 订阅管理（防重复订阅、分页切换清理） | `frontend/src/pages/tasks/index.vue` | 不泄露订阅 |

### qa 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-QA-1 | 搭建 pytest + playwright 测试框架 | `pytest.ini`、`playwright.config.ts`、`conftest.py` | CI 可跑 |
| P8-QA-2 | 核心链路冒烟测试（脚本→参考图→视频） | `tests/e2e/test_director_pipeline.py` | 覆盖 10 个 P8-BIZ 验收点 |
| P8-QA-3 | 接口契约测试（前端 API vs 后端路由） | `tests/contract/test_api_contract.py` | 发现不匹配报错 |
| P8-QA-4 | 排队三件套集成测试（超限返回 429、并发限制生效） | `tests/integration/test_rate_limit.py` | 三档 tier 全覆盖 |
| P8-QA-5 | 积分预扣/退款/回滚集成测试 | `tests/integration/test_credits.py` | 所有财务路径闭环 |
| P8-QA-6 | 支付回调验签测试（配合 security） | `tests/integration/test_payment_callback.py` | 签名错误拒绝处理 |
| P8-QA-7 | CI 流水线：每次 PR 跑冒烟 | `.github/workflows/qa.yml` | 冒烟失败阻止合并 |
| P8-QA-8 | Bug 跟踪板 | `.claude/orchestrator/qa_issues.md` | 发现的问题全部入表 |

---

## 依赖关系 & 启动顺序

```
第一波（立刻并行启动）：
  devops P8-OPS-1（迁移：rate_limit_config 补资源）
  worker P8-WRK-1（SQL 兼容）
  qa P8-QA-1（搭测试框架）
  security P8-SEC-1/SEC-2（支付验签）

第二波（等第一波部分完成）：
  api-biz P8-BIZ-1/BIZ-2（等 P8-OPS-1 完成，有限流配置可用）
  api-biz P8-BIZ-4/BIZ-5/BIZ-6（独立，可随时做）
  api-biz P8-BIZ-7（等 P8-WRK-1 完成）
  fe-core P8-FEC-1/FEC-2（独立）

第三波（等前端/后端接口定稿）：
  fe-pages 全部任务
  qa P8-QA-2/QA-3（核心链路冒烟，等 api-biz 交付）
  api-auth P8-AUTH-2（等 security P8-SEC-4）

第四波（收尾）：
  devops P8-OPS-3/OPS-4/OPS-5
  qa P8-QA-7（CI 接入）
  security P8-SEC-5/SEC-6
```

---

## Phase 1-7 已完成任务（归档）

详见 `changelog.md`。Phase 1-7 共完成 T1-T26 任务，覆盖：
- Phase 1：基础设施骨架
- Phase 2：用户系统、鉴权、数据隔离
- Phase 3：限流、积分集成
- Phase 4：CORS、结构化日志、Docker、前端页面
- Phase 5：真实 AI API 接入（火山 Ark、Kling、TTS）
- Phase 6：管理后台、支付、邮件、报表
- Phase 7：对象存储、部署、监控

**Phase 1-7 交付完整但未集成验证**，是 Phase 8 的前置。

---

## 待决策事项

| 问题 | 涉及终端 | 优先级 | 决策方 |
|------|---------|--------|-------|
| Token 存储方案（httpOnly Cookie vs localStorage） | fe-core + api-auth + security | P1 | orchestrator + 用户 |
| 导演链是否需要单独终端 | — | — | **已决策**：不新开，由 api-biz + worker + fe-pages 分治，qa 负责端到端 |

---

## 阻塞项

| 阻塞描述 | 阻塞原因 | 等待谁 |
|---------|---------|--------|
| qa 冒烟测试 | 等 api-biz 修完 P8-BIZ-1/2 | api-biz |
| api-auth 接入黑名单 | 等 security 交付 token_blacklist | **已解除**：security P8-SEC-4 完成，AUTH-2 已接入 |
| 批量端点接入 orchestrator | 等 worker 修完 SQL 兼容 | **已解除**：P8-WRK-1 完成 |
| app/middleware/credits.py 需加 await | P8-WRK-2 将 CreditService 改为原生 async，middleware 调用处需加 await | api-biz（在 BIZ-2 顺手补） |
| /health/detailed 补 Celery 检查 | devops 不可写 app/main.py；参考 monitoring/health.py:_check_celery() | api-biz |
| security→devops 配置依赖 | 微信 V3 + 支付宝 RSA2 验签已集成，需 devops 在 app/config.py 加 WECHAT_API_V3_KEY / WECHAT_PLATFORM_CERT_PATH / ALIPAY_PUBLIC_KEY_PATH / ALIPAY_APP_ID，并在 .env.example 加占位 | devops |
| worker 技术债 | WRK-1/5 声称同步化但实际未落地，director_tasks.py 仍有 5 处 asyncio.run，_shared.py 仍有 7 处 asyncio.run（见 qa_issues.md QA-047）。当前能跑但 Celery prefork 下有"Future attached to a different loop"风险 | worker（Phase 9 重做） |

---

## 上次操作记录

```
[2026-05-12] Phase 8 启动。团队 1+6 升级为 1+8，新增 qa、security 终端。
            完成全链路缺陷审查，识别 46 项问题（P0×16、P1×19、P2×11）。
            已拆解为 50 个具体任务，按终端分派完毕。

[2026-05-12] devops 终端完成 P8-OPS-1 ~ P8-OPS-5：
  P8-OPS-1 ✅ alembic/versions/006_add_rate_limit_resources.py
  P8-OPS-2 ✅ alembic/versions/007_add_constraints.py
  P8-OPS-3 ✅ app/main.py:health_detailed() 补 Celery inspect；monitoring/health.py 备用
  P8-OPS-4 ✅ monitoring/grafana-dashboard.json + prometheus.yml
  P8-OPS-5 ✅ scripts/backup.sh（Redis BGSAVE + RDB）

[2026-05-12] worker 终端完成 P8-WRK-1 ~ P8-WRK-6（见上方记录）

[2026-05-13] orchestrator 直接接管，完成剩余 api-biz 核心修复：
  P8-BIZ-1 ✅ director.py:_dispatch_director_task — 按 task_type 路由到正确 Celery 任务
             — 路由表：chat→director_chat_task(text)、script→director_script_task(text)
               prepare→director_prepare_task(default)、produce→director_produce_task(default)
               ref_images→director_reference_images_task(image)
  P8-BIZ-2 ✅ director.py:_dispatch_director_task — 加三件套：check_concurrent_limit + check_rate_limit + reserve_credits
  P8-BIZ-3 ✅ main.py:generate_tts() — 加 check_concurrent_limit + check_rate_limit("tts_gen")
  P8-BIZ-5 ✅ main.py:batch_generate_videos/images — 预扣失败 try/except 回滚已扣积分
  P8-BIZ-8 ✅ tasks.py:cancel_task() — 取消时退还 credits_reserved，写 credit_transactions 记录
  P8-OPS-3 ✅ main.py:health_detailed() — 补 Celery inspect 检查

[2026-05-13] 继续完成剩余任务：
  P8-BIZ-9  ✅ credits.py 新增 get_price() 公开方法；main.py 批量/TTS credits_reserved 改从 DB 读取
  P8-BIZ-10 ✅ reports.py 三个端点统一 {items, total, page, page_size}；/usage 补分页参数
  P8-SEC-1/2/3/4/5/6 ✅ 已由 security 终端完成（signing.py + payment.py + token_blacklist.py + hmac.py + audit.py）
  migration 008 ✅ 已由 security 终端完成（token_blacklist + audit_log + login_attempts + api_keys.hmac_salt）
```

---

## 下一步计划

1. 各终端领取任务，在自己分支上开始
2. orchestrator 监督：每日拉各终端进度到 changelog
3. qa 终端搭好测试框架后，所有 P0 修复必须有对应回归用例
4. Phase 8 全部 P0 完成后，orchestrator 做一轮集成验证，再进 P1
---

## 2026-05-15 Cost Guard

Status: deployed.

Runtime limits:
- Platform daily observed cost limit: 300 yuan.
- Platform warning ratio: 80%.
- User daily credit limit: 1000 credits.

Protected entry points:
- Director task dispatch.
- Batch image generation.
- Batch video generation.
- TTS generation.

Evidence:
- API health returned ok after deployment.
- Container py_compile passed.
- Runtime cost guard check for user 4 returned:
  - platform observed cost: 228.090000 yuan
  - platform limit: 300.0 yuan
  - usage ratio: 0.76030
  - platform blocked: False
  - user 4 daily credits consumed: 30
  - user blocked: False

Residual risk:
- Limits are conservative defaults and should be moved to `.env`/deployment config per environment before wider rollout.
- Guard uses imported actual Volcengine billing rows and local provider estimates; if bills are not imported frequently, provider estimates become more important.

## 2026-05-15 Enterprise Breakeven Pricing

Status: deployed.

Current runtime credit prices:
- `llm_director_chat`: 6
- `llm_refine`: 6
- `image_gen`: 12
- `pipeline_analysis`: 15
- `video_gen_5s`: 80
- `video_gen_8s`: 120
- `video_gen_10s`: 160

Reason:
- User provided Volcengine bill screenshot with visible total `1.177588` yuan for a flow matching 2 text calls plus 1 image generation group.
- At the enterprise package floor (`499 / 10000 = 0.0499` yuan/credit), old 12 credits produced only `0.5988` yuan and would lose money.
- New 24 credits produces `1.1976` yuan, margin `0.020012` yuan against the visible Volcengine cost.

Evidence:
- DB `credit_pricing` updated.
- `app/services/credits.py` updated.
- Local/container py_compile passed.
- API/text/image/video/admin restarted and API health returned ok.

Residual risk:
- Margin is very thin; final commercial prices should include target gross margin and video-specific real bill evidence.

## 2026-05-15 Volcengine Billing Import

Status: deployed and imported current bill.

Changes:
- Added `volc_billing_rows` table.
- Added TSV parser/importer for Volcengine billing exports.
- Added admin billing endpoint `GET /api/admin/volc-billing`.
- Imported user-provided account billing file.

Evidence:
- DB is at `011_add_volc_billing_rows (head)`.
- Imported rows: 37.
- Actual account consumption: 243.480000 yuan.
- Recharge: 80.000000 yuan.
- Net: -163.480000 yuan.
- API health returned ok after restart.

Accounting interpretation:
- `provider_usage_costs` is the task-level theoretical/estimated model cost ledger.
- `volc_billing_rows` is the account-level actual cash movement ledger.
- Free inference quota and resource packages mean actual cash bills can be lower than theoretical model cost. Commercial pricing should use theoretical/conservative cost; actual billing rows are for reconciliation.

## 2026-05-15 Volcengine Free Inference Quota Rule

Status: rule captured.

User-provided billing rule:
- Free inference quota only offsets online inference fees from token post-pay.
- It does not offset plugin, knowledge base, or batch inference token fees.
- It can offset uncached prompt tokens, cached-hit tokens, and output tokens.
- It cannot offset context-cache storage fees.
- Free quota is counted separately per model and shared under the main account.
- Base models and fine-tuned models share the same base-model free quota.
- After quota is exhausted, calls can fail unless the corresponding model service is opened and account requirements are satisfied.

Pricing implication:
- `provider_usage_costs.estimated_cost_yuan` should represent list-price/model-price cost before free quota or discounts.
- `provider_usage_costs.actual_cost_yuan` should represent the matched cash bill after free quota/resource-package offsets.
- Commercial user credit pricing must be based on list-price or conservative expected cost, not on temporary free quota deductions.

Operational risk:
- Free quota can hide true model cost during testing. Once quota is exhausted, the same traffic starts generating cash bills or can fail.
- Production should monitor remaining Volcengine quota/balance and set inference limits to avoid sudden shutoff or runaway bills.

## 2026-05-15 Credit Pricing Stoploss

Status: deployed.

Runtime credit prices:
- `llm_director_chat`: 3
- `llm_refine`: 3
- `image_gen`: 6
- `video_gen_5s`: 80
- `video_gen_8s`: 120
- `video_gen_10s`: 160
- `pipeline_analysis`: 10

Evidence:
- DB `credit_pricing` has the prices above.
- `app/services/credits.py` `DEFAULT_PRICING` has the same prices.
- API health returned ok after restart.

Reason:
- User's Volcengine bill showed 35 consumption rows totaling `243.48` yuan while the previous project pricing only charged 11 credits for the test flow. This stop-loss update prevents obvious cost inversion while provider-level exact matching is still pending.

Residual risk:
- This is not the final official-price-matched model. It should be recalculated after real `provider_usage_costs` rows exist and current Volcengine prices are confirmed.

## 2026-05-15 Provider Cost Ledger

Status: deployed and structurally verified.

Changes:
- Database is at `010_add_provider_cost_ledger (head)`.
- Added `provider_pricing_rules` and `provider_usage_costs`.
- Task completion now extracts nested `billing_usage` and writes task-level provider usage/cost rows.
- Admin can list costs and create/list provider pricing rules.

Evidence:
- `alembic upgrade head` succeeded.
- `provider_pricing_rules` and `provider_usage_costs` exist in Postgres.
- Temporary test price rule estimated 1,000,000 input tokens + 500,000 output tokens as `2.000000` yuan.
- Temporary verification rows were cleaned; remaining verification rows = `0`.
- `GET /health` returned ok.
- API/text/image/video/admin containers restarted and are running.

Residual risk:
- Real provider call after this change is still pending.
- Official Volcengine price rules are not seeded yet; they must be added from current official pricing before using estimated margin reports commercially.

## 2026-05-14 Billing Usage Metering

Status: code deployed, real provider call pending.

Changes:
- Added normalized provider usage records for Doubao, Seedream, and Seedance results.
- Added a Volcengine billing TSV analyzer that counts every `变动金额` row, including small charges.

Current billing evidence from user template:
- Rows: 37.
- Consumption rows: 35.
- Recharge rows: 2.
- Real Volcengine consumption: 243.48 yuan.
- Recharge: 80.00 yuan.
- Net: -163.48 yuan.

Metering rules now represented in result JSON:
- Doubao: input `prompt_tokens`, output `completion_tokens`, total `tokens`.
- Seedream: input prompt chars, negative prompt chars, reference image count; output image count, width, height, pixels.
- Seedance: input prompt chars, reference image count; output video count, duration seconds, resolution, aspect ratio.

Residual risk:
- Volcengine account billing rows are still account-level cash rows and do not identify local task ids. Task-level matching needs either provider order id capture or a separate provider cost ledger table.
- Real provider calls after this change have not been run yet, so actual provider `raw_usage` field availability is still pending confirmation.

## 2026-05-14 Director Produce Hardening

Status: verified for bad-input fail-fast path.

Changes:
- Shared media writeback helpers now live in `app/tasks/_shared.py`.
- `director_tasks.py`, `image_tasks.py`, and `video_tasks.py` use the shared helpers, reducing duplicated writeback logic and removing reverse imports from worker task modules into `director_tasks.py`.
- `/api/director/produce` now normalizes `shot_indices` before dispatch. Non-list input, non-integer values, and non-positive values return 400 instead of risking runtime exceptions or silent empty production.

Evidence:
- Python compile passed for `app/routes/director.py app/tasks/_shared.py app/tasks/director_tasks.py app/tasks/image_tasks.py app/tasks/video_tasks.py`.
- Frontend build passed with `cd frontend; npm run build`.
- Running service health returned `{"status":"ok"}`.
- Invalid shot index API check returned `400 No shot rows to produce`.
- Invalid shot type API check returned `400 shot_indices must be integers`.
- DB evidence after failed calls: `director_produce` tasks in the recent window = `0`; credit transactions for test user `6` in the recent window = `0`.

Residual risk:
- Real provider media generation was not run in this pass. The writeback path is compiled and deployed, but final commercial acceptance still needs one controlled low-cost provider smoke test.

## 2026-05-15 User Spend Limit Settings

Status: deployed and verified on the running local stack.

Changes:
- Added `user_spend_limits` table via Alembic revision `013`.
- Added customer-facing APIs:
  - `GET /api/credits/spend-limit`
  - `PUT /api/credits/spend-limit`
- Updated `app/services/cost_guard.py` so per-user settings override the default user limit.
- `is_unlimited=true` bypasses only the user's own daily limit; the platform daily cash-cost limit is still checked first.
- Updated `/settings` with a "每日消费限额" card showing today's used credits, remaining credits, default limit, a numeric daily limit input, and an "不限额" toggle.

Evidence:
- Local py_compile passed for `app/services/cost_guard.py`, `app/routes/credits.py`, and `alembic/versions/013_add_user_spend_limits.py`.
- Frontend production build passed with `cd frontend; npm run build`.
- Container py_compile passed after hot-copying updated API files.
- `alembic current` returned `013 (head)`.
- Postgres `\d user_spend_limits` confirmed the table, unique user constraint, FK to `users(id)`, and positive-limit check constraint.
- `/health` returned ok after API restart.
- `GET/PUT /api/credits/spend-limit` verified for test user 8:
  - default limit `1000`, consumed `0`, remaining `1000`.
  - custom limit `1`, remaining `1`.
  - unlimited mode returned `daily_credit_limit=null`, `is_unlimited=true`.
- Low-limit paid task smoke test returned HTTP `429` with `User daily credit limit reached` before credit reservation/provider dispatch.
- Direct container service check for unlimited user 11 allowed `credits_to_reserve=999999` without user-limit rejection.
- Direct container service check with temporary platform daily limit `1` returned HTTPException status `429`, proving platform guard still wins even for unlimited users.

Deployment note:
- Full `docker compose up --build` failed with Docker gRPC header error in the current Windows/path environment. Files were hot-copied into API/nginx containers, migration was run in the API container, and API was restarted.

## 2026-05-15 Director Final FFmpeg Export

Status: code deployed to the running stack; full container runtime export is blocked until the worker image includes FFmpeg.

Changes:
- Added a new async final export endpoint: `POST /api/director/export-final`.
- The endpoint validates `project_id`, optional `shot_indices`, confirms there are `selected_video` clips for the current user, applies concurrency/rate limit, reserves `pipeline_analysis` credits, and dispatches a Celery task.
- Added `director_export_final_task` to `app/tasks/director_tasks.py`.
- Added `export_final_video()` to `app/services/video_edit.py`:
  - accepts local paths or HTTP(S) video URLs,
  - downloads remote clips with a 1GB per-input safety limit,
  - probes video/audio streams,
  - normalizes every clip to consistent H.264/AAC/yuv420p MP4,
  - adds silent audio for clips without audio,
  - concatenates clips and returns duration/file-size metadata.
- The export task uploads the finished `final.mp4` to OSS and stores `final_url`, `oss_key`, `clip_count`, `duration_sec`, `file_size`, and source shot metadata in `tasks.result`.
- Added a customer-facing "导出最终成片" control to `/director/produce`; it submits the export, polls the task, shows progress, and displays the final URL when done.
- Updated `Dockerfile` to install `ffmpeg` alongside `curl` for future image builds.

Evidence:
- Local py_compile passed for `video_edit.py`, `director_tasks.py`, `director.py`, and `tasks/__init__.py`.
- Frontend production build passed with `cd frontend; npm run build`.
- Local FFmpeg algorithm smoke test generated two 1-second MP4 clips, exported `final.mp4`, and verified output:
  - `clip_count`: 2
  - `file_size`: 10812 bytes
  - `duration_sec`: about 2.021 seconds
- Hot-copied API/worker/frontend files into the running containers and restarted `saas--api-1` and `saas--worker-admin-1`.
- Container py_compile passed for the API and worker files.
- `GET /health` returned `ok` after restart.
- Celery inspect confirmed `app.tasks.director_tasks.director_export_final_task` is registered on the default/admin worker node.
- `POST /api/director/export-final` with no produced clips returned HTTP `400` and `No produced videos found for export`, before credit reservation or task dispatch.

Runtime blocker:
- The current running `worker-admin` container does not have `ffmpeg` installed (`exec: "ffmpeg": executable file not found in $PATH`).
- Attempting `docker compose up -d --build api worker-admin` still fails in this Windows/Docker environment with the Docker Desktop gRPC `x-docker-expose-session-sharedkey` non-printable header error.
- A direct in-container `apt-get install ffmpeg` attempt timed out and did not install FFmpeg.
- Therefore, the final export code path is ready and locally FFmpeg-tested, but a real container export task cannot be honestly marked complete until the image is rebuilt successfully with the updated Dockerfile.

Cleanup note:
- The local FFmpeg smoke test files were removed, but one permission-broken temporary test directory remains at `storage/tmp_ffmpeg_export_smoke/final_export_m8xdsgtq` from the earlier failed Windows temp-dir experiment. It should be removed after filesystem permissions are repaired outside the sandbox.

## 2026-05-15 Payment Upgrade Chain Self-Check

Status: closed (with evidence).

Completed:
- Free -> tier-upgrade order chain is now wired end-to-end in code:
  - schema, API, callback processing, front-end recharge flow.
- Callback success path has a repeatable verification script:
  - `scripts/verify_payment_upgrade_callback.py`

Verification evidence:
- Runtime DB head: `013 (head)`.
- Schema includes required fields:
  - `users.tier_expires_at`
  - `orders.order_type/plan_id/tier_target/tier_days`
- API outputs:
  - `GET /api/payment/plans` includes `credit_plans` and `tier_plans`.
  - `GET /api/auth/me` includes `tier_expires_at`.
- Success-path callback script run in API container confirmed:
  - callback returns HTTP 200 with `"success"`
  - order updated to `paid`
  - user tier upgraded and expiry set
  - bonus credit transaction inserted with non-null `balance_after`
  - temporary verification rows cleaned after run.

Known boundary:
- Real external callback signature verification still requires valid live payment-channel credentials and provider callback requests.

## 2026-05-15 Director Final FFmpeg Runtime Install

Status: runtime installed and service-level verified.

Runtime installation:
- `ffmpeg` is installed in `saas--worker-admin-1`.
- `ffmpeg` is installed in `saas--api-1` to cover the legacy synchronous concat endpoint as well.
- Both containers report `ffmpeg version 7.1.4-0+deb13u1`.
- `Dockerfile` already includes `ffmpeg`, so the change is durable once Docker rebuild works again.

Evidence:
- `docker restart saas--worker-admin-1` succeeded after worker FFmpeg install.
- `docker exec saas--worker-admin-1 ffmpeg -version` succeeded.
- `docker exec saas--api-1 ffmpeg -version` succeeded.
- Container service smoke test generated two one-second MP4 clips inside `saas--worker-admin-1` and called `export_final_video()`.
- Smoke output:
  - `clip_count`: 2
  - `duration_sec`: 2.021016
  - `file_size`: 38502 bytes
- `GET /health` returned `ok` after install checks.

Boundary:
- Full Celery export-to-OSS task is still not marked complete because the current containers do not have OSS credentials configured:
  - `oss_access_key`: false
  - `oss_secret_key`: false
- With OSS credentials absent, the task can render locally but would fail at `storage_service.upload_bytes()`.
- Full image rebuild is still blocked by the Docker Desktop gRPC `x-docker-expose-session-sharedkey` non-printable header error, so the current install is a runtime hot fix plus Dockerfile durability for a future successful rebuild.

Environment note:
- The workspace `.git` file points to `C:/tmp/saas-git`, which is unavailable in this session. `git status` cannot be trusted until that gitdir is restored.

## 2026-05-15 Director Final Cut Workbench

Status: deployed and API/service verified.

Product decision:
- The FFmpeg link is now treated as a visible "final cut workbench", not only a background export button.
- Scope is deliberately not a Premiere-style full editor. The first commercial version focuses on the actual short-drama delivery loop:
  - choose produced shots,
  - reorder shots,
  - enable/disable shots,
  - trim start/end,
  - choose simple transitions,
  - edit burn-in subtitles,
  - set BGM path placeholder,
  - export the final video.

Changes:
- Added Alembic revision `014_add_final_edit_plans.py`.
- Added `final_edit_plans` table for persistent per-project/user edit plans.
- Added `app/services/final_edit.py` for default-plan generation, plan normalization, shot merge, and export-payload generation.
- Added `GET /api/projects/{project_id}/final-edit-plan`.
- Added `PUT /api/projects/{project_id}/final-edit-plan`.
- Updated `POST /api/director/export-final` to accept `edit_plan` and pass normalized export data to Celery.
- Updated `director_export_final_task` to use edit-plan clip order, enabled clips, trim values, transition list, subtitles, and BGM path.
- Updated `export_final_video()` to accept source dicts with `trim_start` and `trim_end`.
- Added front-end route:
  - `/director/final-cut`
  - `/director/final-cut/:projectId`
- Added `frontend/src/pages/director/final-cut.vue`.
- Added final-cut entry from `/director/produce`.
- Added front-end API helpers for loading/saving final edit plans.

Evidence:
- Local py_compile passed for:
  - `app/services/final_edit.py`
  - `app/services/video_edit.py`
  - `app/routes/workbench.py`
  - `app/routes/director.py`
  - `app/tasks/director_tasks.py`
  - `alembic/versions/014_add_final_edit_plans.py`
- Frontend production build passed with `npm run build`.
- Hot-copied backend files and frontend dist into running containers.
- Container py_compile passed in API and worker.
- `alembic upgrade head` ran successfully: `013 -> 014`.
- `alembic current` returned `014 (head)`.
- Postgres `\d final_edit_plans` confirmed table, unique `(project_id, user_id)`, indexes, and FKs to `projects`/`users`.
- `GET /health` returned `ok`.
- API smoke:
  - Registered a temporary user.
  - Created a temporary project.
  - Inserted one produced `shot_rows.selected_video`.
  - `GET /api/projects/{project_id}/final-edit-plan` returned source `default` and 1 clip.
  - `PUT /api/projects/{project_id}/final-edit-plan` saved `trim_start=0.5` and `burn_subtitles=true`.
  - Temporary user/project/credit/test rows were cleaned.
- Worker FFmpeg trim smoke:
  - Generated two 2-second clips in `saas--worker-admin-1`.
  - Called `export_final_video()` with per-clip trim start/end.
  - Output:
    - `clip_count`: 2
    - `duration_sec`: 2.52
    - `file_size`: 46802 bytes

Boundary:
- Full final export to public `final_url` still requires OSS credentials in the running containers.
- BGM path is wired through the plan, but the first UI exposes a path/URL field only. A proper customer-friendly BGM asset picker/upload flow should be added next.
- Cover title is captured in UI settings, but automatic cover rendering/export is not yet wired to a persisted cover asset.

## 2026-05-15 Final Cut BGM Asset Chain

Status: deployed and verified.

Changes:
- Final cut workbench now supports BGM as a first-class project asset:
  - upload audio file,
  - import audio from HTTP(S) URL,
  - list/select project audio assets,
  - preview selected audio,
  - set BGM volume from `0.00` to `1.00`,
  - save selected BGM and volume into `final_edit_plans.plan_json.settings`.
- Added backend endpoint:
  - `POST /api/projects/{project_id}/assets/import-url`
- Hardened `assets.metadata_json` writes by explicitly serializing JSON and casting to JSONB in raw SQL insert paths.
- `export_final_video()` now accepts `bgm_volume`.
- FFmpeg BGM handling now supports local project asset URLs such as `/assets/{project_id}/assets/file.wav`.
- `director_export_final_task` passes `bgm_volume` from edit-plan export data into FFmpeg.

Evidence:
- Local py_compile passed for:
  - `app/routes/workbench.py`
  - `app/services/final_edit.py`
  - `app/services/video_edit.py`
  - `app/tasks/director_tasks.py`
- Frontend `npm run build` passed.
- Hot-copied API, worker, and frontend dist into running containers.
- Container py_compile passed in API and worker.
- API and worker containers restarted; `GET /health` returned `ok`.
- Worker FFmpeg BGM smoke:
  - generated two clips and one BGM wav inside `saas--worker-admin-1`,
  - exported with `bgm_volume=0.25`,
  - output had audio stream,
  - `clip_count`: 2,
  - `duration_sec`: 2.48,
  - `file_size`: 54975 bytes.
- URL import smoke:
  - generated a wav test file,
  - served it through local nginx as `http://nginx/bgm-url-test.wav`,
  - imported through `POST /assets/import-url`,
  - returned `asset_type=audio`,
  - returned `/assets/...wav`,
  - `listAssets(asset_type=audio)` returned 1 item,
  - imported size was 88278 bytes,
  - `upload_mode=url_import`.
- Upload smoke:
  - uploaded a generated wav through multipart `POST /assets/upload`,
  - returned `asset_type=audio`,
  - returned `/assets/...wav`,
  - `listAssets(asset_type=audio)` returned 1 item,
  - uploaded size was 88278 bytes,
  - `upload_mode=stream`.
- Temporary verification users/projects/credit rows and local test files were cleaned.

Boundary:
- External music APIs are not integrated yet. The current production-safe path is user-owned upload and direct audio URL import.
- URL import intentionally accepts only direct audio files, not arbitrary music web pages.
- Commercial music provider integration should be added only after choosing a licensing model/API vendor.

## 2026-05-16 Final Export Local Fallback

Status: deployed and verified.

Problem found:
- User exported final video from `/director/final-cut`, but the UI showed "导出失败".
- Runtime DB evidence:
  - recent `director_export_final` tasks for user 4 failed at progress `88`.
  - error: `OSS credentials not configured (OSS_ACCESS_KEY / OSS_SECRET_KEY)`.
- The old export used a temporary FFmpeg output directory. When upload failed, the temporary final MP4 was cleaned up, so there was no durable file for the user to open.
- Container inspection confirmed `api`, `worker-admin`, and `nginx` have no shared mounts, so writing a local file in the worker container would not be enough for the browser to access it.

Fix:
- Added Alembic revision `015_add_final_video_blobs.py`.
- Added `final_video_blobs` table as a no-OSS local fallback:
  - `task_id UUID PRIMARY KEY`
  - `project_id`
  - `user_id`
  - `content_type`
  - `file_size`
  - `data BYTEA`
- Added authenticated API endpoint:
  - `GET /api/director/final-video/{task_id}`
- Updated `director_export_final_task`:
  - tries OSS upload first,
  - if OSS upload fails, stores final MP4 bytes in `final_video_blobs`,
  - returns `final_url=/api/director/final-video/{task_id}`,
  - returns `storage_mode=db_blob`.

Evidence:
- Local py_compile passed for:
  - `app/routes/director.py`
  - `app/tasks/director_tasks.py`
  - `alembic/versions/015_add_final_video_blobs.py`
- Container py_compile passed for API and worker files.
- `alembic upgrade head` succeeded after correcting `task_id` to UUID.
- Runtime DB is `015 (head)`.
- `\d final_video_blobs` confirmed table, indexes, and FKs.
- API and worker restarted.
- `GET /health` returned `ok`.
- Full no-OSS fallback smoke:
  - created a temporary user/project,
  - generated two local worker MP4 clips,
  - inserted temporary `shot_rows.selected_video`,
  - called `POST /api/director/export-final`,
  - task finished `done`,
  - result:
    - `final_url`: `/api/director/final-video/adcdc7106a64429685026281c230be05`
    - `storage_mode`: `db_blob`
    - `file_size`: 37768
  - authenticated GET of final URL returned:
    - HTTP 200
    - `Content-Type: video/mp4`
    - length `37768`
- Temporary verification tasks/projects/users/credit rows and worker files were cleaned.

Boundary:
- Previous failed exports cannot be recovered because their temporary FFmpeg files were already deleted.
- User should re-click "导出成片"; with the fallback deployed, no-OSS exports now return an authenticated `/api/director/final-video/{task_id}` link.
- DB blob storage is a development/local fallback. Production should still configure OSS/CDN for large videos and public delivery.
## 2026-05-16 Final Cut Recipe Library

Status: deployed and verified.

Context:
- User is collecting creator editing tutorials and wants them preserved as detailed step recipes, not vague prompts.
- Product direction: AI should select and fill structured editing recipes, then FFmpeg executes concrete operations where feasible.

Implemented:
- Added structured final-cut recipe library under `data/final_cut_recipes/`.
- Added `editing_thinking_rules.json` with planning rules:
  - `classical_shot_continuity`
  - `travel_vlog_segmented_story`
  - `music_bridge_three_methods`
  - `closeup_group_to_wide_tension`
  - `cinematic_pacing_slow_fast_slow`
- Added `effect_recipes.json` with effect recipes:
  - `dehaze_clarity_boost`
  - `year_countdown_reveal`
  - `music_player_overlay`
  - `freeze_cutout_emphasis`
- Added service `app/services/final_cut_recipes.py`.
- Added authenticated APIs:
  - `GET /api/director/final-cut-recipes`
  - `GET /api/director/final-cut-recipes/{recipe_id}`
- Updated `/director/final-cut` to show a visible "剪辑思维库" panel grouped by category, with summary, steps/rules, commercial value, AI dependencies, and FFmpeg feasibility.

Important design boundary:
- Planning rules and executable effects are explicitly separated.
- `dehaze_clarity_boost` is labeled as FFmpeg approximation, not AI upscaling.
- `freeze_cutout_emphasis` is labeled as requiring AI segmentation before reliable execution.
- Repeated "大片感/高级感节奏" content was merged into one canonical pacing recipe instead of duplicating entries.

Evidence:
- Local `python -m py_compile app/services/final_cut_recipes.py app/routes/director.py` passed.
- Local `python -m json.tool` passed for both recipe JSON files.
- `cd frontend; npm run build` passed.
- Hot-copied backend service, route, recipe data, and frontend dist into running containers.
- API container py_compile passed.
- API container recipe load returned 9 recipe IDs.
- `GET /health` returned `{"status":"ok"}`.
## 2026-05-17 Final Cut AI Planning

Status: deployed and verified.

Decision:
- Followed the shared bottom-layer model access design.
- Doubao/key_pool remains shared.
- Final cut AI is separated as its own business capability, credit operation, route, and prompt contract.

Implemented:
- Added credit operation fallback price:
  - `final_cut_ai_plan`: 6 credits
- Added `app/services/final_cut_ai.py`.
  - Calls Doubao through existing `generate_text`.
  - Requires JSON-only output.
  - Allows AI to adjust only `enabled`, `order`, `trim_start`, `trim_end`, `transition`, `subtitle`, and `settings`.
  - Preserves system-owned `video_url`, `duration`, and `prompt`.
  - Rejects plans that do not return a valid clips list.
- Added API:
  - `POST /api/director/final-cut-plan/ai`
- API behavior:
  - checks project ownership,
  - loads existing saved/default final edit plan,
  - checks concurrency and `llm_chat` rate limit,
  - applies platform/user cost guard,
  - reserves `final_cut_ai_plan`,
  - calls Doubao via existing key pool in a worker thread,
  - saves generated plan to `final_edit_plans`,
  - charges on success and refunds on failure.
- Updated `/director/final-cut` UI:
  - added optional AI instruction textarea,
  - added `AI 应用到剪辑方案` button in the recipe panel,
  - displays AI explanations/warnings after generation.

Evidence:
- Local py_compile passed for:
  - `app/services/final_cut_ai.py`
  - `app/services/credits.py`
  - `app/routes/director.py`
- Frontend `npm run build` passed.
- Hot-copied backend files and frontend dist into running containers.
- API container py_compile passed.
- API container confirmed `DEFAULT_PRICING['final_cut_ai_plan'] == 6`.
- API container route registration returned `True` for `/api/director/final-cut-plan/ai`.
- API container merge smoke returned reordered first shot index `2`, proving AI clip ordering can be merged without losing base plan fields.
- `GET /health` returned `{"status":"ok"}`.

Test boundary:
- Local `pytest tests/unit/test_credit_pricing.py -q` could not run because host Python 3.14 environment is missing `asyncpg`.
- API container also does not include pytest, so container unit test execution was unavailable.
## 2026-05-18 Final Cut Local Rule Apply

Status: deployed and verified.

Context:
- User asked not to rush to wrap up and to continue building real final-cut functionality.
- Previous live AI smoke showed correct planning direction but high token use: 3 demo clips consumed 3071 tokens, including 1921 completion tokens.

Implemented:
- Tightened `app/services/final_cut_ai.py`:
  - reduced `max_tokens` from 2200 to 900,
  - capped explanation/warnings in prompt contract,
  - banned absolute overclaiming such as "perfectly covers".
- Added deterministic no-token rule application service:
  - `app/services/final_cut_rule_apply.py`
- Supported local rules:
  - `cinematic_pacing_slow_fast_slow`
  - `closeup_group_to_wide_tension`
  - `travel_vlog_segmented_story`
- Added API:
  - `POST /api/director/final-cut-plan/apply-rule`
- Updated `/director/final-cut` UI:
  - added `本地应用规则` button,
  - kept `AI 应用到剪辑方案` as enhanced option,
  - both write back to the editable final edit plan before export.

Evidence:
- Local py_compile passed for:
  - `app/services/final_cut_rule_apply.py`
  - `app/services/final_cut_ai.py`
  - `app/routes/director.py`
- Frontend `npm run build` passed.
- Hot-copied backend service, route, and frontend dist into containers.
- API container py_compile passed.
- API restarted.
- `GET /health` returned `{"status":"ok"}`.
- Runtime route registration confirmed `/api/director/final-cut-plan/apply-rule`.
- Runtime slow-fast-slow smoke:
  - input: wide 8s, closeup market 5s, sunset ending 9s
  - output: applied `True`
  - clip 2 was trimmed by `trim_end=2.0`, making it a 3s middle fast-cut
  - opening/ending kept fade transitions.

Boundary:
- Local rule application uses prompt/subtitle heuristics, not visual model analysis yet.
- It is low-cost and deterministic but less semantically accurate than future frame-level visual diagnosis.

## 2026-05-18 Final Cut Low-Res Preview Sample

Status: deployed and verified.

Implemented:
- `POST /api/director/export-preview` submits a no-token FFmpeg preview export task.
- `director_export_preview_task` is registered on the default/admin Celery worker.
- `export_final_video(..., preview=True)` renders low-res browser-friendly MP4 previews while preserving final edit plan semantics.
- `/director/final-cut` now has `生成预览小样`, separate preview progress, and direct playback in the right-side preview panel.

Evidence:
- Local py_compile passed for changed backend files.
- Frontend `npm run build` passed.
- Runtime `/health` returned ok.
- Unauthenticated `POST /api/director/export-preview` returned HTTP 401, proving the route is mounted.
- Worker log lists `app.tasks.director_tasks.director_export_preview_task`.
- Container FFmpeg smoke produced a valid preview MP4 at `480x852`, with audio stream present.

Boundary:
- Preview is FFmpeg-only over existing generated clips; it does not call Doubao/DeepSeek and records `credits_reserved=0`.
- Advanced creator effects that require segmentation/cutout are still future work.

## 2026-05-18 Produce To Final Cut Bridge

Status: deployed and deeply verified.

Implemented:
- `/director/produce` now has a visible `Final Cut Chain` bridge card.
- The bridge counts produced `selected_video` shots and routes ready projects to `/director/final-cut/:projectId`.
- The header shortcut now says `进入剪辑台`.
- Shot-card edit/done primary actions now route to the final-cut workbench instead of directly exporting, making the commercial path: production -> editing workbench -> preview -> final export.
- Added `scripts/verify_final_cut_preview_chain.py` for repeatable deep validation.

Evidence:
- Frontend `npm run build` passed.
- Frontend dist was published to `saas--nginx-1` and nginx restarted.
- Runtime checks:
  - `/director/produce` returned 200.
  - `/director/final-cut/test_project` returned 200.
  - `/health` returned ok.
  - `/api/director/export-preview` returned 401 when unauthenticated.
- Deep chain script passed:
  - temp user/project/shot rows created,
  - two real worker MP4 clips inserted as `selected_video`,
  - final edit plan loaded and saved,
  - preview task submitted and completed,
  - MP4 fetched from `/api/director/final-video/{task_id}`,
  - preview bytes = 25312,
  - temporary rows and videos cleaned.

Boundary:
- Direct export remains as secondary fallback, but the product-guided path is now through the editing software.
- No new creator effect algorithm was added in this pass.

## 2026-05-18 Final Cut AI Planning Timeout Fix

Status: deployed and verified at container level.

Current state:
- The final-cut AI planning button no longer waits synchronously for Doubao in the browser request.
- `/api/director/final-cut-plan/ai` validates project/recipe/clip availability, then dispatches `director_final_cut_ai_task`.
- The text worker loads the current final edit plan, calls Doubao through the shared key pool, saves the normalized final edit plan, then publishes task completion.
- The final-cut page polls the returned task id and applies the completed plan to the editor.

Commercial guardrails:
- Default deterministic rule application is still available and consumes no Doubao tokens.
- AI planning remains credit guarded and rate limited.
- Failed AI planning refunds the reserved credits through the existing task failure path.

Evidence:
- Local backend py_compile passed.
- Frontend build passed.
- Project brain unit tests passed.
- Container backend py_compile passed.
- Text worker can import `director_final_cut_ai_task`.
- `/health` returned ok.

Operational note:
- Docker image rebuild is currently blocked by inaccessible pytest temporary directories in the Windows build context. Hot deployment was used instead:
  - backend files copied into api and worker-text containers,
  - frontend `dist` copied into nginx,
  - api and worker-text restarted.

## 2026-05-19 Project Brain Production Ledger

Status: deployed and verified at container level.

Current state:
- The project brain now returns `context.production_ledger`.
- The ledger estimates long-form progress from existing workspace and `shot_rows` data:
  - target total seconds,
  - planned shot count and duration,
  - generated video count and duration,
  - remaining seconds,
  - current minute range,
  - previous/current/next scene,
  - per-scene image/video completion,
  - reusable asset anchors across character, scene, costume, prop, and style refs.
- `/director/produce` shows a visible `Production Ledger / 进度账本` panel inside the production flow panel.

Boundary:
- This is currently computed from current project documents and shot rows; it is not yet a dedicated persisted ledger table.
- Scene detection relies on prompt text like `第1集第2场`; future script planning should write explicit episode/scene metadata to avoid regex inference.
- Target duration is inferred from project/episode/scene docs or minute mentions. If no target is present, it falls back to planned shot duration.

Evidence:
- Local py_compile passed.
- Project brain unit tests passed: 12 tests.
- Frontend build passed.
- `project_brain.py` hot-copied to api container and api restarted.
- Frontend dist hot-copied to nginx.
- Container py_compile passed.
- `/health` returned ok.
- Nginx bundle contains `Production Ledger`.

## 2026-05-19 Creator Rules Prompt Layers

Status: deployed and verified at container level.

Current state:
- User-provided creator techniques are now mapped by execution layer instead of being dumped into one large prompt:
  - visual authenticity and anti-AI-plastic controls -> Seedream + Seedance prompt boundary,
  - human micro-expression and body linkage -> Seedream + Seedance prompt boundary,
  - camera motion formula -> Seedance video prompt boundary only,
  - voice delivery formula -> TTS payload compiler before Ark TTS.
- `app/services/visual_quality_rules.py` now provides:
  - `apply_visual_quality_controls`,
  - `apply_video_motion_controls`,
  - `build_human_performance_controls`.
- `app/services/ref_resolver.py` applies:
  - visual/performance controls to image payloads,
  - visual/performance + video motion controls to video payloads.
- `app/services/voice_delivery_rules.py` compiles TTS text and provider controls:
  - punctuation pauses,
  - tense/warm/warning delivery profiles,
  - speed/volume defaults while preserving explicit user overrides.

Boundary:
- This is deterministic and does not add extra Doubao calls.
- TTS provider support is limited to currently wired executable fields (`input`, `speed`, `volume`, `voice`); richer emotion tags can be added later only if the provider endpoint supports them reliably.
- Ref-resolver integration test is skipped locally when `asyncpg` is missing, because importing `app.db` requires the driver.

Evidence:
- Local py_compile passed for changed backend and test files.
- Unit tests passed: 23 passed, 1 skipped.
- Hot-published to api, image worker, video worker, and text worker.
- Restarted touched containers.
- Container py_compile passed.
- Container TTS smoke check returned `delivery_profile=tense_breathing_pauses`, `speed=0.86`, `volume=0.95`, and natural pause text `下一个，不是就到我了`.
- `/health` returned ok.

## 2026-05-19 Content Humanizer Write Script Layer

Status: deployed and verified at container level.

Current state:
- `app/services/content_humanizer.py` provides deterministic generated-copy naturalization.
- `/api/director/write-script` now applies this layer by default after Doubao returns script text.
- Request body controls:
  - `humanize_copy`: default `true`; set `false` to return raw LLM copy,
  - `humanize_strength`: `light | medium | deep` or Chinese aliases `轻度 | 中度 | 深度`,
  - `platform`: reserved metadata field for future platform-specific style policies.
- Response now includes `humanize` metadata:
  - enabled,
  - strength,
  - changed_count,
  - changed_rules,
  - note.

Boundary:
- This is an originality/readability improvement layer, not a guarantee to bypass any platform review or detection.
- It does not make another Doubao call, so it does not add text-token cost.
- Current rules are deterministic and conservative; deeper platform-specific rewriting can be added later behind the same service.

Evidence:
- Local py_compile passed.
- Unit/regression tests passed: 27 tests.
- Hot-published to `saas--api-1`.
- API container restarted.
- Container py_compile passed.
- Container smoke check transformed AI cliches into more natural copy and returned `changed_count=4`.
- `/health` returned ok.

## 2026-05-19 Project Brain Director Ledgers

Status: deployed and verified at container level.

Current state:
- The project brain is no longer only a phase/status checker. It now returns four general-purpose director ledgers:
  - `context.creative_technique_ledger`
  - `context.story_continuity_ledger`
  - `context.cost_risk_ledger`
  - `context.final_quality_ledger`
- `app/services/project_brain_ledgers.py` owns the deterministic ledger calculations.
- `app/services/project_brain.py` merges ledger summary fields into `signals`, adds ledger-driven risks/missing items, and returns the ledgers under `context`.
- `/director/produce` now shows four compact panels for:
  - 创作技巧账本,
  - 剧情连续账本,
  - 成本风控账本,
  - 成片验收账本.

Design principle:
- Base ledgers are generic and reusable across projects and genres.
- They only depend on common fields: project docs, scene docs, shot rows, matched libraries, refs, reviews, selected images/videos, visual budget, final edit plan.
- Genre-specific strategies should be layered later as strategy inputs/plugins, not hard-coded into the base ledgers.

Boundary:
- The ledgers are computed from current persisted state; they are not yet persisted historical tables.
- Cost is operation-level risk estimation, not a provider invoice calculation.
- Final quality ledger is deterministic and checks readiness gaps; it does not replace human/vision review.

Evidence:
- Local py_compile passed for project brain and ledger files.
- Unit tests passed: 16 tests.
- Frontend build passed.
- Hot-published backend to `saas--api-1` and frontend dist to `saas--nginx-1`.
- API/nginx restarted.
- Container py_compile passed.
- Container smoke check returned all four ledger keys.
- `/health` returned ok.
- `/director/produce` returned 200.

Deep check note:
- A synthetic multi-scene project revealed two ledger alignment issues after initial deployment:
  - production ledger scene parser only understood Chinese scene markers,
  - creative technique signal counts did not match top-level ledger counts.
- Fixed scene parser to support explicit `episode/scene`, `EP1SC2`, and `Episode 1 Scene 2`.
- Fixed creative technique signals and cost risk `watch` propagation.
- Re-ran tests and synthetic deep check successfully.

## 2026-05-19 Project Brain Execution Trace UI

Status: deployed and verified at frontend/container level.

Current state:
- `/director/produce` now includes a visible `Brain Execution Trace` panel immediately after the production workflow.
- The panel makes the automatic brain process inspectable:
  - reads project workspace readiness and version,
  - shows brain phase, summary, and analyzed time,
  - shows progress ledger current scene, generated duration, remaining duration, and shot/image/video counts,
  - surfaces creative technique, story continuity, cost risk, and final quality checks,
  - shows the next executable brain instruction,
  - shows the latest continue/execution feedback message after the user clicks `继续推进`.

Design principle:
- This is a generic observability layer for the project brain, not a project-specific shortcut.
- It derives from existing workspace, brain, ledgers, shots, and system events, so it does not add provider calls or token cost.
- Backend `execution_trace` persistence can be added later, but the web UI now exposes the current automatic process without waiting for a new API schema.

Evidence:
- `cd frontend; npm run build` passed.
- Hot-published frontend `dist` to `saas--nginx-1`.
- Restarted `saas--nginx-1`.
- `/health` returned 200.
- `/director/produce` returned 200.
- Source and built assets contain `大脑执行轨迹` / `Brain Execution Trace`.

Known note:
- `git diff` is currently blocked by the existing repository path issue (`fatal: not a git repository: C:/tmp/saas-git`); no git configuration was changed.

## 2026-05-19 Project Brain Verbose Debug Flow

Status: deployed and verified at frontend/container level.

Current state:
- `Brain Execution Trace` now includes a default-expanded `Verbose Debug Flow / 详细流程账本`.
- Each brain step shows:
  - input evidence,
  - decision logic,
  - output/API call,
  - stop condition.
- The flow covers:
  - reading workspace context,
  - merging memory and ledgers,
  - mapping creative techniques,
  - checking story continuity,
  - cost/risk guardrails,
  - final delivery checks,
  - issuing the next instruction,
  - feedback/writeback after execution.
- Raw workspace file evidence is available under `展开原始读取清单`.

Evidence:
- `cd frontend; npm run build` passed.
- Hot-published frontend `dist` to `saas--nginx-1`.
- Restarted `saas--nginx-1`.
- `/health` returned 200.
- `/director/produce` returned 200.
- Source and built assets contain `详细流程账本`, `Verbose Debug Flow`, `输入依据`, and `停止条件`.

## 2026-05-19 Context Read Coverage Audit

Status: deployed and verified.

Current state:
- Step 1 `读取上下文` is no longer only a file existence check.
- `build_project_brain()` now returns enriched `read_files` and `context.context_coverage`.
- Each context source now records:
  - `path`,
  - `role`,
  - `label`,
  - `exists`,
  - `size`,
  - `chars`,
  - `parsed`,
  - `parse_status`,
  - `item_count`,
  - `consumed`,
  - `coverage`,
  - `used_by`,
  - `impact_if_missing`.
- `/director/produce` uses the backend coverage evidence in `BrainExecutionTrace`.
- Raw evidence shows whether each source was merely present or actually consumed by the brain.

Design principle:
- A context source is not considered fully covered just because it exists.
- It is only `covered` when it exists, parses, and participates in decision signals.
- Missing or unconsumed sources are visible so they can be treated as fake/partial coverage during debugging.

Evidence:
- `python -m py_compile app/services/project_brain.py tests/unit/test_project_brain.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 16 tests.
- `cd frontend; npm run build` passed.
- Hot-published backend `project_brain.py` to `saas--api-1`.
- Hot-published frontend `dist` to `saas--nginx-1`.
- Restarted api/nginx containers.
- Container py_compile passed for `/app/app/services/project_brain.py`.
- `/health` returned 200.
- `/director/produce` returned 200.

## 2026-05-19 Ledger Merge Audit

Status: deployed and verified.

Current state:
- Step 2 `合并记忆与账本` now has backend evidence, not only UI display.
- `build_project_brain()` returns `context.ledger_merge_audit`.
- The audit records whether each component is present and whether it enters decisions:
  - `production_ledger`
  - `character_lock`
  - `scene_lock`
  - `asset_reuse`
  - `creative_ledger`
  - `quality_ledger`
  - `decision_memory`
  - `failure_memory`
  - `constraint_memory`
  - `cost_ledger`
- Each audit row records:
  - `component`
  - `label`
  - `present`
  - `evidence`
  - `signals_used`
  - `consumed_by`
  - `decision_effect`
  - `coverage`
- `/director/produce` now shows `展开账本合并审计` under the verbose brain flow.

Truth table:
- `covered`: present and consumed by phase/next_action/risks/missing/final_edit decisions.
- `partial`: present but currently only used for audit/signals/display.
- `missing`: not present.

Important finding:
- Progress ledger, character lock, scene lock, asset reuse, cost ledger, and final quality ledger can affect decisions.
- `memory/decisions.md`, `memory/failures.md`, and `memory/constraints.md` are currently visible and counted, but mostly partial because they do not deeply drive next_action yet. They should be tightened later into retry guardrails, cost/style constraints, and duplicate-work prevention.

Evidence:
- `python -m py_compile app/services/project_brain.py tests/unit/test_project_brain.py` passed.
- `python -m pytest tests/unit/test_project_brain.py tests/unit/test_project_brain_ledgers.py -q` passed: 16 tests.
- `cd frontend; npm run build` passed.
- Hot-published backend/frontend to api/nginx containers.
- Restarted api/nginx containers.
- Container py_compile passed for `/app/app/services/project_brain.py`.
- `/health` returned 200.
- `/director/produce` returned 200.
