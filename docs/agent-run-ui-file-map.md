# Agent-Run 界面↔文件配对清单

## 一、界面区域 → 文件映射

### 启动页 `/director/agent-run`

| 界面元素 | 前端文件 | 后端 API |
|---------|---------|---------|
| 项目选择器 / 新建项目 | `index.vue` + `LaunchInput.vue` | `GET /api/projects` (workbench) / `POST /api/projects` |
| 目标输入框 + 快捷提示 | `LaunchInput.vue` | — |
| 模式/预算高级设置 | `LaunchInput.vue` | — |
| 输入资产上传 | `index.vue` (file input) | `POST /api/projects/{id}/assets` |
| "开始执行"按钮 | `index.vue` → `createAgentRun()` | `POST /api/agent-runs` |
| 最近执行列表 | `RecentRuns.vue` | `GET /api/agent-runs?project_id=` |

### 观察页 `/director/agent-run/:runId`

| 界面区域 | 前端文件 | 后端 API / 数据源 |
|---------|---------|-----------------|
| **左侧状态栏** | `RunStatusBar.vue` | `snapshot.run` (状态/目标/预算/进度/耗时/阶段/决策上下文) |
| 运行状态 (● 完成) | `RunStatusBar.vue` | `snapshot.run.status` |
| 预算条 (28/500) | `RunStatusBar.vue` | `snapshot.budget.spent` / `allowed` |
| 进度 (4/6 任务) | `RunStatusBar.vue` | `snapshot.tasks` count |
| 耗时 | `[runId].vue` 计算 | `snapshot.run.created_at` |
| 生产阶段 / Gate | `RunStatusBar.vue` | `snapshot.state_machine` / `snapshot.actions` |
| 决策上下文 | `RunStatusBar.vue` | `snapshot.decision_context` |
| [首页] 按钮 | `RunStatusBar.vue` emit `goHome` | — (router.push) |
| [取消] 按钮 | `RunStatusBar.vue` emit `cancelRun` | `POST /api/agent-runs/{id}/actions/cancel` |
| [专家后台] 按钮 | `RunStatusBar.vue` emit `openExpert` | — (router.push `/director/produce`) |
| **顶部横幅** | `RunBanner.vue` | `snapshot.run.status` + 信用限额检测 |
| **中间 - 执行链 Tab** | `EventTimeline.vue` + `EventItem.vue` | `snapshot.stream[]` + SSE |
| **中间 - 对话 Tab** | `ChatStream.vue` + `ChatBubble.vue` / `ChatStepCard.vue` / `ChatMediaCard.vue` / `ChatProgressBar.vue` | SSE (`llm_chunk`, `execution_event`) + `snapshot.stream[]` |
| **右侧 - 成果区** | `OutputBoard.vue` | `snapshot.outputs` (images/videos/shots/keyframe_pool/script/notes) |
| **右侧 - 证据账本** | `EvidenceLayers.vue` | `snapshot.evidence` |
| **底部输入框** | `[runId].vue` (composer section) | `POST /api/agent-runs/{id}/actions/continue-step` |
| 路由选择下拉 | `[runId].vue` (DeepSeek/中控) | `continue-step` body.action_hint |
| "发送" 按钮 | `[runId].vue` → `continueAgentRunStep()` | `POST /api/agent-runs/{id}/actions/continue-step` |

---

## 二、成果区 (OutputBoard) 操作 → API

| 操作按钮 | 前端位置 | 后端 API | 服务函数 |
|---------|---------|---------|---------|
| Provider 下拉选择 | `OutputBoard.vue` line ~99 | localStorage 存储 | — |
| "预览多图" | `OutputBoard.vue` | `POST /agent-runs/{id}/actions/keyframe-batch/preview` | `_build_keyframe_variation_prompts` |
| "生成多图" | `OutputBoard.vue` | `POST /agent-runs/{id}/actions/generate-keyframe-batch` | `reserve_credits` → Celery `image_tasks` |
| "设为主图" | `OutputBoard.vue` | `POST /agent-runs/{id}/actions/select-keyframe-candidate` | UPDATE shot_rows |
| "生成视频" | `OutputBoard.vue` | `POST /agent-runs/{id}/actions/generate-video-from-pool` | `reserve_credits` → Celery `video_tasks` |
| "刷新" | `OutputBoard.vue` emit `refresh` | `GET /agent-runs/{id}/snapshot` | `get_agent_run_snapshot` |

---

## 三、实时数据通道

