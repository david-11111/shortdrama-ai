# Phase 8 各终端启动指令

> 每段可直接复制到对应终端作为开场指令。终端读完自己的 `.claude/team/<代号>.md` + 本页分派内容即可开工。
> orchestrator 不派发具体写法，只给"做什么 / 验收什么 / 不能碰什么"。

## 所有终端通用强制项（粘贴前阅读）

每段启动指令默认包含以下强制前置步骤，终端开工前必须完成：

```
第 0 步（所有终端通用，不可跳过）：
读完以下三份文件，确认已理解后再开工：
1. CLAUDE.md — 全局规则
2. .claude/CODE_STANDARDS.md — 代码规范（最重要）
3. .claude/team/<你的代号>.md — 权限边界

核心心法：能用 5 行解决的绝不写 10 行，能复用现有代码绝不新写。
修 bug 只改必要的行，不借机重构、重命名、加注释。
越权、引入新依赖、超范围修改 — 一律在过检时打回。
```

---

## 给 api-biz 终端

```
你是 api-biz 终端。先读 CLAUDE.md 和 .claude/team/api-biz.md 明确权限边界。
Phase 8 分配给你 10 个 P0 任务（详见 .claude/orchestrator/state.md 的 api-biz 表）。

立刻启动（按此顺序）：
1. P8-BIZ-4、BIZ-5、BIZ-6、BIZ-8、BIZ-9、BIZ-10 互相独立，可并行
2. P8-BIZ-1（重写 _dispatch_director_task 派发表）+ P8-BIZ-2（加排队三件套）
   — 等 devops 的 P8-OPS-1 迁移合入后再做 BIZ-2 的 check_rate_limit 部分
3. P8-BIZ-3（TTS 加排队）独立可做
4. P8-BIZ-7（批量端点接入 workbench_orchestrator）等 worker 的 P8-WRK-1 完成

核心约束：
- 绝对不改 app/tasks/、app/services/（除中间件）、alembic/、frontend/
- _dispatch_director_task 的派发映射必须按 state.md 里列出的 5 条精确对应
- 所有新加的排队检查顺序：check_concurrent → check_rate → reserve_credits → send_task
- 预扣失败一律回滚已扣部分，不允许财务泄露

分支：api/phase8-dispatch-fix、api/phase8-rate-limit-director 等按任务粒度拆
完成一项通知 orchestrator 过检，qa 加回归用例后才算 closed。
```

---

## 给 worker 终端

```
你是 worker 终端。先读 CLAUDE.md 和 .claude/team/worker.md。
Phase 8 分配给你 6 个任务（详见 .claude/orchestrator/state.md 的 worker 表）。

立刻启动：
1. P8-WRK-1（最优先）— 修 director_tasks.py 的 _save_shot_rows / _load_shot_rows
   使用 SQLAlchemy 参数化写 JSONB，不依赖 PG 方言特性
   完成后 api-biz 才能做 P8-BIZ-7
2. P8-WRK-6（director 任务加 charge/refund）— 对齐 image/video_tasks 的模式
3. P8-WRK-2/3/4/5（异步化改造）— 系统性优化，可在一个分支集中做

核心约束：
- 绝对不改 app/routes/、app/middleware/、app/main.py、alembic/
- director_tasks.py 里的 SQL 兼容修复不要顺手改其他 task 文件
- 异步化改造小心：确认当前调用方是同步还是异步，别破坏接口契约
- key_pool 的 cooldown 语义：Redis TTL 就是过期时间，不需要再存时间戳值

分支：worker/phase8-sql-compat、worker/phase8-async-fix 等
```

---

## 给 api-auth 终端

```
你是 api-auth 终端。先读 CLAUDE.md 和 .claude/team/api-auth.md。
Phase 8 分配给你 4 个任务（详见 .claude/orchestrator/state.md 的 api-auth 表）。

立刻启动：
1. P8-AUTH-4（修 /auth/me user_id 字段混淆）— 独立，最快
2. P8-AUTH-1（密码强度校验）— 独立
3. P8-AUTH-3（登录失败日志 + 锁定）— 独立
4. P8-AUTH-2（接入 Token 黑名单）— 等 security 终端的 P8-SEC-4 交付 app.security.token_blacklist 后再做

核心约束：
- 绝对不改业务路由（app/routes/ 除 auth.py/users.py 外）
- Token 黑名单服务由 security 终端写，你只是在 middleware/auth.py 里调用
- 登录失败锁定用 Redis 计数器，不要在用户表加字段（如需字段找 orchestrator）

分支：auth/phase8-me-fix、auth/phase8-login-audit 等
```

---

## 给 fe-core 终端

