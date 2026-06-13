# Main Chain Function Tree And Diagnosis

**Date:** 2026-05-27  
**Purpose:** 展开当前项目的功能树、主链层次、内部 API、外部 API 调用，并判断为什么系统还没有达到 Codex-style 自动处理问题的目标。

## One-Line Verdict

目标是对的，文档方向也基本齐全。当前卡住的主要不是“缺功能”，而是 **权威主链还没有成为唯一命令路径**。

更具体地说：

- 架构问题：主链设计已经写清楚，但代码仍存在多个可执行入口、多个局部决策器、多个恢复路径。
- 细节问题：一些 API/action 已经长出来但没有同步成合同文档；真实 DB 端到端链路仍未验证；部分老链路没有被明确降级为 compatibility-only。
- 所以系统看起来有 Agent Run、Project Brain、任务流、事件流，但还不是 Codex 那种“一个 run 自己持续决策、执行、观察、恢复”的闭环。

## Target Function Tree

```text
ShortDrama AI SaaS
├─ 0. Product Target
│  └─ Codex-style short-drama production agent
│     ├─ user gives a goal
│     ├─ system reads project facts
│     ├─ system decides next step
│     ├─ system dispatches work
│     ├─ system observes result
│     ├─ system recovers or asks human
│     └─ system delivers video artifact
│
├─ 1. Authoritative Main Chain
│  ├─ 1.1 Run Intake
│  ├─ 1.2 Unified Fact Load
│  ├─ 1.3 Decision Packet
│  ├─ 1.4 Dispatch Gateway
│  ├─ 1.5 Lane Execution
│  ├─ 1.6 Terminal Observation
│  ├─ 1.7 Memory / Ledger Writeback
│  └─ 1.8 Next Decision / Complete / Recover / Block
│
├─ 2. Capability Lanes
│  ├─ A Lane: Project Brain / Workspace intelligence
│  ├─ B Lane: Agent Run / DeepSeek / UI control tower
│  └─ C Lane: Production Runner / Celery / Provider / Final Edit
│
├─ 3. SaaS Platform
│  ├─ Auth / user / token
│  ├─ Credits / pricing / spend guard
│  ├─ Rate limit / concurrency
│  ├─ Admin / reports / dead letter / key pool
│  └─ Payment / recharge / orders
│
├─ 4. Production Tools
│  ├─ Prompt and reference resolution
│  ├─ Story / script / director reasoning
│  ├─ Keyframe generation
│  ├─ Video generation
│  ├─ TTS / audio
│  ├─ Final edit plan
│  └─ Preview / final export / delivery
│
└─ 5. User Surfaces
   ├─ Agent Run launch and observation
   ├─ Director workbench / production console
   ├─ Final cut
   ├─ Task pages
   ├─ Admin pages
   └─ Billing / reports / settings
```

## Main Chain Level Map

This is the most important tree. The project should behave like this:

