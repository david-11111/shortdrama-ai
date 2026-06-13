# Agent Runtime Claude/Opus Alignment Design

Date: 2026-05-27

## Purpose

The project target is not only a task pipeline. It must behave like a coordinated agent runtime similar to Claude/Opus: understand the user's goal, build a plan, call tools and APIs through a controlled path, observe results, revise the next step, explain progress, and close only when the outcome is genuinely complete.

This design aligns two surfaces at the same time:

1. Internal coordination: one authoritative loop controls planning, dispatch, observation, recovery, and completion.
2. External feedback: every important step is reported to the user with clear state, evidence, next action, and risk.

The intended loop is:

```text
User Goal
-> Goal Intake
-> Coordinator
-> Planner
-> Unified State Reader
-> Decision Maker
-> Tool/API Dispatcher
-> Observer
-> Reflector
-> Feedback Writer
-> repeat until complete / blocked / asks human
```

Unlike Claude Code's coordinator-worker pattern, this runtime cannot rely on a single passive mailbox-style completion signal. Short-drama production has long-running provider tasks, DB writebacks, credits, rate limits, webhooks, user interruptions, and final artifact verification. L7 therefore must be an active observation, reflection, and feedback layer.

## Current Diagnosis

The existing main-chain documents already define the correct target:

```text
goal
-> agent_run
-> unified facts
-> DecisionTickResult
-> dispatch gateway
-> lane handler
-> terminal observation
-> next decision
```

Recent implementation work added the missing terminal bridge:

```text
terminal task
-> observe_task_terminal_decision_tick
-> main_chain_terminal.continue_main_chain_after_task
-> main_chain_controller.apply_decision_packet
-> dispatch_authoritative_packet OR wait/recover/blocked/complete
```

That is necessary but not sufficient. The system still needs an agent-runtime contract that makes the coordinator, planner, observation, reflection, and user feedback explicit. Without that, the system can execute tasks, but it will still not feel like Claude/Opus because the reasoning loop and feedback protocol are not first-class.

## Design Principle

Every autonomous production step must answer five questions before and after execution:

```text
What is the current goal?
What facts prove the current state?
What is the next step and why?
Which tool/API is allowed to act?
What will the user see as progress, risk, or completion?
```

No lane may bypass this loop:

- A lane can plan and synthesize project facts, but cannot be the final dispatcher.
- B lane can explain, diagnose, route user intent, and request an action, but cannot queue production work directly.
- C lane can execute provider/final-edit work, but cannot choose the global next step.

The most important Claude Code lesson is forced separation. The runtime should not merely ask each lane to behave; it should remove or block capabilities that do not belong to that lane.

Forced layering invariants:

```text
B lane: recommend / diagnose / explain / request only
C lane: execute assigned mission only
Coordinator: decide / route / pause / escalate only through packets
Gateway: enforce permissions before any production write
Worker: see the assigned mission and required inputs, not global authority
```

This is "tool deprivation" as architecture: clarity comes from making bypasses impossible, not from relying on convention.

Reasoning and execution must also be physically separated. Planning and diagnostic workers may produce decision rationale, evidence summaries, confidence, and model/tool metadata. Execution workers should receive only the final mission, allowed tools, expected writes, timeout policy, and success criteria. The system must not persist hidden chain-of-thought as a product feature; it should persist auditable rationale and structured evidence.

## 7-Layer Target Runtime

### L1 Goal Intake

Purpose: capture the user's actual production goal and constraints.

Inputs:

- User instruction
- Project ID
- Run mode: step, autopilot, preview, repair
- Budget and credit limits
- Risk tolerance
- Existing project workspace and history

Outputs:

- `goal_statement`
- `run_mode`
- `constraints`
- `expected_artifact`
- `human_feedback_policy`

Existing anchors:

- `POST /api/agent-runs`
- `POST /api/agent-runs/{run_id}/actions/continue-step`
- `POST /api/projects/{project_id}/brain/continue`
- `agent_runs.goal`
- `agent_runs.meta`

Required change:

All user-facing autonomous work should enter or resume one authoritative run context. Compatibility routes may exist, but they must adapt into this contract.

### L2 Coordinator

Purpose: act as the only global controller for a run.

Responsibilities:

- Own the run lifecycle.
- Decide whether the system is planning, dispatching, waiting, recovering, asking the user, or completing.
- Prevent lane-local code from acting as a competing orchestrator.
- Attach every decision and tool call to the same run.