```
你是 fe-core 终端。先读 CLAUDE.md 和 .claude/team/fe-core.md。
Phase 8 分配给你 5 个任务（详见 .claude/orchestrator/state.md 的 fe-core 表）。

立刻启动：
1. P8-FEC-2（刷 Token 失败递归保护）— 优先，防死循环
2. P8-FEC-3（请求去重 composable）— 独立
3. P8-FEC-1（刷 Token 后重连 WebSocket）
4. P8-FEC-4（全局 toast 错误处理器）
5. P8-FEC-5（Token 存储方案评估）— 产出调研文档给 orchestrator，不实现

核心约束：
- 绝对不改 frontend/src/pages/ 下的业务页面
- 请求去重 composable 要提供给 fe-pages 使用，不能在 pages 里各自实现
- WebSocket 重连逻辑在 composables/useWebSocket.ts 里统一做
- 不要改 package.json 加新依赖，除非 orchestrator 批准

分支：fe-core/phase8-client-refresh、fe-core/phase8-dedupe 等
```

---

## 给 fe-pages 终端

```
你是 fe-pages 终端。先读 CLAUDE.md 和 .claude/team/fe-pages.md。
Phase 8 分配给你 6 个任务（详见 .claude/orchestrator/state.md 的 fe-pages 表）。

立刻启动（所有任务都依赖 fe-core 的 composable 就位）：
1. P8-FEP-3（全局确认弹窗）— 用 fe-core 提供的通用组件
2. P8-FEP-5（ShotTable URL 白名单）— 独立，可先做
3. P8-FEP-4（微信二维码替代 alert）— 独立
4. P8-FEP-1（资产上传分片/流式）
5. P8-FEP-2（批量生成积分预检）— 需要调用 credits API
6. P8-FEP-6（任务列表 WS 订阅管理）

核心约束：
- 绝对不改 frontend/src/api/、frontend/src/stores/、frontend/src/composables/
- 不要在 page 里封装 HTTP 逻辑，调用 fe-core 提供的 composable
- 二维码渲染用 qrcode.vue 或类似库，如需新依赖先报 orchestrator

分支：fe/phase8-confirm-dialog、fe/phase8-qrcode 等
```

---

## 给 devops 终端

```
第 0 步（不可跳过）：
读完 CLAUDE.md、.claude/CODE_STANDARDS.md、.claude/team/devops.md。
核心心法：能用 5 行绝不写 10 行；只改必要的行；不引新依赖；不越权。

───────────────────────────────────────────────

你是 devops 终端。分支：ops/phase8-migration-chain-fix

## 背景
alembic/versions/ 有两个 006 撞车：
- 006_add_rate_limit_resources.py  （down_revision=005_add_workbench_tables）
- 006_add_security_tables.py       （security 终端起草，down_revision=005_add_workbench_tables）
- 007_add_constraints.py           （down_revision=006_add_rate_limit_resources）
`alembic upgrade head` 当前会报 "Multiple head revisions"。

## 任务（P8-OPS-1 + 迁移链重排 + OPS-2/3/4/5 准备）
1. 把 `006_add_security_tables.py` 重命名为 `008_add_security_tables.py`；
   文件内：revision 改为 "008_add_security_tables"，down_revision 改为 "007_add_constraints"。
2. 保留 `006_add_rate_limit_resources.py` 原状，确认其 revision 和 down_revision 正确。
3. 确认 `007_add_constraints.py` 的 down_revision = "006_add_rate_limit_resources"（如不是，修）。
4. 打开 `006_add_rate_limit_resources.py`，确认已覆盖三档 tier × 5 资源：
   tts_gen / director_script / director_produce / director_ref_images / llm_chat
   共 15 行 INSERT，带 ON CONFLICT DO NOTHING。若缺，补齐。
5. 本地起 postgres（docker-compose up -d postgres），跑两轮：
   - `alembic upgrade head`
   - `alembic downgrade -2 && alembic upgrade head`
   两轮无报错。
6. P8-OPS-3（/health 集成协调）：monitoring/health.py 已实现，但 app/main.py 未 include_router。
   在 PR 描述里写明"需要 api-biz 在 app/main.py 加一行：
   `from monitoring.health import router as health_router; app.include_router(health_router)`"
   不要自己动 app/main.py。
7. P8-OPS-4/OPS-5 先列盘点清单到 PR 描述，本波不做，等第一波稳定后第四波推进。

## 禁止
- 不改 app/ 下任何文件（health 集成是 api-biz 的事）
- 不改 security 终端起草的 008 SQL 内容，只改文件名和 revision 常量

## 交付
- alembic/versions/006_add_rate_limit_resources.py（确认/补全）
- alembic/versions/008_add_security_tables.py（从 006_ 重命名并改 down_revision）
- 确认 007 的 down_revision 正确
- 本地 upgrade/downgrade 两轮通过的终端输出贴 PR

## 完成后
写入 `.claude/orchestrator/changelog.md`：
`[P8-OPS-1] migration chain resolved: 005→006_rate_limit→007_constraints→008_security`
```

