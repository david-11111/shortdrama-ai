# Main Chain 7-Layer Code Verification

**Date:** 2026-05-27  
**Scope:** 对照 `docs/main-chain-function-tree-diagnosis.md` 的 7 层主链，逐层核对当前代码链路、API 入口、调度路径和任务终态回流。

## 0. Verification Verdict

目标文档的方向是对的：系统要成为一个 Codex-style 的短剧生产 agent，核心必须是：

```text
goal
-> authoritative run
-> unified facts
-> decision packet
-> dispatch gateway
-> lane execution
-> terminal observation
-> next decision / recover / block / complete
```

当前代码已经有这些零件，但还没有形成严格闭环。最关键的问题不是缺少某一个工具能力，而是 **主链不是唯一命令路径，且 L7 terminal observation 之后没有自动把可执行 decision packet 回送到 L4 dispatch gateway**。

结论分级：

| Layer | 目标 | 当前状态 | 结论 |
| --- | --- | --- | --- |
| L1 | Authoritative Run | PARTIAL | 有 `agent_runs`，但入口不唯一，兼容 run 和子 run 混用 |
| L2 | Unified Facts | PARTIAL | 有 snapshot facts，但仍有 workbench/project brain 局部 facts |
| L3 | Decision Packet | PARTIAL | 有 `DecisionTickResult`，但生产派发多用 compatibility packet |
| L4 | Dispatch Gateway | PARTIAL | 网关存在，但不是所有生产/控制路径唯一入口 |
| L5 | Lane Execution | PARTIAL | A/B/C lane 均存在，但 B lane 仍可触发执行路径 |
| L6 | Terminal Observation | PASS-PARTIAL | 任务终态统一 hook 存在，但只是观察和记录 |
| L7 | Next Decision | FAIL-PARTIAL | 能计算 next decision，不能自动续派发形成闭环 |

主因判断：

```text
架构问题约 70%:
  主链没有成为唯一权威控制器。
  L7 只观察，不推进。
  compatibility wrapper 仍承担真实派发。

细节问题约 30%:
  决策包来源不一致。
  B lane 权限边界过宽。
  直接任务 API 与 agent run 主链并存。
  文档/API/action surface 同步不足。
```

## 1. Expected Main Chain

`docs/main-chain-function-tree-diagnosis.md:60-162` 已定义主链层次：

```text
L1 Authoritative Run
L2 Unified Facts
L3 Decision Packet
L4 Dispatch Gateway
L5 Lane Execution
L6 Terminal Observation
L7 Next Decision
```

其中 L4 的目标是 "the only place production work should be queued"，L7 的目标是任务终态后继续、等待、恢复、询问用户或完成。

## 2. Actual Main Paths Found In Code

### Path A: Agent Run 创建入口

代码证据：

- `app/routes/agent_runs.py:68-155`
- `POST /api/agent-runs`
- `production_run` 没有 storyboard 时调用 `continue_project_brain(... action=generate_story_plan ...)`
- 有 storyboard 时调用 `start_video_production(...)`
- `continue_project` 调用 `continue_project_brain(...)`

诊断：

```text
POST /api/agent-runs
-> create agent run
-> branch:
   -> continue_project_brain
   -> start_video_production
```

这是一个高层入口，但不是唯一权威主链。它根据 action 分叉到 workbench 兼容路径或 production start 路径。

### Path B: Agent Run continue-step 控制入口

代码证据：

- `app/routes/agent_runs.py:351-955`
- `POST /api/agent-runs/{run_id}/actions/continue-step`
- 路由栈包括 `_build_human_continue_body`、`_apply_planner_routing`、`_apply_control_intent_routing`、`attach_semantic_control`
- 运行期策略调用 `decide_runtime_action(...)`
- execute 时调用 `_ensure_action_gate_allows(...)`
- 通过 `dispatch_agent_action(...)` 做 B lane 执行
- `execute_continue_project(...)` 可调用 `continue_project_brain(...)`
- `execute_final_edit(...)` 可直接调用 `director_export_preview(...)`