Existing anchors:

- `app/services/main_chain_controller.py`
- `app/services/main_chain_terminal.py`
- `app/services/run_coordination.py`
- `app/services/run_dispatch_gateway.py`

Required change:

Expand `main_chain_controller` from "apply one decision packet" into a runtime coordinator with explicit phases:

```text
intake
plan
read_state
decide
dispatch
observe
reflect
feedback
complete
```

### L3 Planner

Purpose: produce an actionable stage plan without directly dispatching production work.

Planner output should include:

- Current stage
- Remaining stages
- Success criteria
- Tool/API candidates
- Required facts
- Risks and blockers
- Human confirmation requirements

Existing anchors:

- `app/services/project_brain.py`
- `app/services/agent_semantic_controller.py`
- `app/services/agent_control_registry.py`
- `app/services/llm_planner.py`
- `app/routes/agent_runs.py` routing helpers

Required change:

Rename the authority of planner outputs conceptually:

```text
project_brain.next_action -> project_brain.recommended_action
semantic_controller.action -> requested_action_intent
diagnostic.recommended_action -> recommended_action_intent
```

The coordinator converts recommendations into authoritative decision packets.

### L4 Unified State Reader

Purpose: read one factual state for all decisions.

State must include:

- `agent_runs`
- `agent_events`
- `agent_steps`
- `agent_artifacts`
- `tasks`
- `shot_rows`
- `credit_transactions`
- `final_edit_plans`
- `video_production_runs`
- workspace Markdown/JSON
- provider/task status
- pending human decisions

Existing anchors:

- `app/services/agent_run_snapshot.py`
- `app/services/run_coordination.py::load_run_facts_from_snapshot`
- `app/services/run_coordination.py::UnifiedRunFacts`
- `app/services/project_workspace.py`

Required change:

All autonomous decision paths should load facts through the same snapshot/facts path before producing a command. Workbench/project-brain facts may enrich the snapshot, but should not be a separate source of command truth.

### L5 Decision Packet

Purpose: turn facts and plan into a structured command.

Decision statuses:

- `execute`: safe to call one tool/API through gateway
- `wait`: active work or provider wait; no new dispatch
- `recover`: failure detected; choose recovery or ask user
- `blocked`: missing facts, budget, ambiguity, or policy block
- `ask_human`: user confirmation/input required
- `complete`: final success criteria satisfied

Current packet anchor:

- `app/services/run_coordination.py::DecisionTickResult`

Required additions:

```text
goal_summary
plan_stage
tool_name
tool_intent
user_visible_summary
next_user_message
observation_policy
reflection_policy
human_question
closure_criteria
```

The existing packet fields remain important:

```text
action
stage_id
selected_lane
dispatchable
allowed
allowed_writes
evidence
evidence_refs
budget
risk
failure_policy
success_criteria
mission
```

Decision packets should be persisted through a mailbox-style state machine:

```text
pending: accepted but not executing
in_progress: one active packet owned by the gateway/worker
completed: execution observed and reflected
recovered: failure handled by a recovery strategy
rejected: invalid or unauthorized packet
cancelled: stopped by user/coordinator policy
```

Only the coordinator may submit authoritative packets. B lane and planner outputs enter as `requested_action_intent` or `recommended_action`, then the coordinator converts or rejects them.

### Decision Mailbox

Purpose: make decision state durable and auditable.

The decision mailbox is the concrete state machine behind the coordinator-worker model:

```text
empty/pending -> coordinator submits packet
pending -> gateway claims next executable packet
in_progress -> worker/provider runs assigned mission
in_progress -> observer records progress/heartbeat/control signals
completed/recovered/cancelled -> reflector closes or emits next packet
```

Decision mailbox records should be immutable events plus current indexes, not mutable hidden state only. The system can store them in dedicated tables or in `agent_events.meta` during transition, but the contract should be the same.

Required fields:

```text
decision_id
run_id
parent_decision_id
status
packet
claimed_by
claimed_at
completed_at
result_ref
observation_refs
recovery_strategy
idempotency_key
decision_rationale
thinking_artifacts
```

`decision_rationale` is a concise, user-safe and developer-safe explanation of why the recommendation was made. It is not hidden chain-of-thought. `thinking_artifacts` stores structured metadata and evidence, for example model name, prompt class, token count, diagnostic tool name, cited event IDs, and confidence score.

