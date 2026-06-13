# 代码规范（所有终端必读）

> 本文件是 Phase 8 启动前的强制规范。每个终端开工前必须读完。
> 违反规范的代码 orchestrator 在过检时一律打回，不讨论。

---

## 核心心法：少即是多

**能用 5 行解决的绝不写 10 行。能复用现有代码绝不新写。**

判断标准：删掉一行后功能是否受损？如果不受损，那行就不该存在。

---

## 一、代码量控制

### 1.1 绝对禁止
- 写超出任务范围的"顺手优化"
- 创建新文件，除非任务本身要求（如新建 `security/signing.py`）
- 复制粘贴已有逻辑（先找现有函数复用）
- 加"可能将来用得上"的抽象、接口、基类

### 1.2 强制要求
- 单函数 ≤ 50 行。超出必须拆分或写清理由
- 单文件 ≤ 500 行。超出必须拆模块
- 类的方法 ≤ 10 个。超出考虑组合而非继承
- 修一个 bug 的 diff 尽量控制在 ±30 行以内

### 1.3 复用优先
改动前先搜一遍：
- 后端工具：`app/tasks/_shared.py`、`app/services/`
- 前端工具：`frontend/src/composables/`、`frontend/src/utils/`
- 已有中间件：`app/middleware/`

找不到再新写。

---

## 二、修改范围约束

### 2.1 权限红线
- **只改自己终端可写的文件**（详见 `.claude/team/<代号>.md`）
- 越界的改动一律 revert，不解释
- 需要共享文件改动，找 orchestrator 申请，不要自行动手

### 2.2 只改必要的行
修 bug 时：
- ✅ 只动出 bug 的函数 / 语句
- ❌ 不借机重排 import、改命名、加类型注解、改格式
- ❌ 不修"看起来不好"但没出问题的代码

理由：一个 PR 混入两种变更会让 code review 和回滚都变困难。

### 2.3 不动 Phase 1-7 产物
除非任务明确要求，不要改动已有的：
- 数据库迁移（只新增 `alembic/versions/006_*.py` 等）
- schemas（不改已有字段）
- 路由路径（兼容性红线）

---

## 三、防御性编程的度

### 3.1 只在系统边界校验
需要校验：
- 路由层（用户输入）
- 外部 API 回调
- 文件上传

不需要校验：
- 内部函数互相调用
- 框架已保证的约束（FastAPI + Pydantic 已校验的字段不要再 assert）
- SQLAlchemy 返回的对象不需要再检查类型

### 3.2 异常处理
- 能抛异常让上层处理，就不要 try-except
- 必须 try-except 时：
  - 只捕获具体异常类，不裸写 `except:` 或 `except Exception:`
  - catch 后必须要么重新抛、要么日志记录、要么退款回滚 — **不能吞掉**
- 不在 except 里写 `pass`，任何情况下都不行

### 3.3 TODO 禁令
- 禁止新增 `# TODO` / `# FIXME`
- 要做就做完，不做就不写
- 已存在的 TODO 要么这次解决要么写 issue 给 orchestrator

---

## 四、注释与文档

### 4.1 代码应自解释
好命名 > 注释。函数命名能表达意图就不要注释说一遍。

### 4.2 允许的注释
- 非显而易见的业务规则（如积分定价的来源文档）
- 外部依赖的坑（如"ARK API 某条件下会返回空字符串，所以这里判空"）
- `# noqa`、`# type: ignore` 必须带原因

### 4.3 禁止的注释
- 重述代码在做什么（"这里查询数据库"）
- 过期注释（代码改了注释没改）
- 大段 docstring 写给自己看的设计文档
- 中英文混写（统一中文，项目已有约定）

---

## 五、依赖管理

### 5.1 不引入新依赖
- `requirements.txt`、`package.json` 默认冻结
- 确实需要新库 → 向 orchestrator 申请，说明：
  - 现有库为什么不够
  - 为什么选这个（stars / 维护活跃度 / license）
  - 引入后的维护成本

### 5.2 不升级现有依赖
- 除非 security 终端发现有已知漏洞
- 升级要分独立 PR，不和功能改动混

---

## 六、数据库

### 6.1 SQL 写法
- 全部参数化，不拼字符串
- `text("SELECT ... WHERE id = :id")` + `{"id": x}` 是标准
- 不要 f-string 拼 SQL，哪怕变量是内部的