诊断：

```text
continue-step
-> B lane routing / diagnostics / semantic control
-> dispatch_agent_action
   -> status/diagnostics answer
   -> plan_visual_assets -> continue_project_brain
   -> plan_final_edit -> director_export_preview
   -> fallback -> continue_project_brain
```

B lane 不是纯解释/诊断层，它有触发生产或剪辑的执行分支。因此它和 L4 dispatch gateway 的权威边界没有完全隔离。

### Path C: Project brain continue 兼容主链

代码证据：

- `app/routes/workbench.py:1044-1385`
- `POST /api/projects/{project_id}/brain/continue`
- 加载 `shot_rows`、`final_edit_plan`、`visual_plan`
- `build_project_brain(...)`
- `action = requested_action or current_brain.next_action`
- `evaluate_action_gate(...)`
- `create_agent_run(...)`
- 生产动作调用 `_dispatch_production_action(...)`
- 规划循环调用 `build_story_understanding_with_llm(...)` 和 `continue_project_from_brain(...)`

诊断：

```text
brain/continue
-> project-local facts
-> project_brain.next_action
-> create child agent run
-> planning loop or production dispatch
-> compatibility decision packet
-> dispatch_authoritative_packet
```

这是当前最接近主链的真实生产路径，但它的 decision packet 是兼容包装，不是直接从 L2 unified snapshot facts 生成。

### Path D: Production start 兼容入口

代码证据：

- `app/routes/workbench.py:758-837` 创建 production start run
- `app/routes/workbench.py:840-904` 使用 `_build_compatibility_decision_packet(...)`
- `app/routes/workbench.py:893-904` 调用 `dispatch_authoritative_packet(...)`
- `app/routes/workbench.py:907-1021` 队列化 `video_production_run_task`

诊断：

```text
production/start
-> create_agent_run
-> compatibility DecisionTickResult(action=video_production_run)
-> dispatch_authoritative_packet
-> queue video_production_run_task
```

这条路径经过 gateway，但 packet 仍是 compatibility packet。

### Path E: Direct SaaS task APIs

代码证据：

- `app/main.py:179-231` `/api/batch/generate-videos`
- `app/main.py:234-280` `/api/batch/generate-images`
- `app/main.py:283-321` `/api/tts/generate`
- `app/services/task_submission.py:34-117` `submit_batch_tasks(...)`
- `app/services/task_submission.py:120-175` `submit_single_task(...)`

诊断：

```text
direct API
-> submit_batch_tasks / submit_single_task
-> INSERT tasks
-> celery_app.send_task
```

这些 API 不经过 agent run decision packet 和 dispatch gateway。作为 SaaS 原子能力可以保留，但从 Codex-style 主链视角看，它们必须被明确标注为 platform/direct-task path，不能被视为主链的一部分。

## 3. Layer-By-Layer Verification

### L1 Authoritative Run

目标不变量：

```text
所有自动生产都必须归属于一个 authoritative agent_run。
run 是 goal、budget、phase、status、events、tasks 的唯一上层容器。
```

代码存在：

- `app/routes/agent_runs.py:68-155` 创建 agent run 后按 action 分发。
- `app/routes/workbench.py:794-817` `production/start` 创建 agent run，并在 meta 中标记 `dispatch=dispatch_gateway`、`compatibility_only=True`。
- `app/routes/workbench.py:1105-1125` `brain/continue` 每次创建一个 run，并保留 `_chain_run_id/source_run_id`。
- `app/tasks/_shared.py:740-778` 任务终态后可按 sibling tasks 更新 `agent_runs.status`。

断点：