```text
L0 User Goal
└─ "继续生成剩下的视频，完成后自动剪辑"

L1 Authoritative Run
└─ agent_run
   ├─ id
   ├─ project_id
   ├─ user_id
   ├─ mode: step / autopilot / preview
   ├─ budget
   ├─ current_phase
   └─ status

L2 Unified Facts
└─ one factual state, not lane-local facts
   ├─ workspace Markdown
   │  ├─ PROJECT.md
   │  ├─ story/characters.md
   │  ├─ story/episodes.md
   │  ├─ scenes/episode-01-scene-01.md
   │  ├─ memory/decisions.md
   │  ├─ memory/failures.md
   │  └─ memory/constraints.md
   ├─ workspace JSON
   │  └─ shots/episode-01-scene-01.json
   ├─ DB facts
   │  ├─ shot_rows
   │  ├─ assets / refs
   │  ├─ tasks
   │  ├─ credit_transactions
   │  ├─ final_edit_plans
   │  ├─ video_production_runs
   │  └─ agent_events / agent_steps / artifacts
   └─ runtime facts
      ├─ active tasks
      ├─ provider status
      ├─ budget status
      ├─ risks
      └─ pending human decisions

L3 Decision Packet
└─ structured command, not just next_action
   ├─ action
   ├─ selected_lane
   ├─ dispatchable
   ├─ allowed_writes
   ├─ evidence_refs
   ├─ budget
   ├─ risk
   ├─ failure_policy
   ├─ success_criteria
   └─ mission

L4 Dispatch Gateway
└─ the only place production work should be queued
   ├─ validate packet
   ├─ update agent_run
   ├─ publish dispatch event
   ├─ enforce idempotency / budget / write scope
   └─ call one lane handler

L5 Lane Execution
├─ A Lane
│  ├─ generate_story_plan
│  ├─ plan_scene
│  ├─ lock_assets
│  └─ plan_visual_assets
├─ B Lane
│  ├─ status_query
│  ├─ evidence explanation
│  ├─ diagnostics
│  ├─ pending action confirmation
│  └─ human instruction routing
└─ C Lane
   ├─ generate_keyframes
   ├─ generate_videos
   ├─ plan_final_edit
   ├─ export_preview
   └─ export_final

L6 Terminal Observation
└─ every terminal task returns to the same hook
   ├─ publish_complete
   ├─ publish_failed
   ├─ persist task state
   ├─ publish agent_event
   ├─ drain pending instruction
   ├─ observe_task_terminal_decision_tick
   └─ maybe_finalize_run

L7 Next Decision
└─ expected Codex-like behavior
   ├─ continue if safe and budget allows
   ├─ wait if tasks/provider active
   ├─ recover if failed
   ├─ ask human if ambiguous/risky
   └─ complete if final artifact exists
```

## Current Main Chain In Code

```text
Frontend
└─ /director/agent-run
   ├─ createAgentRun(...)
   ├─ getAgentRunSnapshot(...)
   ├─ stream run events
   └─ action buttons

Backend API
├─ POST /api/agent-runs
│  └─ app.routes.agent_runs.create_run
│     └─ calls continue_project_brain(...)
│
├─ POST /api/agent-runs/{run_id}/actions/continue-step
│  └─ routing / planner / semantic controller / diagnostics
│     └─ may call continue_project_brain(...)
│
└─ POST /api/projects/{project_id}/brain/continue
   └─ app.routes.workbench.continue_project_brain
      ├─ create_agent_run(...)
      ├─ build_project_brain(...)
      ├─ planning loop for A-lane planning actions
      ├─ compatibility DecisionTickResult
      ├─ dispatch_authoritative_packet(...)
      └─ compatibility handlers
         ├─ _continue_plan_visual_assets
         ├─ _continue_generate_keyframes
         ├─ _continue_generate_videos
         └─ _continue_plan_final_edit

Dispatch
└─ app.services.run_dispatch_gateway.dispatch_authoritative_packet
   ├─ validate packet
   ├─ update_agent_run(status='dispatching')
   ├─ publish_agent_event(source='dispatch_gateway')
   └─ call handler

Task Execution
├─ app.services.task_submission.submit_batch_tasks
│  ├─ reserve credits
│  ├─ INSERT tasks(status='queued')
│  └─ celery_app.send_task(...)
├─ app.tasks.image_tasks.generate_image_task
├─ app.tasks.video_tasks.generate_video_task
├─ app.tasks.tts_tasks.generate_tts_task
└─ app.tasks.director_tasks.*

Terminal Hook
└─ app.tasks._shared
   ├─ publish_complete
   ├─ publish_failed
   ├─ _persist_and_publish
   ├─ _publish_agent_task_event
   ├─ _drain_pending_instruction
   ├─ _observe_run_coordination_after_task
   │  └─ run_coordination.observe_task_terminal_decision_tick
   └─ _maybe_finalize_run
```

## API Function Tree

### Main Agent APIs