### 6.2 迁移
- 每个迁移必须可回滚（`downgrade` 写全）
- 迁移文件命名：`<版本号>_<简短描述>.py`
- 一个迁移做一件事，不混合
- 加约束前先跑数据检查，存在违规数据先清洗

### 6.3 不改 schemas
不向已有表加必填字段（会破坏历史数据）。
如必须加，先加 nullable，回填数据，再改 NOT NULL，分三个迁移。

---

## 七、前端

### 7.1 类型
- TypeScript 严格模式（`strict: true`）
- 禁用 `any`（必须用时加 `// any 的理由`）
- API 响应必须有明确类型定义
- 避免 `as` 强转，用 type guard

### 7.2 组件
- 业务页面（fe-pages）不写通用 UI 组件（找 fe-core 做）
- 不复制粘贴页面代码，抽 composable
- CSS 用项目已有的 tokens / utility class，不自建色值

### 7.3 状态
- 页面级状态放 composable / ref，不塞 pinia store
- 全局状态才进 store
- store 保持 thin，复杂逻辑放 service

---

## 八、测试

### 8.1 P0/P1 bug 必须有回归测试
- qa 终端负责写
- 业务终端修完后，通知 qa 加回归

### 8.2 测试不追覆盖率百分比
- 重点测"曾经失败过的路径"和"核心链路"
- 不强制给 getter/setter 写测试
- 不写只复述实现的测试

### 8.3 测试隔离
- 测试不互相依赖
- 测试用临时数据库 / redis DB，不污染开发环境
- 外部 API 全部 mock

---

## 九、安全

### 9.1 日志脱敏
- 手机号、邮箱、身份证、API Key 打印时脱敏
- 异常堆栈不要直接返回给前端

### 9.2 密钥
- 不硬编码
- 不落 git（`.env` 在 `.gitignore`）
- 数据库存储加密（等 security 终端 `app.security.encryption` 交付）

### 9.3 用户输入
- 所有外部入口过 Pydantic 校验
- 文件上传校验 MIME + 大小
- URL 不直接嵌入 HTML / `<img src>` 前白名单过滤

---

## 十、Git 规范

### 10.1 分支
- 前缀必须是终端代号：`auth/` `api/` `worker/` `fe-core/` `fe/` `ops/` `qa/` `sec/`
- 主干用 `main`，禁止直接 push
- 一个分支 = 一件事

### 10.2 Commit
- 格式：`<type>(<scope>): <description>`
- scope 必须是终端代号（含 `qa`、`sec`）
- 中文描述，一句话说清"做了什么"
- 不要 "fix bug"、"update" 这种空描述

### 10.3 PR
- 标题 = 任务 ID + 简述（如 `P8-BIZ-1: 修 _dispatch_director_task 派发表`）
- 描述里必列：
  - 对应 QA Issue ID
  - 改动文件清单
  - 自测步骤
  - 是否需要 qa 加回归

### 10.4 禁止
- `git push --force` 到任何共享分支
- `--amend` 已 push 的 commit
- 把多个任务塞一个 commit
- 改 git config

---

## 十一、自测

### 11.1 提交前必跑
- Python：语法检查（`python -m py_compile`）+ 能启动
- 前端：`npm run build` 过 + `vue-tsc` 无错
- 涉及 DB：迁移 upgrade + downgrade 都跑一遍

### 11.2 提交前必确认
- 没有遗留 `print` / `console.log`
- 没有注释掉的死代码
- 没有新增 TODO
- 没有越权改动

---

## 十二、沟通规范

### 12.1 遇到阻塞立刻报
- 不要憋着自己想 2 小时
- 到 `.claude/orchestrator/state.md` 的"阻塞项"表里加一行
- 艾特涉及的终端 / orchestrator

### 12.2 完成任务通知 orchestrator
- 说明白：改了哪些文件、测试通过情况、任务 ID
- 等 orchestrator 过检 + qa 回归通过，才算 closed
- 不要自己改 qa_issues.md 的状态

### 12.3 不确定就问
- 宁可问一下，不要"我猜 orchestrator 想要这样"
- 尤其是：
  - 需要改共享文件
  - 任务描述有歧义
  - 发现任务描述本身有错

---

## 红线总结（一句话版）

> **只改该改的文件，只做该做的事，用最少的代码，不增加未来维护负担。**

有疑问、发现规范本身有漏洞、觉得某条规则在某场景不合理 — 找 orchestrator，不要自行绕过。