- `brain/continue` 会创建新的 run，并用 `_chain_run_id` 关联来源。真实主链更像多个兼容 run 串联，而不是一个 run 自己推进到底。
- `production/start` 的 run 明确带 `compatibility_only=True`，说明它不是完全权威主链。
- direct task API 在 `app/main.py:179-321` 不创建 authoritative run。

状态：PARTIAL

结论：

L1 容器存在，但“唯一主 run”没有被强制。当前更像 `agent_run`、`brain/continue run`、`production run task`、direct task 并存。

### L2 Unified Facts

目标不变量：

```text
所有决策必须读取同一个事实源：
workspace markdown/json + DB shot_rows/tasks/assets/final_edit_plans/video_production_runs + runtime state。
```

代码存在：

- `app/services/run_coordination.py:184-198` `load_run_facts_from_snapshot(...)` 从 `get_agent_run_snapshot(...)` 读取 run outputs、shots、tasks、production_run。
- `app/services/run_coordination.py:190-191` 复用 `_effective_tasks_for_state(...)`，避免 superseded failed media tasks 污染决策。
- `app/routes/workbench.py:1044-1089` `brain/continue` 自己加载 `shot_rows`、`final_edit_plan`、`visual_plan` 并构建 `current_brain`。
- `app/services/project_brain.py:1976-2007` A lane 根据 signals/risks 决定 phase 和 `next_action`。

断点：

- L7 terminal decision 使用 snapshot facts；workbench 生产派发使用 `before/current_brain` 局部 facts。两者事实入口不统一。
- `project_brain._decide_phase(...)` 仍是一个 lane-local next_action 决策器，不是只给 L3 提供 facts。
- direct task API 不绑定 run snapshot，因此无法被 L2 统一事实完整观察。

状态：PARTIAL

结论：

有 unified facts 的雏形，但不是所有主链派发都从它开始。现在是 `snapshot facts` 和 `project_brain facts` 并存。

### L3 Decision Packet

目标不变量：

```text
下一步必须是结构化 packet，而不是单个 next_action。
packet 必须包含 action、selected_lane、dispatchable、allowed_writes、evidence_refs、budget、risk、failure_policy、success_criteria、mission。
```

代码存在：

- `app/services/run_coordination.py:37-59` `DecisionTickResult` 字段覆盖目标 packet。
- `app/services/run_coordination.py:64-181` `evaluate_decision_tick(...)` 能返回 `wait/recover/complete/blocked/execute`。
- `app/services/run_coordination.py:298-335` `_decision_result(...)` 设置 `selected_lane`、`dispatchable`、`allowed_writes`、`evidence`、`mission`。
- `app/services/run_coordination.py:489-503` `_mission_payload(...)` 生成 `mission_id/lane/action/write_scope/idempotency_key`。
- `tests/unit/test_run_coordination.py:46-63` 测试确认 execute packet 包含 dispatch fields。

断点：

- `app/routes/workbench.py:1415-1496` `_build_compatibility_decision_packet(...)` 手工构造 `DecisionTickResult`，`status=execute`、`dispatchable=True`、`allowed=True`，reason 为 compatibility wrapper。
- `app/routes/workbench.py:1553-1561` `_dispatch_production_action(...)` 使用 compatibility packet，而不是调用 `load_run_facts_from_snapshot(...) -> evaluate_decision_tick(...)`。
- `production/start` 的 `video_production_run` action 也用 compatibility packet，且它不是 `run_coordination.evaluate_decision_tick(...)` 自然产生的 action。

状态：PARTIAL

结论：

L3 的 packet 类型是对的，但真实派发使用的 packet 来源不够权威。当前是“有权威 packet 模型，但兼容包装器在替它下命令”。

### L4 Dispatch Gateway

目标不变量：

```text
所有 production work 只能在 dispatch gateway 排队。
gateway 必须 validate packet、更新 run、发 dispatch event、执行一个 lane handler。
```

代码存在：