### L6 Tool/API Dispatch

Purpose: enforce one controlled place for tool/API execution.

Every autonomous production call must pass:

```text
Decision Packet
-> dispatch_authoritative_packet
-> lane handler
-> tool/API call
-> task/event/artifact writeback
```

Existing anchors:

- `app/services/run_dispatch_gateway.py`
- `app/services/main_chain_handlers.py`
- `app/routes/workbench.py` production handlers
- `app/services/task_submission.py`
- `app/tasks/image_tasks.py`
- `app/tasks/video_tasks.py`
- `app/tasks/director_tasks.py`

Required change:

The gateway must become the enforcement point for:

- idempotency
- budget envelope
- allowed write scope
- lane ownership
- event publication
- user-visible dispatch feedback

Direct SaaS task APIs may remain platform/manual paths, but they must not be used by the autonomous agent run.

### Capability Whitelist

Purpose: physically enforce lane boundaries at the gateway.

Each lane has an allowlist and an explicit forbidden set:

```text
planning_b_lane:
  allowed: analyze, recommend, diagnose, suggest, draft_feedback
  forbidden: execute, write_db, call_provider, spend_credits, mark_complete

execution_c_lane:
  allowed: execute_assigned_mission, write_expected_outputs, call_provider, report_progress
  forbidden: change_goal, change_plan, skip_stage, override_budget, choose_next_global_action

coordinator:
  allowed: decide, route, pause, escalate, ask_human, complete
  forbidden: direct provider call, direct unscoped DB write, bypass_gateway

learning_l8:
  allowed: advise, rank_strategies, suggest_timeout, summarize_history
  forbidden: dispatch, write_run_status, spend_credits, override_decision
```

Gateway enforcement:

```text
packet.selected_lane
-> capability check
-> runtime/tool/provider version check
-> allowed_writes check
-> budget/rate/idempotency check
-> dispatch
```

If the action is not allowed for the lane, the gateway must reject it with a `rejected` decision mailbox status.

Capability requirements should be versioned, but not hard-coded to a single model brand. Requirements describe the runtime capability needed by the action:

```text
generate_videos:
  required_features: video_generation, provider_status_observation, selected_video_writeback
  provider_capabilities: seedance_image_to_video OR kling_image_to_video
  max_concurrent: provider/rate-limit dependent

plan_final_edit:
  required_features: scene_analysis, selected_video_read, final_edit_plan_writeback

diagnose_tasks:
  required_features: task_snapshot_read, event_read
```

For LLM workers, model/version requirements may apply to reasoning tasks. For provider execution, the requirement should reference provider/tool capability, not the reasoning model that recommended the action.

Capability requirement contract:

```python
CAPABILITY_REQUIREMENTS = {
    "generate_videos": {
        "capability_version": "2026-05-27.v1",
        "required_features": [
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        "provider_capabilities_any": [
            "seedance_image_to_video",
            "kling_image_to_video",
        ],
        "max_concurrent": 2,
        "rate_limit_per_hour": 10,
    },
    "plan_final_edit": {
        "capability_version": "2026-05-27.v1",
        "required_features": [
            "scene_analysis",
            "selected_video_read",
            "final_edit_plan_writeback",
        ],
    },
}
```

The gateway must compare the packet action against the current runtime context:

```text
runtime_features
provider_capabilities
capability_versions
model_features for reasoning-only actions
budget/rate/concurrency limits
```

If any required runtime/tool/provider feature is absent, dispatch is rejected before handler execution and a mailbox rejection event records the exact missing requirement.

### Durable Worker Mailbox Protocol

The "mailbox" is not email. It is a durable asynchronous communication contract between the coordinator and workers. It preserves Claude Code's useful properties:

- auditable commands and results
- asynchronous decoupling
- restart/recovery after worker crash
- atomic worker instructions

But the project must not inherit Claude Code's passive limitations. The mailbox is a persistence and communication layer, not the only observation mechanism.

Recommended mailbox channels:

```text
inbox: coordinator -> worker command packets
outbox: worker -> coordinator result packets
status_updates: worker/provider -> progress and heartbeat updates
control_channel: user/coordinator -> pause/cancel/priority/change requests
audit_log: immutable command/result/control history
```

Worker categories:

```text
reasoning workers:
  DeepSeek
  Doubao
  Use mailbox for async reasoning, diagnosis, planning, prompt work, and feedback drafting.

production provider workers:
  Seedream
  Seedance
  Kling
  FFmpeg/export
  Use mailbox/job envelopes for audit and idempotency, but require active observation.
```