```text
/api/agent-runs
├─ POST /
│  ├─ creates / starts an agent run
│  └─ currently delegates into project brain continue
├─ GET /{run_id}/snapshot
│  └─ full observable run state for UI
├─ GET /{run_id}/events
│  └─ event history
├─ GET /{run_id}/stream
│  └─ SSE stream for execution events and LLM chunks
└─ POST /{run_id}/actions/*
   ├─ retry-failed
   ├─ change-provider
   ├─ continue-step
   ├─ export-partial
   ├─ keyframe-batch/preview
   ├─ generate-keyframe-batch
   ├─ select-keyframe-candidate
   ├─ generate-video-from-pool
   └─ cancel
```

Diagnosis:

- These are the right product surface for Codex-like interaction.
- But several action endpoints are still direct specialized operations, not obviously routed through the same dispatch packet/gateway contract.

### Project / Workbench APIs

```text
/api/projects
├─ POST /
├─ GET /
├─ GET /{project_id}
├─ GET /{project_id}/workspace
├─ POST /{project_id}/workspace/init
├─ POST /{project_id}/workspace/write
├─ GET /{project_id}/brain
├─ POST /{project_id}/brain/continue
├─ GET /{project_id}/agent-events
├─ GET /{project_id}/agent-runs
├─ GET /{project_id}/shot-rows
├─ GET /{project_id}/shot-rows/{shot_index}
├─ PUT /{project_id}/shot-rows/{shot_index}
├─ prompt revision / safe rewrite endpoints
├─ asset endpoints
├─ visual-plan endpoints
├─ final-edit-plan endpoints
└─ production-run route
```

Diagnosis:

- This is where A lane and older workbench production behavior live.
- `brain/continue` now routes production actions through the gateway.
- The production-run route is explicitly called out in handoff docs as a remaining boundary risk.

### Direct Task APIs

```text
/api/batch/generate-images
└─ direct batch image generation

/api/batch/generate-videos
└─ direct batch video generation

/api/tts/generate
└─ direct TTS generation

/api/tasks
├─ GET /
├─ GET /{task_id}
└─ POST /{task_id}/cancel

/ws/tasks
└─ task progress websocket
```

Diagnosis:

- These APIs are valid SaaS/task APIs.
- For the Codex-like agent, they are dangerous if treated as peer orchestration paths.
- They should be capability APIs behind main-chain missions, or explicitly marked manual/legacy.

### Director APIs

```text
/api/director
├─ metadata
│  ├─ /modes
│  ├─ /final-cut-recipes
│  ├─ /presets
│  ├─ /evaluation-standard
│  ├─ /feedback-templates
│  └─ /final-cut/*
├─ planning / reasoning
│  ├─ /chat
│  ├─ /script
│  ├─ /prepare
│  ├─ /produce
│  ├─ /reference-images
│  ├─ /diagnose-task
│  ├─ /recommend-mode
│  ├─ /explain-decision
│  ├─ /evaluate-run
│  └─ /rework-suggest
├─ memory / evolution
│  ├─ /{project_id}/project-memory
│  ├─ /{project_id}/reference-bindings
│  ├─ /evolution/*
│  └─ /case/context
└─ media / final artifacts
   ├─ proxy media
   ├─ final video response
   ├─ export preview
   └─ export final
```

Diagnosis:

- This is a large capability surface.
- The docs describe the strategy, but not every director route has a current action contract.
- If these routes are invoked from UI as independent decisions, they weaken the main chain.

### SaaS Platform APIs

```text
/api/auth
├─ register
├─ login
├─ refresh
├─ logout
└─ me

/api/credits
├─ balance
├─ transactions
├─ pricing
└─ spend limit

/api/payment
├─ plans
├─ create-order
├─ callback
├─ mock-success
└─ orders

/api/reports
├─ usage
├─ usage/summary
└─ credits/history

/api/admin
├─ overview
├─ users
├─ tasks
├─ task stats
├─ credits / pricing
├─ revenue
├─ provider costs
├─ volc billing
├─ dead-letter
├─ key-pool
├─ system
└─ rate-limits
```

Diagnosis:

- These are platform support systems. They do not prevent Codex-like behavior.
- They become a problem only when cost/rate/task constraints are not consistently enforced at the dispatch gateway.

## External API / Provider Call Tree