- `app/services/run_dispatch_gateway.py:24-67` `dispatch_authoritative_packet(...)` 更新 run 到 `dispatch_gateway`、发布 `dispatch_gateway` event、调用 handler。
- `app/services/run_dispatch_gateway.py:70-81` `_validate_packet(...)` 拒绝非 execute/non-dispatchable/missing mission packet。
- `tests/unit/test_run_dispatch_gateway.py:44-80` 覆盖 update/publish/handler。
- `tests/unit/test_run_dispatch_gateway.py:83-105` 覆盖 non-dispatchable packet 被拒绝。
- `app/routes/workbench.py:893-904` `production/start` 经过 gateway。
- `app/routes/workbench.py:1599-1610` `brain/continue` 生产动作经过 gateway。

断点：

- `app/main.py:179-321` direct generate images/videos/tts 不经过 gateway。
- `app/services/agent_action_executor.py:110-134` B lane 可调用 `execute_continue_project` 或 `execute_final_edit`，其中 final edit 可走 `director_export_preview`。
- `app/routes/agent_runs.py:644-659` continue-step 的 final edit 分支可直接调用 `director_export_preview(...)`。
- gateway 目前只校验 packet shape，没有强制 idempotency、budget、write_scope 落地约束。预算检查在 handler 内，例如 `app/routes/workbench.py:2053-2058`。

状态：PARTIAL

结论：

gateway 已经存在，并且部分生产动作经过它。但它不是所有生产排队和剪辑执行的唯一入口，也没有完全拥有 budget/idempotency/write-scope enforcement。

### L5 Lane Execution

目标不变量：

```text
A lane 负责 project brain/workspace intelligence。
B lane 负责 UI control、status、diagnostics、human routing。
C lane 负责 provider production、final edit。
lane 执行必须由 L4 选中并调用。
```

代码存在：

A lane:

- `app/services/project_brain.py:1976-2007` `_decide_phase(...)` 生成 `generate_story_plan/plan_visual_assets/generate_keyframes/generate_videos/plan_final_edit/open_final_cut`。
- `app/routes/workbench.py:1213-1287` planning loop 调用 `build_story_understanding_with_llm(...)` 和 `continue_project_from_brain(...)`。

B lane:

- `app/services/agent_control_registry.py:4-11` `HUMAN_EXECUTABLE_ACTIONS` 包含 `status_query/generate_story_plan/plan_visual_assets/generate_keyframes/generate_videos/plan_final_edit`。
- `app/services/agent_control_registry.py:13-80` capability registry 定义 tools/gates/verify。
- `app/services/agent_action_executor.py:50-136` 根据 routing/tool/action 返回 diagnostics、status、deferred、visual asset、final edit 执行结果。

C lane:

- `app/routes/workbench.py:1990-2139` `_continue_generate_batch(...)` 选择目标 shots、做并发/频控/预算、插入 tasks、`celery_app.send_task(...)`。
- `app/routes/workbench.py:1726-1839` `_continue_plan_final_edit(...)` 读取 selected videos 并写入 final edit plan。
- `app/tasks/video_tasks.py:35` `generate_video_task(...)` 是 video worker 入口。
- `app/tasks/image_tasks.py:38` `generate_image_task(...)` 是 image worker 入口。

断点：

- B lane 的 `HUMAN_EXECUTABLE_ACTIONS` 包含生产动作，边界不够窄。
- A lane 仍产出 `next_action` 并驱动 `brain/continue`，它不是纯 facts/planning provider。
- C lane task insertion 和 gateway 的约束分散，真实预算/队列写入在 handler 中完成。

状态：PARTIAL

结论：

lane 能力齐全，但 lane 的职责边界没有完全按主链收口。最危险的是 B lane 同时做控制、诊断和部分执行触发。

### L6 Terminal Observation

目标不变量：

```text
每一个 terminal task 都必须回到同一个 hook：
persist task state -> publish event -> drain pending instruction -> observe decision tick -> maybe finalize run。
```