---

## 给 worker 终端

```
第 0 步（不可跳过）：
读完 CLAUDE.md、.claude/CODE_STANDARDS.md、.claude/team/worker.md。
核心心法：能用 5 行绝不写 10 行；只改必要的行；不引新依赖；不越权。

───────────────────────────────────────────────

你是 worker 终端。分支：worker/phase8-celery-async-hygiene

## 背景修正
orchestrator 原 state.md 里 P8-WRK-1 描述"修 PostgreSQL 专用语法"不成立——
`director_tasks.py` 的 `_save_shot_rows` / `_load_shot_rows` / `_save_asset_pack` 已用
`CAST(:data AS JSONB)` 参数化（见 472 行、512 行）。

真正的问题是：Celery 任务（prefork）内部大量 `asyncio.run(_xxx())`，
每次都新建事件循环，会与 SQLAlchemy async engine 的连接池产生
"Future attached to a different loop"风险；同时 app/services/credits.py 也在同步 wrapper
里 asyncio.run，在 FastAPI 的异步上下文被调用就会炸。

## 任务（调整后的 WRK-1/2/3/4/5）
### 1. P8-WRK-5（_shared.py）先行
阅读 app/tasks/_shared.py，定位所有 asyncio.run / SYNC_REDIS 使用点。
目标：Celery 任务内部一律走"同步 SQL + 同步 Redis"路径。
方案 A（默认，推荐）：为 Celery 任务提供纯同步 `sync_session()` 工厂（sync engine + sync Session）。
方案 B：loop 级缓存（只适合 solo，不适合 prefork）。

如选 A，向 orchestrator 报备：需要 devops 在 app/db.py 增加 SyncSessionLocal。
不要自己改 app/db.py。

### 2. P8-WRK-2（services/credits.py）
app/services/credits.py:40-50 的同步 wrapper 拆分：
- `async def reserve_credits_async(...)` 给 FastAPI 路由用
- `def reserve_credits_sync(...)` 给 Celery 任务用（直接用 sync engine 执行 SQL）
- maybe_charge / maybe_refund 全部走 sync 版本

### 3. P8-WRK-1（director_tasks.py 对齐）
director_script_task / director_prepare_task / director_produce_task /
director_reference_images_task 里所有 `asyncio.run(_xxx(...))` 改为同步版本。
helper 函数改签名：`def _save_shot_rows_sync(session, project_id, shot_rows, user_id)`。

### 4. P8-WRK-3/4（key_pool.py）
- RLock → 如仅同步 Celery 使用，保留 RLock 并在文件顶部 docstring 注明"仅同步上下文"；
  如仍在 FastAPI 异步路径被调用（路由通过 service 层间接调用），改 asyncio.Lock。
  先 grep 所有调用点确认。
- cooldown：Redis TTL 就是过期时间，不要再把 `int(time()) + cooldown_seconds` 写进 value。
  改为 `client.setex(cooldown_key, cooldown_seconds, "1")`。

### 5. P8-WRK-6（director 任务 charge/refund）
参考 image_tasks / video_tasks 现有模式，为 director_script_task /
director_produce_task / director_reference_images_task 加 maybe_charge / maybe_refund
（先确认 api-biz 的 P8-BIZ-2 会在 _dispatch_director_task 里传 transaction_id 过来，
传不过来就不做此项，改在第二波完成）。

## 验收
1. `grep -n "asyncio.run" app/tasks/` 结果只在 celery beat 入口出现，任务 body 内 0 处。
2. 启 worker：`celery -A app.celery_app worker -Q text,default,image -l info`，
   触发一个 director_script_task，shot_rows 成功写入 PostgreSQL，日志无 loop-related 异常。
3. `grep -n "asyncio.run" app/services/credits.py` 结果 0 处。

## 禁止
- 不改 app/routes/**、app/middleware/**、app/main.py
- 不改 app/config.py / app/db.py / app/redis_client.py（如需 SyncSessionLocal 向 orchestrator 申请）
- 不改 alembic/
- 不借机重构其他 task 文件（image_tasks/video_tasks 本波不动）

## 完成后
changelog 追加：`[P8-WRK-1/2/5] celery task async hygiene done; sync path established`。
如 P8-WRK-6 未做（因 BIZ-2 未交付 transaction_id），在 state.md 阻塞项表补一行。
```

---

## 给 security 终端

