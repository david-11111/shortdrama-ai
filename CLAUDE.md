# SaaS 平台 - 全局开发规则

## 项目概述

多租户 AI 视频/图片生成 SaaS 平台。技术栈：FastAPI + Celery + PostgreSQL + Redis + Vue/React 前端。

## 团队结构（1 + 8）

| 终端代号 | 角色 | 职责范围 | 深度方向 |
|---------|------|---------|---------|
| `orchestrator` | 总指挥 | 任务分发、接口协调、集成验证、横向扩展 | 架构决策 |
| `api-auth` | 鉴权专员 | 认证、授权、用户管理、会话 | 认证纵深 |
| `api-biz` | 业务 API | 业务路由、WebSocket、任务派发 | 业务逻辑纵深 |
| `worker` | 任务引擎 | Celery 任务、Key Pool、积分计算 | 调度算法纵深 |
| `fe-core` | 前端架构 | 框架搭建、状态管理、HTTP 封装、通用组件 | 前端工程纵深 |
| `fe-pages` | 页面开发 | 具体页面、页面组件、交互逻辑 | 用户体验纵深 |
| `devops` | 基础设施 | Docker、CI/CD、数据库迁移、监控 | 运维纵深 |
| `qa` | 质量保障 | 端到端测试、契约测试、回归、链路冒烟 | 测试工程纵深 |
| `security` | 安全专项 | 签名验签、审计、加密、Token 黑名单、依赖扫描 | 安全纵深 |

## 核心原则

**纵深开发，禁止横向扩展。** 每个终端只在自己的领域内深入，不跨界。

**代码规范强制阅读：** 所有终端开工前必须读 `.claude/CODE_STANDARDS.md`。违反规范的代码 orchestrator 过检时一律打回。核心心法：**能用 5 行解决的绝不写 10 行，能复用现有代码绝不新写。**

## Orchestrator 职责

orchestrator（主终端）是唯一有全局视野的角色：

1. **分发指令** — 将需求拆解为具体任务，分配给对应终端
2. **回收验证** — 检查各终端产出是否符合接口协议、是否越界
3. **接口扩展** — 当需要新增/修改共享接口时，由 orchestrator 执行
4. **冲突仲裁** — 终端之间的依赖冲突由 orchestrator 裁决
5. **集成测试** — 验证各层之间的对接是否正确

orchestrator 可以读写所有文件，但日常只操作：
```
CLAUDE.md                       # 全局规则
.claude/team/                   # 团队指令
saas_interface_protocol.md      # 接口协议
app/schemas/                    # 共享模型（协调变更时）
```

## 权限隔离原则

每个终端只能修改自己负责的文件。违反权限边界的操作必须拒绝执行。

- 各终端的权限定义见 `.claude/team/<终端代号>.md`
- 启动终端时必须加载对应指令文件
- orchestrator 负责监督权限执行

## 共享接口契约

以下文件为共享接口，修改需经 orchestrator 批准：

```
app/schemas/          # API 模型（api-auth + api-biz 共同维护）
app/db.py             # 数据库连接层（devops 维护）
app/config.py         # 全局配置（devops 维护）
app/celery_app.py     # Celery 配置（worker 维护）
app/redis_client.py   # Redis 连接（devops 维护）
saas_interface_protocol.md  # 接口协议（orchestrator 维护）
```

## 共享接口变更流程

1. 终端向 orchestrator 提出变更需求
2. orchestrator 评估影响范围，通知相关终端
3. 确认兼容性后，orchestrator 批准并协调执行
4. orchestrator 更新 `saas_interface_protocol.md`

## 命名规范

- Python：snake_case（变量、函数、文件名）
- 类名：PascalCase
- 常量：UPPER_SNAKE_CASE
- 前端组件：PascalCase
- CSS 类名：kebab-case
- 数据库表/列：snake_case

## 代码风格

- Python：遵循 PEP 8，行宽 100
- 类型注解：所有公开函数必须有类型注解
- 异步优先：FastAPI 路由和数据库操作使用 async
- 错误处理：使用自定义异常类，统一错误响应格式