代码存在：

- `app/tasks/_shared.py:484-491` `_persist_and_publish(...)` 在 `task_complete/task_failed` 后调用 `_drain_pending_instruction(...)`、`_observe_run_coordination_after_task(...)`、`_maybe_finalize_run(...)`。
- `app/tasks/_shared.py:512-529` failed/dead-letter 路径也调用同一组后置 hook。
- `app/tasks/_shared.py:503-509` `_observe_run_coordination_after_task(...)` 调用 `observe_task_terminal_decision_tick(task_id)`。
- `app/services/run_coordination.py:201-222` `observe_task_terminal_decision_tick(...)` 读取 task run context、加载 facts、evaluate decision、插入 decision event。
- `app/services/run_coordination.py:270-295` `_insert_decision_event(...)` 发布 `source=state_machine/event_type=decision/phase=decision_tick`。
- `tests/integration/test_agent_events.py:352-402` 覆盖 terminal observer 写入 decision_tick event。

断点：

- `observe_task_terminal_decision_tick(...)` 只记录 decision event，不会调用 `dispatch_authoritative_packet(...)`。
- `_maybe_finalize_run(...)` 在 sibling tasks 全 terminal 时直接把 run 标记 completed/failed，可能早于 L7 自动派发下一阶段。

状态：PASS-PARTIAL

结论：

L6 hook 基本成立，是当前 7 层里最稳的一层。但它只做观察，没有推进下一步。

### L7 Next Decision

目标不变量：

```text
终态观察后：
execute -> dispatch gateway
wait -> 等待
recover -> 恢复策略或问用户
blocked -> 问用户
complete -> 写回总结并完成
```

代码存在：

- `app/services/run_coordination.py:64-181` `evaluate_decision_tick(...)` 能产生 `wait/recover/complete/blocked/execute`。
- `app/services/run_coordination.py:79-100` active tasks 返回 wait。
- `app/services/run_coordination.py:119-134` terminal failed tasks 可返回 recover。
- `app/services/run_coordination.py:136-150` final artifact 可返回 complete。
- `app/services/run_coordination.py:168-181` allowed next action 可返回 execute。
- `app/services/agent_run_state_machine.py:187-191` `recommend_next_action(...)` 从 production stages 推导下一 action。

断点：

- 没有发现 `observe_task_terminal_decision_tick(...)` 或 L7 调用 `dispatch_authoritative_packet(...)` 的代码。
- decision event 存在于 debug/event stream，但不是自动命令。
- 当前“继续下一步”主要靠用户或 continue-step/brain-continue 再触发。
- `_maybe_finalize_run(...)` 可能在所有当前 tasks terminal 后把 run 完成，而不是由 decision tick 的 `execute/complete/recover` 统一裁决。

状态：FAIL-PARTIAL

结论：

这是无法达到 Codex-style 的核心断点。系统能“知道下一步”，但不会在同一个主链里“自己继续做下一步”。

## 4. API And External Provider Tree

### Internal API Tree

```text
/api/agent-runs
-> app.routes.agent_runs.create_run
-> continue_project_brain OR start_video_production

/api/agent-runs/{run_id}/actions/continue-step
-> routing/planner/control intent
-> dispatch_agent_action
-> diagnostics/status OR continue_project_brain OR director_export_preview

/api/projects/{project_id}/brain/continue
-> build_project_brain
-> evaluate_action_gate
-> planning loop OR _dispatch_production_action
-> compatibility packet
-> dispatch_authoritative_packet

/api/projects/{project_id}/production/start
-> create_agent_run
-> compatibility packet
-> dispatch_authoritative_packet
-> video_production_run_task

/api/batch/generate-videos
-> submit_batch_tasks
-> generate_video_task

/api/batch/generate-images
-> submit_batch_tasks
-> generate_image_task

/api/tts/generate
-> submit_single_task
-> generate_tts_task
```