```
第 0 步（不可跳过）：
读完 CLAUDE.md、.claude/CODE_STANDARDS.md、.claude/team/security.md。
核心心法：能用 5 行绝不写 10 行；只改必要的行；不引新依赖；不越权。

───────────────────────────────────────────────

你是 security 终端（新建立）。分支：sec/phase8-payment-signing-integration

## 背景修正
app/security/signing.py 已有 verify_wechat_v3_signature / parse_wechat_v3_callback /
verify_alipay_rsa2_signature 三个函数骨架（见 29/79/132 行）。
app/security/{audit,encryption,hmac,token_blacklist}.py 也都存在。
不要重写这些函数，本波只做「集成到 payment.py + 加防重放」。

## 任务
### 1. P8-SEC-1（微信 V3 集成）
app/services/payment.py:204 附近找到微信回调处理函数，内部调：
`parse_wechat_v3_callback(headers, body, api_v3_key, platform_cert_pem)`
- api_v3_key 从 app.config.settings.WECHAT_API_V3_KEY 读
- platform_cert_pem 从 WECHAT_PLATFORM_CERT_PATH 指向的文件读
- 如配置未定义，向 orchestrator 报备（PR 描述写明，不自己改 config.py）

验签失败 → 抛 SignatureError（在 signing.py 加这个异常类）→ 路由返回 401。
验签成功 → 走现有订单处理流程，不动。

### 2. P8-SEC-2（支付宝 RSA2 集成）
payment.py:250 同理接入 `verify_alipay_rsa2_signature(params, alipay_public_key_pem)`。
验签失败抛 SignatureError。

### 3. P8-SEC-3（防重放）
- 微信：timestamp 与当前时间差 > 5 分钟 → 拒绝。放在 parse_wechat_v3_callback 内部。
- 支付宝：notify_id 首次见过 Redis set NX 10 分钟；已见过直接返回成功。

### 4. 日志脱敏
signing.py 内不准把 ciphertext / api_v3_key / 私钥内容打 log。

## 不做的事（本波）
- Token 黑名单（P8-SEC-4）— 第二波
- API Key HMAC 迁移（P8-SEC-5）— 第三波
- 审计日志接入（P8-SEC-6）— 第三波
- 008_add_security_tables.py — 本波由 devops 重编号为 008，不要动内容

## 禁止
- 不改 app/routes/ 除 payment.py 外任何文件
- 不改 app/config.py（新增配置项向 orchestrator 申请）
- 不建 alembic 迁移

## 给 qa 的测试向量
在 signing.py 的函数 docstring 补充「如何构造假签名/过期时间戳/无效 notify_id」说明。
qa 据此写 tests/unit/test_signing.py。

## 验收
1. `grep -n "TODO" app/services/payment.py` 在 204、250 附近的 TODO 消失。
2. 伪造错误签名 → 路由返回 401。
3. 时间戳超期 → 拒绝。
4. 日志 grep `api_v3_key`、`alipay_public_key` 无结果。

## 需要 orchestrator 协调
PR 描述列出需要 devops 在 app/config.py 加：
WECHAT_API_V3_KEY / WECHAT_PLATFORM_CERT_PATH / ALIPAY_PUBLIC_KEY_PATH / ALIPAY_APP_ID
以及 .env.example 对应占位。

## 完成后
changelog 追加：`[P8-SEC-1/2/3] payment signing integrated + replay protection; awaiting devops config`
```

---

## 跨终端协作矩阵

| 任务 | 主责 | 协作方 | 协作内容 |
|------|------|-------|---------|
| P8-BIZ-2 | api-biz | devops | 等 P8-OPS-1 迁移合入 |
| P8-BIZ-7 | api-biz | worker | 等 P8-WRK-1 SQL 修复 |
| P8-AUTH-2 | api-auth | security | 等 P8-SEC-4 交付黑名单服务 |
| P8-OPS-3 | devops | api-biz | /health 端点的接入点 |
| P8-SEC-5 | security | devops | API Key 数据迁移 |
| P8-SEC-6 | security | api-biz | admin 路由审计接入 |
| 全部 P0 修复 | 各终端 | qa | 修完必须有回归用例 |

---

## orchestrator 的监督节奏

- 每日上午：各终端用一句话汇报昨天进度 + 今天开工项（更新到 qa_issues.md 的 status 列）
- 每个任务完成：终端通知 orchestrator，orchestrator 做两件事：
  1. 读代码变更，检查是否越界
  2. 通知 qa 写回归用例，用例通过才 close issue
- 阻塞即报：任何终端遇阻立即更新 state.md 的"阻塞项"表格，不要等
- P0 全部 closed 后：orchestrator 做一轮完整集成验证，再开启 P1