```text
Provider Gateway
└─ app.services.key_pool
   ├─ acquire(service)
   ├─ release(key_name)
   └─ report_error(key_name, error)

Text / Reasoning
├─ Doubao
│  ├─ director chat/script/final-cut AI
│  ├─ prompt and planning support
│  └─ used by A/B lane reasoning paths
└─ DeepSeek / planner-style calls
   ├─ human instruction routing
   ├─ evidence composing
   └─ B lane explanation/control

Image
└─ Seedream
   ├─ generate keyframes
   ├─ generate reference images
   ├─ update selected_image
   └─ create image candidate/review evidence

Video
├─ Seedance
│  ├─ image-to-video
│  ├─ provider polling/wait
│  └─ selected_video writeback
└─ Kling
   ├─ alternate video provider
   └─ optional TTS/video path depending payload

Storage / Delivery
├─ object storage / OSS / TOS-style persistence
│  ├─ persist_result_to_oss
│  ├─ media proxy
│  └─ signed or public media URLs
└─ final video storage
   ├─ final_video_blobs
   ├─ final_video_assets
   └─ delivery reports

Infrastructure
├─ Redis
│  ├─ Celery broker/result backend
│  ├─ task progress pub/sub
│  ├─ project event pub/sub
│  ├─ rate limit
│  └─ key pool load/cooldown/rpm counters
├─ PostgreSQL
│  ├─ users
│  ├─ credit accounts/transactions
│  ├─ tasks/dead letters
│  ├─ workbench tables
│  ├─ agent runtime tables
│  ├─ final edit/final video tables
│  └─ provider cost ledger
└─ FFmpeg / local media tools
   ├─ preview export
   ├─ final export
   └─ final delivery checks
```

## Where The Architecture Diverges From The Goal

### 1. There Is A Main Chain, But It Is Not Yet The Only Command Path

Target:

```text
all production work -> decision packet -> dispatch gateway -> lane execution
```

Current:

```text
agent-runs actions
projects brain/continue
projects production-run
director produce/export routes
direct batch generation routes
task pages
```

Some paths are already wrapped. Some still look like peer routes.

This is an architecture issue.

### 2. Decision Tick Is Still Mostly Observational

Target:

```text
terminal task
-> observe
-> decide
-> if allowed, continue
```

Current:

```text
terminal task
-> observe_task_terminal_decision_tick
-> persist agent_event decision
-> maybe finalize run
```

The hook records the next decision, but the documented Phase 1 handoff still says real DB end-to-end validation is pending. It also does not yet prove a fully autonomous next-dispatch loop.

This is an architecture issue with verification risk.

### 3. A Lane Still Produces `next_action`; Main Chain Wraps It Later

Target:

```text
Unified facts -> authoritative decision packet
```

Current:

```text
Project Brain -> phase + next_action
Workbench -> compatibility DecisionTickResult packet
Gateway -> dispatch
```

This is acceptable as a transition, but it means the real source of command truth is split between `project_brain`, `workbench`, `run_coordination`, and `agent_run_state_machine`.

This is an architecture issue.

### 4. B Lane Has Too Many Control Abilities Near Execution

B lane should explain, diagnose, ask, and route. It should not become a second orchestrator.

Current B lane has:

- planner routing
- semantic controller
- diagnostic recommendations
- pending actions
- direct calls to continue/export helpers
- keyframe pool actions
- video-from-pool action

Those are useful, but every one needs a clear ceiling:

```text
recommend -> decision packet -> dispatch gateway
```

not:

```text
recommend -> route-specific execution branch
```

This is an architecture issue expressed through implementation details.

### 5. API Documentation Lags Behind The Actual Action Surface

Examples:

- `saas_interface_protocol.md` still references older `crud.py` / `job_registry.py` assumptions.
- Agent Run granular action endpoints are not fully documented as a contract.
- `app/routes/director.py` contains many route capabilities not summarized in one current Markdown contract.

This is a documentation/detail issue, but it causes architectural drift because undocumented routes become undocumented authority.

### 6. Compatibility Paths Are Not Marked Strongly Enough

The docs say “preserve useful lanes, demote duplicated control authority.” The code still contains many routes that can be read as product entry points.

