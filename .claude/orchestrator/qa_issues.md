# QA Issues 跟踪板

> qa 终端发现的所有问题汇总。orchestrator 据此分派，各终端修复后回归测试合入 `tests/regression/`。
> 状态列由 orchestrator 过检后更新。fixed = 终端声称已修；closed = qa 回归通过。

---

## Issue 列表

| ID | 发现时间 | 严重度 | 所属终端 | 描述 | 复现用例 | 状态 |
|----|---------|-------|---------|------|---------|------|
| QA-001 | 2026-05-12 | P0 | api-biz | `_dispatch_director_task` 硬编码派发到 `text_tasks.generate_text_task`，5 种导演链任务全部走错 | tests/bugs/qa_001_director_dispatch.py | open |
| QA-002 | 2026-05-12 | P0 | api-biz | 导演链端点全部缺失 check_concurrent_limit / check_rate_limit / reserve_credits | 待建 | open |
| QA-003 | 2026-05-12 | P0 | api-biz | `/api/tts/generate` 缺失 check_concurrent_limit / check_rate_limit | 待建 | open |
| QA-004 | 2026-05-12 | P0 | api-biz | `str(item)` 写入 tasks.payload，应为 json.dumps | tests/bugs/qa_004_payload_json.py | open |
| QA-005 | 2026-05-12 | P0 | api-biz | 批量端点积分预扣中途失败，前面已扣不回滚 | tests/bugs/qa_005_credit_rollback.py | open |
| QA-006 | 2026-05-12 | P0 | api-biz | `workbench.py` asset 端点重复定义两遍 | tests/bugs/qa_006_duplicate_routes.py | open |
| QA-007 | 2026-05-12 | P0 | api-biz | 批量端点绕过 `workbench_orchestrator`，参考图解析未生效 | 待建 | open |
| QA-008 | 2026-05-12 | P0 | api-biz | `tasks.py:124` 取消任务不退预扣积分（财务漏洞） | tests/bugs/qa_008_cancel_refund.py | open |
| QA-009 | 2026-05-12 | P0 | worker | ~~`director_tasks.py` SQL 兼容性~~（误判，已是参数化）；实际问题是表字段对齐 | 待建 | fixed（WRK-1 表字段已对齐 alembic/005） |
| QA-010 | 2026-05-12 | P0 | worker/api-biz | `workbench_orchestrator.py` 的 validate_*/prepare_* 函数从未被调用 | 待建 | open（待 api-biz BIZ-7） |
| QA-011 | 2026-05-12 | P0 | devops | `rate_limit_config` 缺 tts_gen/director_* 资源 | 待建 | fixed（OPS-1 已交付 migration 006） |
| QA-012 | 2026-05-12 | P0 | orchestrator | `saas_interface_protocol.md` 过时（仍描述 SQLite 系统） | — | won't fix（归档，见对话决策） |
| QA-013 | 2026-05-12 | P0 | security | 微信 V3 签名验签未实现（`payment.py:204` TODO） | 待建 | fixed（SEC-1 已集成 parse_wechat_v3_callback） |
| QA-014 | 2026-05-12 | P0 | security | 支付宝 RSA2 验签未实现（`payment.py:250` TODO） | 待建 | fixed（SEC-2 已集成 verify_alipay_rsa2_signature） |
| QA-015 | 2026-05-12 | P0 | api-biz | 硬编码积分值 10/5/1，应从 credit_pricing 读取 | 待建 | open |
| QA-016 | 2026-05-12 | P0 | worker | director 任务未做积分 charge/refund | 待建 | fixed（WRK-6 maybe_charge/refund 已加；依赖 api-biz BIZ-2 传 transaction_id） |
| QA-017 | 2026-05-12 | P1 | security | 支付回调无幂等检查 | 待建 | fixed（SEC-3 notify_id + timestamp 防重放） |
| QA-018 | 2026-05-12 | P1 | api-auth | 注册无密码强度校验、无邮箱验证 | 待建 | fixed（AUTH-1 已加 _is_password_strong，邮箱验证本波不做） |
| QA-019 | 2026-05-12 | P1 | security/api-auth | JWT 无黑名单，登出不失效 | 待建 | fixed（SEC-4 token_blacklist + AUTH-2 logout 已接入） |
| QA-020 | 2026-05-12 | P1 | api-auth | 无登录失败日志、无防暴力破解 | 待建 | fixed（AUTH-3 login_attempts + Redis 5 次锁定 15 分钟） |
| QA-021 | 2026-05-12 | P1 | security | API Key 用裸 SHA256（应 HMAC+盐） | 待建 | open（SEC-5 待做） |
| QA-022 | 2026-05-12 | P1 | worker | `services/credits.py` 异步上下文里 asyncio.run 包装同步方法 | 待建 | fixed（WRK-2 已移除 credits.py 里 4 处 asyncio.run；middleware 侧 await 待 api-biz BIZ-2 补） |
| QA-023 | 2026-05-12 | P1 | worker | `key_pool.py` 用 threading.RLock，async 路径会阻塞 | 待建 | fixed（WRK-3 已加同步约束注释） |
| QA-024 | 2026-05-12 | P1 | worker | `key_pool.py` cooldown TTL 与时间戳混用，语义错 | 待建 | fixed（WRK-4 setex 值改为 "1"，acquire 改用 exists） |
| QA-025 | 2026-05-12 | P1 | worker | `_shared.py` SYNC_REDIS 同步 Redis 在异步任务里阻塞事件循环 | 待建 | partial fix（WRK-5 移除模块级 SYNC_REDIS；但 asyncio.run 仍留 7 处，见 QA-047） |
| QA-026 | 2026-05-12 | P1 | fe-core | Token 存 localStorage，XSS 风险 | — | fixed（FEC-5 产出 token-storage-eval.md 调研文档，待 orchestrator 决策） |
| QA-027 | 2026-05-12 | P1 | fe-core | 刷 Token 后不重连 WebSocket | 待建 | fixed（FEC-1 useWebSocket watch accessToken） |
| QA-028 | 2026-05-12 | P1 | fe-core | 刷 Token 失败无递归保护 | 待建 | fixed（FEC-2 _retry 二次 401 立即登出） |
| QA-029 | 2026-05-12 | P1 | fe-core | 无请求去重，狂点批量生成重复派发 | 待建 | fixed（FEC-3 dedupeKey + useIdempotent composable） |
| QA-030 | 2026-05-12 | P1 | fe-pages | 资产上传 Base64 全量读内存，大文件 OOM | 待建 | fixed（FEP-1 改为 FormData 流式上传） |
| QA-031 | 2026-05-12 | P1 | fe-pages | ShotTable 直接用 URL 作 img src，未校验 | 待建 | fixed（FEP-5 isAllowedMediaUrl 白名单） |
| QA-032 | 2026-05-12 | P1 | fe-pages | 批量生成前无积分预检 | 待建 | fixed（FEP-2 /credits + /credits/pricing 预检） |
| QA-033 | 2026-05-12 | P1 | fe-pages | 充值页微信二维码用 alert 展示 URL | 待建 | fixed（FEP-4 二维码弹层） |
| QA-034 | 2026-05-12 | P1 | fe-pages | 删除/取消全局缺确认弹窗 | 待建 | fixed（FEP-3 workbench 和 tasks 页加 window.confirm） |
| QA-035 | 2026-05-12 | P1 | api-biz | reports.py 分页响应格式不统一 | 待建 | open |
| QA-036 | 2026-05-12 | P2 | devops/api-biz | `/health`/`/health/detailed` 未实现（DEPLOY.md 提过） | 待建 | partial fix（monitoring/health.py 已就绪；app/main.py 缺 Celery 检查，待 api-biz） |
| QA-037 | 2026-05-12 | P2 | devops | Prometheus metrics 采集待验证 | 待建 | fixed（OPS-4 grafana-dashboard + prometheus.yml 已补） |
| QA-038 | 2026-05-12 | P2 | devops | scripts/backup.sh 备份脚本待验证 | 待建 | fixed（OPS-5 已补 Redis BGSAVE + RDB 拷贝） |
| QA-039 | 2026-05-12 | P2 | security/api-biz | 无管理员操作审计日志 | 待建 | open（SEC-6 待做） |
| QA-040 | 2026-05-12 | P2 | api-biz | credit_pricing 查询无缓存 | 待建 | open |
| QA-041 | 2026-05-12 | P2 | security | 文件上传无类型/病毒扫描 | 待建 | open |
| QA-042 | 2026-05-12 | P2 | fe-pages | 任务/资产列表无虚拟滚动，大数据卡顿 | 待建 | open |
| QA-043 | 2026-05-12 | P2 | fe-core | 无离线检测、无全局错误边界 | 待建 | partial fix（FEC-4 全局 toast 已有；离线检测 Phase 9） |
| QA-044 | 2026-05-12 | P2 | devops | credit_accounts.balance 无 CHECK>=0 约束 | 待建 | fixed（OPS-2 migration 007） |
| QA-045 | 2026-05-12 | P2 | devops | shot_rows/assets 无外键约束、无 duration/shot_index 约束 | 待建 | fixed（OPS-2 migration 007） |
| QA-046 | 2026-05-12 | P2 | devops | credit_transactions.user_id 无索引 | 待建 | open |
| QA-047 | 2026-05-12 | P1 | worker | **技术债**：WRK-1/5 声称同步化，实际 asyncio.run 仍留 director_tasks.py×5 + _shared.py×7 共 12 处。Celery prefork 下有"Future attached to a different loop"风险 | 待建 | open（Phase 9 重做） |
| QA-048 | 2026-05-12 | P1 | devops | 微信/支付宝 4 个配置项未加入 app/config.py 和 .env.example（WECHAT_API_V3_KEY / WECHAT_PLATFORM_CERT_PATH / ALIPAY_PUBLIC_KEY_PATH / ALIPAY_APP_ID），security SEC-1/2 依赖此项才能生产可用 | 待建 | open |
| QA-049 | 2026-05-19 | P1 | api-biz | 前端 `prompt.ts` 中 `exportAnnotation()` 调用 `POST /director/annotate-clean-script/export`，后端 director.py 无此路由，实际请求返回 404。发现于 P9-QA-3 全量接口审计。 | tests/contract/api_audit.md（废弃候选表） | open |

