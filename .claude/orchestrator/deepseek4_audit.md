# DeepSeek4 能力审计：为什么视频流水线做不到 Claude 级别的处理

**审计日期**: 2026-05-28
**审计范围**: 全项目 AI/LLM 集成层、Agent 编排、错误恢复、上下文管理

---

## 一、总体判断

项目的基础设施非常扎实（Key Pool、重试/死信、状态机、事件溯源），但 **"大脑"层面有 6 个结构性缺陷**，导致整体智能水平远低于 Claude。DeepSeek4 本身能力足够强，问题不在模型，在**架构设计**。

---

## 二、6 个核心缺陷

### 缺陷 1：规划器是"分类器"而非"推理器"

**现状** (`llm_planner.py:71-92`):
- 给 DeepSeek 的是一个 20 行的 system prompt，让它从 6 个固定 action 中选一个
- `max_tokens=512`，只够输出一个简短 JSON
- temperature=0.1，几乎无创造力
- 本质是一个 **intent classifier**，不是 reasoning engine

**Claude 的做法**:
- 扩展思考（extended thinking）可以消耗数万 token 做深度推理
- 思考过程包括：问题分解 → 方案枚举 → 利弊权衡 → 选出最优路径
- 思考 token 对用户不可见但影响最终决策质量

**差距量化**: 当前系统给 DeepSeek 的"思考预算"是 512 token，Claude 的扩展思考可达 32K token。相差 **60 倍**。

### 缺陷 2：决策是确定性的，不是 Agentic 的

**现状** (`run_coordination.py:64-181`):
- `evaluate_decision_tick()` 是纯 Python 逻辑——if/else 判断状态，查表路由
- LLM 只参与第一步（intent classification），后续路径完全硬编码
- `recommend_next_action()` 从 14 个固定阶段中按顺序推荐下一个

**Claude 的做法**:
- 每一步都由 LLM 决定下一步做什么
- Tool use 是动态的——模型根据当前上下文自主选择工具
- 同一个输入可能走不同路径，因为模型在推理

**差距**: 你有一个 "agent runtime" 的外壳，但内部决策是状态机，不是 agent。**名字叫 agent，实质是 workflow。**

### 缺陷 3：没有自我纠错闭环

**现状**:
- 任务失败 → 重试（指数退避）→ 死信队列 → 人工介入
- `director/reasoning.py` 有诊断引擎，但是**基于关键词规则**，不是 LLM 驱动的
- `evolution.py` 记录成功/失败案例，但不反馈到实时决策中

**Claude 的做法**:
- 工具调用失败后，Claude 会分析错误原因，换一种方式重试
- 代码生成 → 执行 → 读错误 → 修复 → 再执行（autonomous loop）
- 自我纠错是核心能力，不是附加功能

**缺失的关键环节**: 需要一个 "反思节点"——LLM 看到失败后，分析根因，生成新的执行策略。当前系统的重试是**盲重试**（相同参数再来一次），而非**智能重试**（换方法再来）。

### 缺陷 4：上下文管理太粗糙

**现状** (`context_budget.py`):
- 中间截断：`text[:head] + "...[context trimmed]..." + text[-tail:]`
- 超过预算就丢弃历史消息
- 没有 prompt caching
- 没有语义压缩（只是字符级截断）

**Claude 的做法**:
- Prompt caching——重复使用的 system prompt 自动缓存
- 上下文窗口内智能分配——重要信息保留，冗余信息压缩
- 支持 200K token 上下文窗口

**差距**: 你的 `max_total_chars=24000`（约 6K token），DeepSeek4 支持 128K+。你在**自我设限**。

### 缺陷 5：工具集硬编码，无法扩展

**现状** (`llm_planner.py:15-22`):
```python
PLANNER_ACTIONS = {
    "status_query",
    "generate_story_plan",
    "plan_visual_assets",
    "generate_keyframes",
    "generate_videos",
    "plan_final_edit",
}
```
只有 6 个 action。新增一个能力需要改 planner prompt + coordination logic + dispatch gateway。

**Claude 的做法**:
- Tool use 通过 JSON Schema 定义，新增工具只需加一个 schema
- 模型自主决定何时调用哪个工具
- 可以同时调用多个工具（parallel tool calls）