Worker sandbox rule:

```text
reasoning worker: broad reasoning tools, no production authority
production worker: provider tools for one assigned mission, no global plan authority
diagnostic worker: read/diagnose tools, no write authority unless explicitly granted repair_writeback
export worker: final media tools for assigned artifact, no story/plan authority
```

A worker should receive the smallest useful context:

```text
mission
input_refs
allowed_tools
expected_writes
success_criteria
timeout_policy
control_policy
```

It should not receive the authority to alter global goals, skip stages, or consume budget outside the decision packet.

DeepSeek and Doubao should return recommendations or artifacts, not dispatch authority:

```text
DeepSeek mailbox result -> diagnosis / recovery suggestion / requested_action_intent
Doubao mailbox result -> script / director plan / prompt / creative recommendation
Coordinator -> canonical decision packet -> gateway
```

Seedream and Seedance require a stronger contract because they are long-running provider execution paths:

```text
Coordinator
-> Decision Packet
-> Dispatch Gateway
-> Provider job envelope in mailbox/audit log
-> Celery/provider task
-> active observer checks progress, provider status, user controls, timeout, and DB writeback
-> result is reflected back into L7
```

Provider mailbox messages must include:

```json
{
  "message_id": "msg-id",
  "run_id": "run-id",
  "task_id": "task-id",
  "worker": "seedance",
  "type": "command",
  "action": "generate_video",
  "idempotency_key": "run-id:generate_videos:shot-1",
  "expected_writes": [
    {"table": "shot_rows", "field": "selected_video", "shot_index": 1}
  ],
  "control_policy": {
    "cancelable": true,
    "pauseable": false,
    "priority": "normal"
  },
  "timeout_policy": {
    "type": "dynamic",
    "baseline_seconds": 600
  }
}
```

Worker status updates should be durable and user-visible at the right level:

```json
{
  "run_id": "run-id",
  "task_id": "task-id",
  "worker": "seedream",
  "type": "status_update",
  "progress": 45,
  "stage": "provider_waiting",
  "eta_seconds": 120,
  "heartbeat_at": "2026-05-27T10:02:00Z"
}
```

Control messages should not mutate provider state directly. They are inputs to the coordinator:

```text
user cancel/pause/change priority
-> control_channel message
-> coordinator observes control signal
-> decision packet: blocked/cancel/reprioritize/recover
-> gateway or task-control service applies the allowed action
```

### L7 Observe, Reflect, Feedback

Purpose: close the Claude/Opus-style loop.

Observation must be multi-source, not a single task-completion listener.

- Task completed or failed
- Provider returned artifact
- DB writeback happened or failed
- User responded
- Budget/rate/provider changed
- Provider webhook arrived
- System resource or queue health changed
- Watchdog detected no progress

Observation sources:

```text
task_status: tasks.status/progress/error/result
writeback_status: shot_rows/final_edit_plans/final_video_assets expected writes
provider_status: webhook/polling/deferred provider state
system_status: Redis/Celery/DB/key-pool/rate-limit health
user_status: pending instruction, cancel, human answer, new goal
mailbox_status: inbox/outbox/status_updates/control_channel/audit_log
```

Required observer behavior:

```text
collect signals
normalize signal shape
prioritize by severity and actionability
dedupe repeated signals
attach evidence_refs
return observation bundle to reflector
```

Active observation must compensate for passive mailbox limitations:

```text
heartbeat check: detect worker/provider silence
progress check: publish partial progress instead of 0/100 only
control check: detect user pause/cancel/priority changes while work is running
timeout check: use task/provider-specific timeout policy
writeback check: verify the provider result changed project state
```

The most important added check is writeback verification. A provider task can finish successfully while DB writeback fails. That must be detected as a first-class L7 signal:

```text
task done + expected selected_image missing -> WRITEBACK_FAILED
task done + expected selected_video missing -> WRITEBACK_FAILED
final export done + final_video_asset missing -> WRITEBACK_FAILED
```

Observation must also verify multi-artifact completion. A production task is not complete just because one URL exists. For example:

```text
image_gen expected artifacts:
  selected_image
  image candidate metadata
  provider/writeback event

video_gen expected artifacts:
  selected_video
  video variant metadata
  provider/writeback event
  optional thumbnail when provider returns one

final_export expected artifacts:
  final video asset
  delivery metadata
  final task/result link
```