| 通道 | 前端组件 | 后端端点 | 数据流 |
|------|---------|---------|--------|
| SSE 事件流 | `useAgentRunStream.ts` → `EventTimeline` / `ChatStream` | `GET /api/agent-runs/{id}/stream?token=` | Redis pubsub `project:{pid}:events` → SSE |
| WebSocket 任务进度 | `useWebSocket.ts` / `useAgentEvents.ts` | `WS /ws/tasks?token=` | Redis pubsub `task:{tid}:progress` → WS |
| Snapshot 轮询 | `useAgentRunSnapshot.ts` → `[runId].vue` setInterval | `GET /api/agent-runs/{id}/snapshot` | PostgreSQL 全量查询 |

---

## 四、Snapshot 数据结构 → 界面区域

```
snapshot = {
  run:              → RunStatusBar (状态/目标)
  budget:           → RunStatusBar (预算条)
  nodes:            → RunGraph (产出流程图) [当前未使用]
  stream:           → EventTimeline / ChatStream (事件流)
  evidence:         → EvidenceLayers (证据账本)
  outputs: {
    images:         → OutputBoard 图片网格
    videos:         → OutputBoard 视频列表
    shots:          → OutputBoard 镜头状态行
    keyframe_pool:  → OutputBoard 关键帧候选池
    script:         → OutputBoard 剧本文本
    director_notes: → OutputBoard 导演笔记
    summary:        → OutputBoard 顶部统计
  }
  tasks:            → 底部任务队列 [当前未独立展示]
  state_machine:    → RunStatusBar (Gate 状态)
  actions:          → RunStatusBar / ActionBar
  decision_context: → RunStatusBar (决策上下文)
  meta:             → 内部使用
}
```

---

## 五、后端服务函数 → 职责

| 文件 | 关键函数 | 职责 |
|------|---------|------|
| `agent_run_snapshot.py:67` | `get_agent_run_snapshot()` | 组装完整快照 (2060 行) |
| `agent_run_snapshot.py:1202` | `_build_outputs()` | 构建成果区数据 |
| `agent_run_snapshot.py:1347` | `_build_keyframe_pool()` | 构建关键帧候选池 |
| `agent_runtime.py:104` | `create_agent_run()` | 创建 run 记录 |
| `agent_runtime.py:362` | `publish_agent_event()` | 发布事件到 Redis + DB |
| `agent_runtime.py:517` | `record_agent_artifact()` | 记录产物 |
| `run_coordination.py:68` | `evaluate_decision_tick()` | 状态机决策 |
| `run_coordination.py:188` | `load_run_facts_from_snapshot()` | 加载 facts 用于决策 |
| `llm_planner.py:53` | `plan_human_instruction()` | DeepSeek 路由用户指令 |
| `llm_stream.py:162` | `stream_llm_reply_to_redis()` | 流式对话回复 |
| `fallback_reasoning.py:155` | `attempt_fallback()` | 降级推理 |
| `agent_evidence_composer.py:37` | `compose_evidence_reply()` | 证据组合回复 |

---

## 六、未使用 / 冗余组件（重构时可考虑删除或合并）

| 文件 | 状态 | 说明 |
|------|------|------|
| `RunGraph.vue` | 未在 [runId].vue 渲染 | 被 EventTimeline 取代 |
| `RunTimeline.vue` | 未在 [runId].vue 渲染 | 被 EventTimeline 取代 |
| `RunHeader.vue` | 未在 [runId].vue 渲染 | 被 RunStatusBar 取代 |
| `ActionBar.vue` | 未在 [runId].vue 渲染 | 功能合并到 RunStatusBar |
| `EvidenceDrawer.vue` | 未在 [runId].vue 渲染 | 被 EvidenceLayers 取代 |

---

## 七、重构影响范围预估

**必须改的文件：**
1. `[runId].vue` — 整体布局从 flex-column 改为 CSS Grid
2. `OutputBoard.vue` — 几乎重写（缩略图网格 + 大图预览 + tabs）
3. `EventTimeline.vue` — 增加内联产物缩略图
4. `ChatMediaCard.vue` — 增加内联视频预览
5. `useAgentRunSnapshot.ts` — 增加选中态管理

**可能改的文件：**
6. `RunStatusBar.vue` — 样式微调适配新网格
7. `EvidenceLayers.vue` — 改为底部 tab 或折叠面板

**不需要改的文件：**
- 所有后端 API 端点（数据结构不变）
- `useAgentRunStream.ts`（SSE 逻辑不变）
- `useChatMessages.ts`（消息构建逻辑不变）
- `director.ts`（API 函数不变）
- `timelineEvents.ts`（事件归一化不变）