**差距**: 你的系统是 **closed-loop controller**，Claude 是 **open-ended agent**。

### 缺陷 6：没有"思考可见性"

**现状**:
- `llm_stream.py` 只流式传输**回复内容**给前端
- Planner 的决策过程对外不可见
- `decision_mailbox.py` 有 `thinking_artifacts` 字段但内容极简

**Claude 的做法**:
- 扩展思考的 token 对用户可见（折叠显示）
- 用户可以审查 AI 的推理过程
- 提高了信任度和可调试性

---

## 三、项目做得好的地方（保持）

| 能力 | 评价 |
|------|------|
| Key Pool 并发管理 + 冷却机制 | 生产级，超越多数开源项目 |
| 错误分类 10 类 + 差异化重试策略 | 精细，成熟 |
| Agent Event 事件溯源 | 架构正确，可观测性好 |
| 死信队列 + 过期任务清理 | 完善 |
| 积分预留/扣款/退款机制 | 金融级安全 |
| 14 阶段生产状态机 | 业务建模完整 |
| 多 Provider 适配层 | 扩展性好 |

---

## 四、改进路线图（按优先级）

### P0 — 让 DeepSeek 真正"思考"

**改动文件**: `llm_planner.py`

当前给 DeepSeek 的 token 预算太少。改为：

1. **扩大 max_tokens 到 4096+**，让模型有空间输出推理链
2. **在 system prompt 中要求 CoT（思维链）**：先分析、再推理、最后输出 JSON
3. **使用 DeepSeek 的 reasoning 能力**（如果 deepseek-chat 支持，或用 deepseek-reasoner）

```
当前: max_tokens=512, temperature=0.1, 一步出 JSON
改进: max_tokens=4096, 先出分析再出 JSON, 或者分两步调用
```

### P1 — 让决策真正 Agentic

**改动文件**: `run_coordination.py`, `main_chain_controller.py`

当前是 Python 状态机决定下一步。改进方向：

1. **每个 tick 都调用 LLM 做决策**，不只依赖状态机
2. **把候选 actions + 证据 + 历史失败作为 context 传给 LLM**
3. LLM 输出下一步 action + 推理原因 + 备选方案

```
当前: evaluate_decision_tick() → Python 状态机 → 固定 action
改进: evaluate_decision_tick() → 组装 context → LLM 推理 → 动态 action
```

### P2 — 加入反思/自我纠错

**改动文件**: 新增 `app/services/error_reflection.py`

任务失败后，不要盲重试：

1. 收集失败信息（error message + 输入参数 + 上下文）
2. 调用 LLM 分析失败原因
3. LLM 输出修正方案（改 prompt、换参数、换 provider、降级处理）
4. 用修正后的方案重试

### P3 — 上下文管理升级

**改动文件**: `context_budget.py`

1. 不要中间截断——用 LLM 做摘要压缩（语义压缩 > 字符截断）
2. 提高 token 预算上限（DeepSeek4 支持 128K，你现在只用 6K）
3. 给 system prompt 加缓存标记

### P4 — 工具集可扩展

将 `PLANNER_ACTIONS` 改为注册机制，新增 action 只需注册 handler + gate rule + prompt hint。

### P5 — 思考可见性

将 planner 的推理过程通过 Redis pub/sub 流式推送到前端（类似 Claude 的 thinking block）。

---

## 五、关于 DeepSeek4

DeepSeek4 本身能力足够。问题在于：

1. **你只用了它的"嘴"（生成回复），没用到它的"脑"（深度推理）**
2. 512 token 的输出预算是对模型能力的浪费
3. 确定性状态机替代了 LLM 应该在的位置

**一句话诊断**: 你的系统架构是"用 LLM 增强的传统流水线"，而 Claude 是"LLM 驱动的自主 Agent"。差距在架构范式，不在模型能力。

---

## 六、立即可做的 Quick Win

改动 `llm_planner.py` 这一个文件，3 处修改，预计投入 30 分钟：

1. `max_tokens`: 512 → 4096
2. system prompt: 增加 CoT 要求（"先分析用户意图，再给出决策理由，最后输出 JSON"）
3. 解析逻辑: 如果 JSON 前有文本，先提取 JSON（容错）

这个改动让 DeepSeek 有空间"想"了，虽然离 Claude 的扩展思考还有差距，但方向对了。