### Tool/Provider Call Tree

```text
A lane:
  build_story_understanding_with_llm
  continue_project_from_brain
  project workspace writeback

B lane:
  diagnostics:
    diagnose_outputs
    diagnose_tasks
    diagnose_provider_writeback
    diagnose_script
    diagnose_keyframe_pool
  answer/status:
    StatusQueryExecutor
    OutputDiagnosticExecutor
    TaskDiagnosticExecutor
  execution bridge:
    continue_project_brain
    director_export_preview

C lane:
  _continue_generate_batch
    -> credit_service.get_price
    -> ensure_run_budget
    -> reserve_credits
    -> INSERT tasks
    -> celery_app.send_task
    -> image/video workers
  _continue_plan_final_edit
    -> final_edit_plans writeback
    -> final-cut route
  video_production_run_task
```

## 5. Root-Cause Findings

### Finding 1: L7 is observational, not executable

Evidence:

- `app/tasks/_shared.py:488-491` calls terminal hooks.
- `app/services/run_coordination.py:219-222` evaluates decision and returns dict.
- `app/services/run_coordination.py:270-295` only writes a decision event.

Impact:

This breaks the Codex-like loop. After one batch finishes, the system can say what should happen next, but it does not dispatch the next action.

Severity: Critical

Required architectural correction:

```text
terminal task
-> observe_task_terminal_decision_tick
-> if decision.status == execute and decision.dispatchable:
     dispatch_authoritative_packet(...)
   elif recover/blocked:
     create pending human instruction or recovery run state
   elif complete:
     writeback summary and complete run
```

### Finding 2: Production dispatch uses compatibility packet, not canonical decision tick

Evidence:

- `app/routes/workbench.py:1415-1496` builds a compatibility `DecisionTickResult`.
- `app/routes/workbench.py:1553-1561` production actions use that packet.
- `app/routes/workbench.py:861-869` production start also uses compatibility packet.

Impact:

The packet has the right shape but not the right authority. It is created from `before` brain signals and hard-coded allowed=true, not from `load_run_facts_from_snapshot -> evaluate_decision_tick`.

Severity: High

Required architectural correction:

```text
all production dispatch
-> load_run_facts_from_snapshot(run_id)
-> evaluate_decision_tick(facts)
-> dispatch_authoritative_packet(packet)
```

Compatibility wrappers should only adapt old callers into the canonical run/facts path, not fabricate the decision.

### Finding 3: Dispatch gateway is not the only production queue

Evidence:

- `app/main.py:179-231` direct video task API queues tasks.
- `app/main.py:234-280` direct image task API queues tasks.
- `app/main.py:283-321` direct TTS task API queues tasks.
- `app/services/task_submission.py:34-117` and `120-175` insert tasks and call Celery.

Impact:

Direct APIs are valid SaaS primitives, but they bypass L1-L4. If UI or agent path uses them for main production, main-chain state will be incomplete.

Severity: High for agent workflow, Medium for platform API

Required architectural correction:

Keep direct APIs as platform tools, but mark them explicitly:

```text
platform/direct-task path:
  allowed for manual SaaS operations
  not allowed for Codex-style agent main run

agent/main-chain path:
  must enter through authoritative run + dispatch gateway
```

### Finding 4: B lane has execution authority beyond diagnostics/control

Evidence:

- `app/services/agent_control_registry.py:4-11` human executable actions include production actions.
- `app/services/agent_action_executor.py:110-134` B lane can call `execute_continue_project` and `execute_final_edit`.
- `app/routes/agent_runs.py:644-659` final edit path can directly call `director_export_preview`.

Impact:

B lane is supposed to be control tower and human interface. Current code lets it trigger production/final edit actions, creating a second command path beside L4.

Severity: High

Required architectural correction:

B lane should output one of:

```text
answer/status
diagnostic evidence
pending confirmation
requested action intent
```