Missing required artifacts produce `MISSING_ARTIFACT` or `WRITEBACK_FAILED` observation signals. Optional artifacts should not block completion unless the decision packet's success criteria mark them required.

Artifact contract:

```python
@dataclass(frozen=True)
class ArtifactRef:
    artifact_type: str
    ref: str
    required: bool = True
    checksum: str = ""
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExpectedArtifact:
    artifact_type: str
    write_target: dict[str, Any]
    required: bool = True
    source: str = "provider_result"
```

Expected artifact examples:

```text
image_gen:
  required: selected_image, image_candidate_metadata, provider_writeback_event

video_gen:
  required: selected_video, video_variant_metadata, provider_writeback_event
  optional: thumbnail

final_export:
  required: final_video_asset, delivery_metadata, final_task_result_link
```

Verification rules:

```text
expected artifact exists in provider result but not DB -> WRITEBACK_FAILED
required artifact absent from provider result and DB -> MISSING_ARTIFACT
optional artifact absent -> expert/debug notice only
artifact present but checksum/size invalid -> ARTIFACT_INVALID
```

Reflection:

- Did this satisfy the stage success criteria?
- Is the next step safe?
- Should the system continue, wait, recover, ask user, or complete?
- What evidence should be shown to the user?

Reflection should follow a three-tier framework:

```text
Tier 1: fast path
  Condition: stage success criteria are satisfied and next step is safe.
  Output: execute next stage / complete.

Tier 2: recovery path
  Condition: failure is known and recoverable.
  Output: recover with explicit strategy.

Tier 3: complex analysis path
  Condition: mixed signals, repeated failures, budget risk, ambiguity, or conflicting facts.
  Output: deeper analysis, ask_human, blocked, or conservative recovery.
```

Recovery strategies:

```text
retry: retry same provider/action within attempt budget
degrade: lower quality/cost or use cheaper provider
reroute: switch provider or route around saturated provider
bypass: skip optional step when closure criteria still allow it
split: divide a large batch into smaller tasks
repair_writeback: re-run writeback without re-calling provider
human: ask user for confirmation or direction
```

Feedback:

Every major transition should produce a normalized user-facing event:

```text
status: planning | executing | observing | waiting | recovering | asking | completed | blocked
summary: short natural-language update
evidence: concrete facts/artifacts/tasks
next_step: what the agent will do next
risk: cost/provider/quality/blocker if any
requires_user: true/false
```

Feedback must be adaptive by audience:

```text
end_user:
  headline
  progress
  ETA when available
  next milestone
  call to action if user input is needed

expert:
  stage
  evidence_refs
  constraints or gates
  provider/task details
  recovery strategy

debug:
  raw decision packet
  raw observation signals
  raw provider payloads
  stack traces or compatibility details
```

Debug feedback must not expose hidden reasoning or chain-of-thought. It should expose structured signals, inputs, outputs, packet fields, and policy decisions.

Watchdog behavior:

```text
if no progress after dynamic timeout:
  emit NO_PROGRESS signal
  transition to wait/recover/blocked depending on provider and queue state
```

Timeouts should be dynamic by task type and provider history, not a single fixed timeout.

Safety circuit breaker:

```text
dangerous action -> blocked + human/admin review
critical risk -> blocked + escalation event
high risk -> ask_human unless prior approval exists
medium risk -> publish expert warning and continue only if allowed
low risk -> continue
```

Dangerous actions include destructive or authority-escalating operations such as deleting projects, purging data, bypassing budget, overriding production policy, or escalating privileges. Normal provider generation is not dangerous by default, but can become high risk when budget, repeated failures, user cancellation, or policy violations are present.

Existing anchors:

- `app/tasks/_shared.py`
- `app/services/run_coordination.py::observe_task_terminal_decision_tick`
- `app/services/main_chain_terminal.py`
- `app/services/agent_runtime.py::publish_agent_event`
- `GET /api/agent-runs/{run_id}/events`
- `GET /api/agent-runs/{run_id}/stream`
- `GET /api/agent-runs/{run_id}/snapshot`

Required change:

Observation must not only write debug decisions. It must write user-understandable progress and feed the next coordinator step.

### L8 Runtime Learning Plane

Purpose: accumulate operational experience across runs without becoming a second coordinator.

L8 is not part of the command authority chain. It can recommend optimizations, but it cannot dispatch tasks or override L2/L5 decisions directly.