The missing classification is:

```text
authoritative
compatibility-only
manual tool
admin/operator
legacy
```

Without that classification, developers keep adding local fixes to whichever endpoint is nearby.

This is an architecture governance issue.

## Is The Problem Architecture Or Details?

It is both, but not equally.

```text
Architecture problem: 70%
Detail/documentation/verification problem: 30%
```

The architecture target is correct. The implementation architecture is only partially converged.

The core architectural gap:

```text
The system has an approved main chain,
but not all commands are forced through it.
```

The core detail gap:

```text
New endpoints/actions/tests/docs are not consistently updated against that main chain contract.
```

## What Must Be True To Feel Like Codex

For the product to feel like Codex, these invariants must hold:

1. There is exactly one authoritative run context for a user goal.
2. Every production action has a decision packet.
3. Every dispatch passes the gateway.
4. Every expensive action passes budget/cost/rate gates at dispatch time.
5. Every worker terminal state re-enters the same observation hook.
6. Observation can trigger the next decision, not only log it.
7. B lane can explain/recommend, but cannot bypass the command chain.
8. A lane can synthesize facts, but cannot be the final dispatcher.
9. C lane can execute, but cannot choose the global next step.
10. UI buttons map to run actions, not independent production tools.

## Recommended Repair Tree

```text
Repair Plan
├─ Phase 1: Declare Authority
│  ├─ classify every API as authoritative / compatibility / manual / admin / legacy
│  ├─ update docs to reflect that classification
│  └─ block new product work that bypasses the gateway
│
├─ Phase 2: Close Main Chain E2E
│  ├─ restore TEST_DATABASE_URL
│  ├─ prove POST /api/agent-runs -> task -> terminal hook -> decision event
│  ├─ prove terminal decision can safely choose next state
│  └─ document the actual verified path
│
├─ Phase 3: Route All Production Actions Through Gateway
│  ├─ agent-run retry/change-provider/continue/export actions
│  ├─ keyframe batch actions
│  ├─ video-from-pool action
│  ├─ production-run route
│  └─ director produce/export if used as product-level commands
│
├─ Phase 4: Turn Observation Into A Loop
│  ├─ wait
│  ├─ continue
│  ├─ recover
│  ├─ ask human
│  └─ complete
│
└─ Phase 5: Collapse UI Around Agent Run
   ├─ primary command surface: /director/agent-run
   ├─ workbench/final-cut become expert panels
   ├─ task pages become observability/admin surfaces
   └─ manual generation buttons become capability tools, not the product center
```

## Final Diagnosis

The documents do match the final goal. The strongest documents are already saying the right thing:

```text
goal
-> authoritative run
-> unified facts
-> decision packet
-> dispatch gateway
-> lane execution
-> terminal observation
-> memory writeback
-> next decision
```

The reason the system is not yet Codex-like is that this chain is not yet enforced everywhere.

The next useful work is not another feature. It is to make the function tree enforceable:

- one authoritative API surface,
- one dispatch gateway,
- one terminal observation loop,
- explicit demotion of side paths,
- current API contract docs for every action that still remains.

## Implementation Alignment Update

The code now has the missing terminal loop bridge:

```text
Terminal Hook
-> observe_task_terminal_decision_tick
-> main_chain_controller.apply_decision_packet
-> dispatch_authoritative_packet OR wait/recover/blocked/complete
```

B lane production actions now return action intent and route writes through the project/main-chain path. Direct generation APIs are documented as platform-only direct task paths.

The next implementation phase introduces enforced lane boundaries:

```text
B lane -> recommendation/request only
C lane -> assigned execution only
Gateway -> capability whitelist + decision mailbox audit
L7 -> active observation + writeback verification + feedback
```

The foundation implementation maps to the Claude/Opus-style runtime as:

```text
goal
-> coordinator
-> decision mailbox with rationale/evidence
-> gateway lane and capability enforcement
-> assigned worker/provider execution
-> writeback and artifact observation
-> safety/reflection decision
-> user/expert/debug feedback
```