It should not own production execution. Its requested action must be converted into canonical facts/decision packet and pass through L4.

### Finding 5: A lane still owns next_action

Evidence:

- `app/services/project_brain.py:1976-2007` `_decide_phase(...)` maps signals to `next_action`.
- `app/routes/workbench.py:1081-1094` `continue_project_brain` uses `requested_action or current_brain.next_action`.

Impact:

A lane is too close to being the main controller. For Codex-style behavior, A lane should contribute planning/facts/recommendations, but L3 should produce the authoritative command.

Severity: Medium-High

Required architectural correction:

Rename or demote `project_brain.next_action` semantics:

```text
project_brain.recommended_action
-> run_coordination.evaluate_decision_tick
-> authoritative packet.action
```

### Finding 6: Run finalization can bypass L7 complete policy

Evidence:

- `app/tasks/_shared.py:740-778` `_maybe_finalize_run(...)` marks run completed/failed once sibling tasks terminal.
- `app/services/run_coordination.py:136-150` separately has complete decision only when final video artifact exists.

Impact:

A run can become completed just because its current batch tasks finished, even though the next production stage may still be pending.

Severity: High

Required architectural correction:

Completion should be decided by L7 decision policy, not by “all current sibling tasks terminal” alone. `_maybe_finalize_run` should either become a stage observer or defer to `evaluate_decision_tick`.

## 6. Main Chain Gap Map

```text
Current real flow:

User
-> agent_runs OR workbench brain/continue OR production/start
-> project_brain.next_action / requested action
-> compatibility DecisionTickResult
-> dispatch_gateway
-> handler queues tasks
-> task terminal hook
-> decision_tick event written
-> run maybe finalized
-> waits for user/API to trigger next step

Expected Codex-style flow:

User goal
-> one authoritative run
-> unified facts
-> canonical decision packet
-> dispatch gateway
-> lane execution
-> task terminal hook
-> canonical decision packet
-> dispatch gateway or recover/block/complete
-> repeat until final artifact
```

The missing bridge is:

```text
decision_tick.execute
-> dispatch_authoritative_packet
```

The unsafe extra bridges are:

```text
B lane -> continue_project_brain
B lane -> director_export_preview
direct API -> submit_batch_tasks
project_brain.next_action -> compatibility packet
_maybe_finalize_run -> completed/failed
```

## 7. Recommended Fix Order

This report is diagnosis only. If implementing, the safe order should be:

1. Define `MainChainController` or equivalent orchestration service.
2. Make terminal observation call the controller instead of only writing event.
3. Replace compatibility packet in `_dispatch_production_action` with canonical `evaluate_decision_tick`.
4. Restrict B lane to intent/diagnostic output; route all writes through L4.
5. Make `_maybe_finalize_run` defer to L7 complete/recover policy.
6. Mark direct generation APIs as platform-only and keep them out of agent main chain.
7. Add DB-level integration tests for full loop:
   `story -> keyframes -> videos -> final_edit -> complete/recover/block`.

## 8. Implementation Alignment Status

After the alignment work, terminal observation now has an implementation bridge back into the main chain:

```text
terminal task
-> observe_task_terminal_decision_tick
-> main_chain_terminal.continue_main_chain_after_task
-> main_chain_controller.apply_decision_packet
-> dispatch_authoritative_packet OR wait/recover/blocked/complete
```

The remaining compatibility packet path is retained only as a fallback when canonical run facts cannot be loaded. B lane production requests now return action intent and route writes through the project/main-chain path instead of directly owning provider or final-edit execution.

## 9. Final Judgment

文档目标明确，功能树方向正确，API/工具能力也基本齐全。迟迟做不到 Codex-style 的根因是主链没有闭合：

```text
不是不会判断下一步，
而是判断下一步之后没有权威执行循环。
```

因此当前问题主要是架构收口问题，不是单个 provider、prompt、UI 或某个细节 bug。