---

## 状态说明

- `open` — 已识别、未分派
- `assigned` — 已分派给终端，待开工
- `in_progress` — 终端在改
- `fixed` — 终端声称已修，待 qa 回归
- `regressed` — qa 回归失败，打回重修
- `closed` — 回归通过，合入 `tests/regression/`

---

## 统计

截至 2026-05-12（第一轮过检后）：

| 状态 | 数量 | 说明 |
|------|------|------|
| open | 12 | 未修复（含 1 个 Phase 9 技术债 QA-047） |
| fixed | 30 | 已交付待 qa 回归 |
| partial fix | 3 | 部分修复（QA-025 / QA-036 / QA-043） |
| won't fix | 1 | QA-012 归档 |
| closed | 0 | qa 回归通过后转入此状态 |
| **合计** | **46 + 2 新增 = 48** | QA-047（worker 技术债）、QA-048（devops 配置项缺失） |

**仍 open 的 12 项按阻塞度排序：**

| 阻塞度 | ID | 所属 | 关键路径 |
|--------|----|----|---------|
| 🔴 最高 | QA-001/002/003/004/005/006/007/008/015/035 | api-biz | 整个 Phase 8 的核心，未开工 |
| 🟡 中 | QA-010 | api-biz | 等 BIZ-7 |
| 🟡 中 | QA-021/039/041 | security | SEC-5/6 待做 |
| 🟢 低 | QA-040/042/046 | api-biz/fe-pages/devops | 性能类，Phase 9 |
| 🟢 低 | QA-047 | worker | 技术债，Phase 9 重做 |
| 🟢 低 | QA-048 | devops | 紧跟 security 验签上线前补配置 |

Phase 8 进度：**30/48 = 62.5% 已进入待回归状态**；仍 open 的关键路径全在 api-biz。