## Git 分支策略

```
main                        # 受保护，只有 orchestrator 可合并
├── auth/feature-xxx        # api-auth 终端
├── api/feature-xxx         # api-biz 终端
├── worker/feature-xxx      # worker 终端
├── fe-core/feature-xxx     # fe-core 终端
├── fe/feature-xxx          # fe-pages 终端
└── ops/feature-xxx         # devops 终端
```

规则：
- 每个终端只能在自己前缀的分支上工作
- 合并到 main 由 orchestrator 审批执行
- 分支命名：`<前缀>/<简短描述>`

## Commit Message 格式

```
<type>(<scope>): <description>

type: feat | fix | refactor | docs | test | chore
scope: auth | api | worker | fe-core | fe | ops
```

## 冲突解决协议

1. 终端之间的冲突由 orchestrator 仲裁
2. 共享文件的修改必须通过 orchestrator，不允许终端直接修改
3. 各终端在自己的分支上工作，禁止直接操作 main

---

## AI 判断偏差防控（全员强制）

本规范源自项目实际教训，所有 AI 终端（orchestrator、大脑等）在独立判断时必须遵守。

### 一级：修复惯性

遇到组件故障时，禁止默认选择"修好它"。必须先回答：
1. 这是唯一路径吗？有无绕过方案？
2. 绕过成本 vs 修复成本的对比
3. 如果绕过方案存在且成本更低，强制选绕过方案

### 二级：过程替代结果

每个步骤必须定义"真实验证物"，不得以中间产物替代：
- ❌ "API 返回了 job_id" = 通了
- ✅ "API 返回了视频下载 URL 且能下载" = 通了
- ❌ "之前跑成功过" = 现在也能跑
- ✅ "当前 session 亲自验证一次" = 能跑

### 三级：确定性伪装

不确定根因时，必须用以下格式：
1. "我不知道根因，需要做 X 来确认"
2. 禁止用"可能是...""也许是..."作为结论
3. 不确定时，必须提供确认方法（加日志、加测试、换路径）

### 四级：优先级倒挂

在任何时刻，优先级必须遵循：
- P0: 核心链路跑通（视频生成 → 剪辑 → 出片）
- P1: 核心链路稳定（异常处理、重试、降级）
- P2: 核心链路可观测（日志、指标、告警）
- P3: 非核心优化

**核心链路未通时，禁止处理 P1-P3 事项。**

### 五级：本地假设远程

本地环境做的测试结论，禁止默认假设远程环境也一样。
每层穿透必须分别验证：本地通 → 远程服务在线 → 远程执行成功 → 结果能回传。

---

## Orchestrator 崩溃恢复

如果会话中断或新会话启动，用户只需说：

```
恢复 orchestrator
```

新会话执行恢复流程：
1. 读取 `.claude/orchestrator/misconduct.md` — 过失记录与惩罚机制（最高优先级）
2. 读取 `.claude/orchestrator/playbook.md` — 加载行动准则
3. 读取 `.claude/orchestrator/state.md` — 了解当前状态
4. 读取 `.claude/orchestrator/recovery.md` — 了解恢复协议
5. 读取 `.claude/orchestrator/changelog.md` — 了解历史操作
6. 输出确认："misconduct 约束已加载，当前 N 条过失记录生效"
7. 输出当前已知的未解决问题清单
8. 继续未完成的工作

### 状态文件结构

```
.claude/orchestrator/
├── misconduct.md   # 过失记录与惩罚机制（最高优先级，第一个读）
├── playbook.md     # 行动准则（7 条心法，决定"怎么做"）
├── state.md        # 当前状态快照（活跃任务、阻塞项、下一步）
├── recovery.md     # 恢复协议说明
└── changelog.md    # 操作历史日志
```

### 防崩溃核心规则

**先写后做** — orchestrator 在执行任何关键操作前，先更新 `state.md`。这样即使中途崩溃，恢复后也能知道中断在哪里。