Learning inputs:

- Goals
- Plans
- Decision history
- Observation signals
- Recovery attempts
- Provider performance
- Cost and duration
- Final outcome
- User interventions

Learning outputs:

- Suggested timeout baselines
- Provider performance profile
- Recovery strategy ranking
- Similar-run examples
- Bottleneck warnings
- Planning hints

Runtime episode shape:

```json
{
  "goal": "Produce missing videos and final cut",
  "plan": [],
  "decisions": [],
  "observations": [],
  "recoveries": [],
  "provider_metrics": {},
  "bottlenecks": [],
  "outcome": "completed",
  "success": true
}
```

Allowed use:

```text
Coordinator asks L8 for hints.
L8 returns advisory evidence.
Coordinator still produces the authoritative decision packet.
Gateway still enforces dispatch.
```

Disallowed use:

```text
L8 directly queues tasks.
L8 directly changes run status.
L8 bypasses budget/rate/write-scope policy.
L8 hides provider failures from user/expert feedback.
```

## Claude/Opus-Style Feedback Contract

The user should see updates in a consistent sequence:

```text
1. I understood the goal.
2. I checked the current project state.
3. I found the next missing/unsafe/complete stage.
4. I am calling this tool/API for this reason.
5. The tool/API returned this result.
6. I verified whether the result satisfies the goal.
7. I will continue / wait / recover / ask you / complete.
```

The system should not expose raw internal noise as the primary message. Raw logs remain available as debug events.

Recommended event levels:

```text
user: concise progress and decisions
expert: diagnostics, risk, provider details
debug: raw packet, raw payload, stack traces, compatibility details
```

Recommended event kinds:

```text
goal_received
plan_created
state_observed
decision_made
tool_call
tool_result
writeback
reflection
user_question
completion
recovery
blocked
watchdog_timeout
writeback_failed
recovery_selected
learning_hint
```

## API And Tool Ownership

### Authoritative Agent APIs

These are allowed to start or resume the coordinated loop:

```text
POST /api/agent-runs
POST /api/agent-runs/{run_id}/actions/continue-step
POST /api/projects/{project_id}/brain/continue
terminal task hook
```

### Tool/Capability APIs

These may be called by gateway handlers, but should not become independent autonomous controllers:

```text
generate_keyframes
generate_videos
plan_final_edit
export_preview
export_final
diagnose_outputs
diagnose_tasks
diagnose_provider_writeback
diagnose_script
diagnose_keyframe_pool
```

### Platform/Manual APIs

These can remain for SaaS/manual operations:

```text
POST /api/batch/generate-images
POST /api/batch/generate-videos
POST /api/tts/generate
task list/detail/cancel APIs
admin APIs
billing/report APIs
```

They must be labeled as non-main-chain unless explicitly wrapped by a decision packet and gateway handler.

## Runtime State Model

Each authoritative run should have a current runtime state:

```text
created
planning
ready_to_dispatch
dispatching
executing
observing
reflecting
waiting
recovering
blocked
asking_human
completed
failed
cancelled
```

State transitions must be caused by decision packets or terminal observations, not by sibling-task completion alone.

`_maybe_finalize_run` should not mark a run complete if L7 says another stage is still pending. It can remain as a safety observer, but completion authority belongs to the coordinator.

## Data Contracts

### Agent Runtime Decision

The coordinator should persist a normalized decision event:

```json
{
  "source": "main_chain",
  "event_type": "decision",
  "phase": "decision_made",
  "visibility": "user",
  "summary": "Keyframe writeback is complete. Next step is video generation.",
  "reason": "One shot has selected_image and is missing selected_video.",
  "meta": {
    "decision_packet": {},
    "evidence_refs": [],
    "next_step": "generate_videos",
    "requires_user": false
  }
}
```

### Agent Runtime Feedback

Every step should expose a user-facing summary:

```json
{
  "status": "executing",
  "summary": "Generating video for shot 1.",
  "evidence": [
    {"kind": "shot_row", "shot_index": 1, "field": "selected_image"}
  ],
  "next_step": "Wait for the video task to finish, then verify writeback.",
  "risk": null,
  "requires_user": false
}
```

### Observation Signal

All observer sources should normalize into one signal shape:

```json
{
  "type": "WRITEBACK_FAILED",
  "severity": "error",
  "source": "writeback_status",
  "run_id": "run-id",
  "task_id": "task-id",
  "stage_id": "generate_keyframes",
  "summary": "Task completed but selected_image was not written back.",
  "evidence_refs": [
    {"kind": "task", "id": "task-id"},
    {"kind": "shot_row", "shot_index": 1, "field": "selected_image"}
  ],
  "suggested_recovery": "repair_writeback"
}
```

### Reflection Decision

Reflection should record which tier produced the decision:

```json
{
  "reflection_tier": "recovery",
  "decision_status": "recover",
  "recovery_strategy": "repair_writeback",
  "reason": "Provider result exists but required DB writeback is missing.",
  "next_step": "Run writeback repair before dispatching the next stage."
}
```

### Human Question

When blocked or risky:

```json
{
  "status": "asking_human",
  "summary": "Budget may be insufficient before video generation.",
  "question": "Continue and spend the estimated 80 credits for video generation?",
  "options": [
    {"id": "continue", "label": "Continue"},
    {"id": "reduce_scope", "label": "Only shot 1"},
    {"id": "stop", "label": "Pause"}
  ],
  "requires_user": true
}
```

## Implementation Phases

### Phase 1: Contract And Event Protocol

Deliverables:

- Add/extend runtime decision and feedback schemas.
- Add decision mailbox schema and state machine: pending, in_progress, completed, recovered, rejected, cancelled.
- Add durable worker mailbox schemas: inbox, outbox, status_updates, control_channel, audit_log.
- Add normalized observation signal schema.
- Add feedback audience levels: user, expert, debug.
- Add progress context fields: current stage, total stages, percentage, next milestone.
- Add user/expert/debug visibility rules.
- Document which APIs are authoritative, capability, platform/manual, admin, or legacy.
- Add tests for event normalization and visibility.

### Phase 2: Coordinator Expansion

Deliverables:

- Expand `main_chain_controller` into a coordinator service.
- Add explicit `plan/read_state/decide/dispatch/observe/reflect/feedback` methods.
- Make terminal hook call the coordinator, not only `apply_decision_packet`.
- Ensure `wait/recover/blocked/complete` all publish user-facing feedback.
- Add watchdog for no-progress detection.

### Phase 3: Multi-Source Observation And Recovery

Deliverables:

- Implement task status observation.
- Implement DB writeback verification.
- Implement mailbox status/control observation.
- Implement provider/system/user signal inputs where available.
- Add recovery strategies: retry, degrade, reroute, split, human, repair_writeback.
- Add tests for task success with missing writeback.

### Phase 4: Planner Demotion

Deliverables:

- Treat `project_brain.next_action` and B-lane action output as recommendations/intents.
- Convert recommendations through unified facts and canonical decision packet.
- Prevent B lane from direct production/final-edit execution.

### Phase 5: Gateway Enforcement

Deliverables:

- Enforce idempotency at gateway.
- Enforce lane capability whitelist.
- Enforce allowed write scope.
- Centralize budget/rate/concurrency checks where possible.
- Publish dispatch feedback before tool/API call.

### Phase 6: Runtime Learning Plane

Deliverables:

- Capture completed runtime episodes.
- Store decision, observation, recovery, provider, cost, and duration history.
- Store mailbox command/result/control history as episode evidence.
- Provide advisory hints for timeout, provider routing, and recovery strategy.
- Ensure L8 is advisory only and cannot dispatch or change run state.

### Phase 7: Full Loop Tests

Deliverables:

- DB-backed test for:

```text
entry -> plan -> keyframes -> observe -> videos -> observe -> final edit -> complete
```

- DB-backed tests for:

```text
wait
recover
blocked
ask_human
complete
writeback_failed
watchdog_timeout
```

- Snapshot/event tests proving user feedback is understandable and ordered.
- Mailbox tests proving DeepSeek/Doubao results become recommendations, not direct commands.
- Provider mailbox tests proving Seedream/Seedance commands require active observation and writeback verification.
- Capability whitelist tests proving B lane cannot execute and C lane cannot choose global next action.
- Learning-plane tests proving hints are advisory and do not bypass the coordinator.

## Acceptance Criteria

The alignment is complete only when all of these are true:

1. A user goal creates or resumes one authoritative run.
2. The coordinator can state the current plan and stage.
3. Every autonomous production action has a decision packet.
4. Every autonomous production dispatch passes the gateway.
5. Every terminal task re-enters observation.
6. Observation can trigger continue, wait, recover, ask human, or complete.
7. B lane cannot queue production work directly.
8. C lane cannot choose the global next action.
9. The user receives clear progress feedback for each major transition.
10. Final completion requires final artifact or explicit closure criteria, not merely all current tasks being terminal.
11. L7 observes task status and DB writeback status separately.
12. Recoverable failures select an explicit recovery strategy.
13. Feedback can be rendered for user, expert, and debug audiences.
14. Watchdog timeout produces a controlled wait/recover/blocked decision.
15. L8 learning hints are advisory and cannot dispatch work directly.
16. Mailbox messages are durable, auditable, and idempotent.
17. DeepSeek and Doubao mailbox outputs cannot bypass the coordinator.
18. Seedream and Seedance jobs expose progress, heartbeat, timeout, and expected-write verification signals.
19. Gateway capability checks reject unauthorized lane actions before any write or provider call.
20. Decision mailbox records store `decision_rationale` and `thinking_artifacts`, but do not store hidden chain-of-thought as a product/debug feature.
21. Gateway capability checks enforce `CAPABILITY_REQUIREMENTS` against runtime, tool, provider, rate, and concurrency context before dispatch.
22. L7 verifies required multi-artifact output and emits `MISSING_ARTIFACT`, `WRITEBACK_FAILED`, or `ARTIFACT_INVALID` before marking a stage complete.
23. Safety circuit breaker blocks dangerous actions and high/critical risk packets with human/admin review feedback before any destructive write.

## Non-Goals

This design does not require:

- Replacing every existing route immediately.
- Removing manual SaaS task APIs.
- Exposing internal chain-of-thought.
- Calling real external providers in every test.
- Rewriting the frontend before the backend contract is stable.
- Building autonomous A/B optimization before the basic loop is reliable.
- Replacing Celery/provider tasks with mailbox-only workers.

## Risks

1. Compatibility routes may keep reintroducing authority drift.
2. Too many user-visible events can become noisy.
3. Moving budget/rate checks into the gateway can duplicate handler checks during transition.
4. Existing tests may rely on local action semantics instead of coordinator semantics.
5. `agent_runs` may need cleanup around parent/child run semantics.
6. L8 learning can become a hidden controller if not kept advisory.
7. Dynamic timeout logic can be noisy until provider history is mature.
8. User-facing progress can become misleading if writeback verification is not strict.
9. A mailbox-only provider model would recreate Claude Code's passive waiting problem.

## Open Implementation Questions

1. Should one user goal remain a single `agent_run`, or should child runs continue to exist but be hidden behind a parent run?
2. Should `ask_human` be a new packet status or represented as `blocked` with a human question?
3. Should direct final export be a C-lane gateway action or remain an explicit manual expert action?
4. How much provider detail should be user-visible versus expert/debug only?
5. Which recovery strategies are safe without human confirmation for each provider and stage?
6. What persistence table should own runtime episodes: `agent_events`, a new `runtime_episodes`, or both?
7. Should mailbox records live in `agent_events.meta`, dedicated mailbox tables, or both?
8. Which Seedream/Seedance provider progress states can be observed reliably today?

## Recommended Decision

Use a parent authoritative run as the user-visible run. Child runs may exist internally for compatibility, but the coordinator should report and decide through the parent run.

Add `ask_human` as an explicit decision status because it is semantically different from `blocked`: blocked means the system cannot proceed; ask_human means the system can proceed after user input.

Final export should become a C-lane gateway action for autonomous runs. Manual export buttons can remain expert/manual actions if clearly labeled.

Provider details should default to expert visibility. User visibility should focus on progress, evidence, risk, and next step.

L7 should be implemented as active multi-source observation plus three-tier reflection. The first required signals are task status and DB writeback verification because they close the most important correctness gap: a task can finish while the project state remains wrong.

Use the mailbox protocol as durable worker communication for both reasoning workers and provider workers, but with different authority:

```text
DeepSeek/Doubao mailbox -> recommendations and content artifacts
Seedream/Seedance mailbox -> provider job envelope and status audit
Coordinator -> only authority that turns either result into the next decision
```

For Seedream and Seedance, mailbox is not enough. They must always be paired with active observation: progress, heartbeat, timeout, user control, provider result, and DB writeback verification.

L8 should be implemented after the basic loop is stable. It should start by recording episodes and producing timeout/provider/recovery hints, not by making autonomous decisions.
