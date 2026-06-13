# Orchestrator 崩溃恢复协议

## 恢复步骤（新会话启动后立即执行）

### Step 0: 加载约束文件（最高优先级）

```
读取 .claude/orchestrator/misconduct.md
读取 .claude/orchestrator/playbook.md
```

misconduct.md 是过失记录与惩罚机制，playbook.md 是行动准则。**两者同时生效，misconduct 优先级高于 playbook**——playbook 说"怎么做事"，misconduct 说"哪些事绝对不能做"。

违反 misconduct 中任何一条的后果：立即停止当前操作，向用户报告，等待指示。没有"下次注意"的缓冲。

### Step 1: 读取状态

```
读取 .claude/orchestrator/state.md
```

这个文件包含：当前阶段、活跃任务、阻塞项、下一步计划。

### Step 2: 确认身份

你是 orchestrator（总指挥），职责：
- 分发指令给 6 个终端
- 回收验证产出
- 维护接口协议
- 协调跨终端依赖

### Step 3: 检查进度

```
读取 .claude/orchestrator/changelog.md（操作日志）
```

找到最后一条记录，确认中断点。

### Step 4: 恢复工作

- 如果有活跃任务未完成 → 继续执行
- 如果有阻塞项 → 向用户确认
- 如果状态干净 → 询问用户下一步

---

## 状态更新规则（防崩溃核心）

### 必须更新 state.md 的时机：

1. **分发任务前** — 先写入任务记录，再执行
2. **任务完成后** — 移入已完成列表
3. **遇到阻塞时** — 记录阻塞原因
4. **阶段切换时** — 更新 phase
5. **做出决策时** — 记录决策和理由

### 更新原则：

- **先写后做**：先把要做的事写进 state，再去做。这样即使中途崩溃，恢复后也知道在做什么。
- **原子记录**：每条记录要自包含，不依赖上下文就能理解。
- **保持精简**：state.md 不超过 100 行，历史操作移入 changelog.md。

---

## 用户快速恢复指令

用户只需要对新会话说：

```
读取 .claude/orchestrator/state.md 和 recovery.md，恢复 orchestrator 角色继续工作。
```

或者更简短：

```
恢复 orchestrator
```

（前提是 CLAUDE.md 中有指引）

---

## 文件结构

```
.claude/orchestrator/
├── playbook.md     # 行动准则（必读，优先级最高）
├── state.md        # 当前状态（必读）
├── recovery.md     # 本文件（恢复协议）
└── changelog.md    # 操作历史日志
```
