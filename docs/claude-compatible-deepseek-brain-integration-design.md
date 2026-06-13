# Claude-Compatible DeepSeek Brain Integration Design

**Date:** 2026-05-28  
**Status:** Design baseline  
**Purpose:** Define how to connect DeepSeek through an Anthropic-compatible API as a Claude/Opus-style reasoning brain, without bypassing the existing Agent Run main chain.

## 1. Core Decision

DeepSeek's Anthropic-compatible API should be integrated as a **brain adapter**, not as a media provider and not as a direct execution path.

The correct authority model is:

```text
DeepSeek through Anthropic-compatible API
  = Claude/Opus-style reasoning and diagnosis brain

Doubao / vision model / FFmpeg probe
  = evidence providers and specialist judges

Showrunner Coordinator
  = final production decision authority

Seedream / Seedance / FFmpeg export
  = execution tools
```

This means DeepSeek can help the system think, judge, route, diagnose, and write decision packets. It must not directly call Seedream, Seedance, FFmpeg export, or write production outputs.

## 2. Why This Is Needed

The current chain has many local fixes, but failures still appear because the system lacks one strong reasoning layer that continuously asks:

```text
What is the user's goal?
Where is the chain now?
What evidence exists?
What is broken?
Which layer caused the failure?
What is the safest next action?
```

Claude Code works well because it has a strong coordinator judgment loop:

```text
observe evidence
reason over root cause
choose next action
dispatch bounded work
verify result
repeat
```

The video production system needs the same pattern, but adapted for short-drama artifacts:

```text
goal card
story quality
shot responsibility
prompt fidelity
reference/keyframe quality
video quality
edit quality
writeback correctness
```

## 3. API Compatibility Boundary

The DeepSeek Anthropic-compatible endpoint can be called with the Anthropic SDK:

```text
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=<deepseek key>
ANTHROPIC_MODEL=deepseek-v4-pro
```

Model mapping behavior:

```text
claude-opus*   -> deepseek-v4-pro
claude-sonnet* -> deepseek-v4-flash
claude-haiku*  -> deepseek-v4-flash
```

Important compatibility limits:

```text
text messages: supported
tool_use/tool_result: supported
thinking: supported
streaming: supported
image input: not supported
document input: not supported
MCP tool use/result: not supported
code_execution_tool_result: not supported
```

Therefore this integration cannot make DeepSeek directly "see" images or videos through this endpoint.

DeepSeek must read structured evidence instead:

```text
vision review reports
FFmpeg probe reports
frame extraction summaries
DB writeback status
task/event snapshots
showrunner judge reports
prompt/story/shot data
```

## 4. Target Architecture

The new layer should plug into the existing 7-layer runtime:

```text
L1 Goal Intake
  -> create or update Production Goal Card

L2 Showrunner Coordinator
  -> final decision authority

L3 Claude-Compatible DeepSeek Brain
  -> reasoning, planning, diagnosis, root-cause analysis

L4 State Reader
  -> loads run snapshot, tasks, shots, assets, events, judge reports

L5 Decision Packet / Decision Mailbox
  -> immutable decision record with rationale and evidence

L6 Dispatch Gateway
  -> permission, capability, budget, safety checks

L7 Observer / Judge / Feedback
  -> observes writeback, media quality, task status, user feedback
```

The execution path remains:

```text
/director/agent-run
  -> POST /api/agent-runs
  -> Project Brain / Showrunner
  -> DecisionMailbox
  -> DispatchGateway
  -> C-lane handlers
  -> Seedream / Seedance / FFmpeg
  -> writeback
  -> Observer / Judge
  -> Showrunner decision
```

No direct legacy production route is allowed.

## 4.1 Optional Local Claude Code CLI Bridge

The local machine already has Claude Code installed:

```text
C:\Users\福星1号\AppData\Roaming\npm\claude.ps1
```

The user profile directory:

```text
C:\Users\福星1号\.claude
```

is mainly Claude Code's configuration, sessions, cache, tasks, plugins, settings, and history directory. It is not a Python library that can be imported by the SaaS backend.

Because the SaaS backend normally runs in Docker/Linux, it cannot directly depend on a Windows user-profile path. Therefore local Claude Code can be embedded only through a **host-side bridge**, not by importing `.claude` files into the app.

Recommended bridge model:

```text
SaaS runtime
  -> HTTP call to localhost ClaudeCodeBridge
  -> Bridge invokes claude -p
  -> Claude Code returns structured JSON
  -> SaaS records result as judge/diagnosis evidence
  -> Showrunner decides
```

The bridge is allowed for development and operator-supervised diagnosis. It should not be the only production brain, because it depends on local user configuration and local machine state.

Safe Claude Code invocation pattern:

```powershell
claude -p `
  --output-format json `
  --permission-mode plan `
  --tools "" `
  --no-session-persistence `
  --max-budget-usd 0.05 `
  --append-system-prompt "You are a read-only runtime diagnosis worker. Return JSON only. Do not edit files. Do not call providers." `
  "<diagnosis prompt>"
```

If codebase inspection is needed, the bridge may allow read-only tools only:

```powershell
claude -p `
  --output-format json `
  --permission-mode plan `
  --allowedTools "Read,Grep,Glob" `
  --no-session-persistence `
  --max-budget-usd 0.10 `
  "<diagnosis prompt>"
```

Forbidden bridge modes:

```text
--dangerously-skip-permissions
--allow-dangerously-skip-permissions
Edit / Write access by default
direct provider calls
database writes
budget override
mark_run_complete
```

The bridge output must be treated as evidence, not as an authoritative execution result. It must still flow into:

```text
DecisionMailbox -> DispatchGateway -> C-lane execution
```

## 5. New Component: Anthropic Compatible LLM Adapter

Create one adapter layer:

```text
app/services/anthropic_compatible_llm.py
```

Responsibilities:

- Read settings for base URL, API key, model, timeout, max tokens.
- Call the Anthropic SDK or Anthropic-compatible HTTP API.
- Support text-only messages.
- Support structured JSON mode by prompt contract, not by assuming OpenAI `response_format`.
- Normalize provider errors.
- Return a common response object:

```json
{
  "provider": "deepseek_anthropic",
  "model": "deepseek-v4-pro",
  "text": "",
  "parsed_json": {},
  "usage": {},
  "raw": {},
  "error": ""
}
```

This adapter becomes the foundation for all Claude-style reasoning tasks.

## 6. New Settings

Add settings:

```text
anthropic_compatible_provider=deepseek
anthropic_base_url=https://api.deepseek.com/anthropic
anthropic_api_key=
anthropic_model=deepseek-v4-pro
anthropic_timeout_seconds=60
anthropic_max_tokens=4096
```

Existing DeepSeek chat-completion settings can remain for backwards compatibility:

```text
deepseek_base_url=https://api.deepseek.com
deepseek_model=deepseek-chat
deepseek_api_key=
```

But new Showrunner/Claude-style reasoning should use the Anthropic-compatible adapter.

## 7. Brain Roles

### 7.1 Planner Brain

Used when the user gives an instruction.

Input:

- raw user instruction
- run snapshot
- current pending action
- current tasks
- visible artifacts
- previous failures

Output:

```json
{
  "intent_type": "conversation | status_query | production_action | quality_feedback | diagnosis",
  "reply": "",
  "dispatch_ready": true,
  "recommended_action": "generate_story_plan | plan_visual_assets | generate_keyframes | generate_videos | plan_final_edit | ask_human | wait",
  "reason": "",
  "evidence_refs": [],
  "missing_info": [],
  "confidence": 0.0
}
```

### 7.2 Root Cause Brain

Used when a run gets blocked, produces bad output, or does not advance.

Input:

- Production Goal Card
- run snapshot
- event stream
- task states
- shot rows
- artifact refs
- judge reports
- provider errors

Output:

```json
{
  "root_cause_layer": "goal_card | story | shot | reference | prompt | keyframe | video | edit | provider | technical | ui | unknown",
  "status": "recover | blocked | wait | complete",
  "recommended_action": "",
  "repair_scope": [],
  "reason": "",
  "evidence_refs": [],
  "confidence": 0.0
}
```

### 7.3 Showrunner Judge Brain

Used before spending credits and after artifact writeback.

It judges:

- whether the story serves the goal card
- whether each shot has a dramatic job
- whether prompts preserve intent
- whether visual reports show keyframes are usable
- whether video reports show clips are cuttable
- whether edit reports show the sequence is coherent

It does not directly inspect pixels through the Anthropic-compatible DeepSeek endpoint. It reads visual/technical reports.

### 7.4 Feedback Brain

Used to explain status to the user.

It converts internal evidence into user-facing feedback:

```text
现在卡在参考图/关键帧前，不是 Seedance 问题。
根因是分镜职责不够明确，Showrunner 已阻断出图，下一步会先重写 shot responsibility 和 prompt。
```

## 8. Tool Boundary

The Claude-Compatible DeepSeek Brain may use logical tools through structured prompts or internal function dispatch, but its tools are advisory only.

Allowed:

```text
read_run_snapshot
read_agent_events
read_tasks
read_shot_rows
read_assets
read_judge_reports
diagnose_writeback
diagnose_quality_gap
propose_decision_packet
draft_user_feedback
```

Forbidden:

```text
call_seedream
call_seedance
call_ffmpeg_export
write_selected_image
write_selected_video
delete_project
override_budget
bypass_gateway
mark_run_complete
```

All executable recommendations must become DecisionMailbox records and pass DispatchGateway.

## 9. Decision Mailbox Integration

Every DeepSeek/Claude-compatible recommendation should be persisted as a mailbox event.

The mailbox record should include:

```json
{
  "decision_id": "",
  "status": "pending | completed | rejected",
  "packet": {},
  "decision_rationale": "safe summarized rationale",
  "thinking_artifacts": [
    {
      "type": "anthropic_compatible_reasoning",
      "provider": "deepseek",
      "model": "deepseek-v4-pro",
      "usage": {},
      "confidence": 0.0
    }
  ]
}
```

Do not store hidden chain-of-thought as product data. Store a concise rationale and evidence references.

## 10. Main Chain Behavior

### 10.1 User Input

```text
User -> /director/agent-run -> POST /api/agent-runs
```

The system should:

1. Create a clean run when `clean_start=true`.
2. Store input assets in run meta.
3. Build or update the Production Goal Card.
4. Ask the Claude-Compatible Brain to classify intent and propose the next action.
5. Convert the proposal into a DecisionPacket.
6. Submit the packet to DecisionMailbox.
7. Dispatch only through DispatchGateway.

### 10.2 Blocked Chain

If a run completes storyboard but does not queue image/video tasks:

1. Observer detects no task progress.
2. State Reader loads brain phase, missing gates, risks, shots, visual plan.
3. Root Cause Brain identifies the blocking layer.
4. Showrunner decides:

```text
continue planning
repair story
repair shot responsibility
apply visual asset plan
generate keyframes
wait
ask human
```

5. DecisionMailbox records the chosen action.
6. Gateway dispatches if allowed.

### 10.3 Bad Image Or Video

If output exists but quality is poor:

1. Vision Judge and/or FFmpeg probe generate evidence.
2. Root Cause Brain reads the reports.
3. Showrunner attributes the failure:

```text
prompt too generic
reference missing
provider drift
video motion uncuttable
technical export failure
story beat unclear
```

4. The system repairs the upstream layer instead of blindly retrying the provider.

## 11. Interaction With Existing Modules

Relevant existing modules:

```text
app/services/llm_planner.py
app/services/story_understanding_llm.py
app/services/showrunner_judgment.py
app/services/decision_mailbox.py
app/services/main_chain_controller.py
app/services/main_chain_observer.py
app/services/main_chain_feedback.py
app/services/run_dispatch_gateway.py
app/services/agent_run_snapshot.py
app/routes/agent_runs.py
app/routes/workbench.py
```

Migration approach:

1. Keep existing `llm_planner.py` behavior working.
2. Add the Anthropic-compatible adapter behind a feature flag.
3. Gradually move planner/story/showrunner reasoning to the new adapter.
4. Keep all production execution under DispatchGateway.

## 12. Minimum Viable Integration

The first useful version should not try to build a full autonomous Claude Code clone.

Minimum version:

```text
1. Anthropic-compatible DeepSeek adapter
2. Planner Brain for user instruction routing
3. Root Cause Brain for blocked runs
4. Showrunner Judge Brain for story/shot/prompt gates
5. DecisionMailbox persistence
6. Gateway-only execution
7. User-facing feedback summary
```

The first target failure to solve:

```text
POST /api/agent-runs creates storyboard,
but the chain does not continue into reference/keyframe/video tasks.
```

The new brain should diagnose:

```text
current_phase=preflight_review
next_action=fix_preflight_risks
visual_plan_action_count>0
pending_keyframes>0
no image_gen tasks
root_cause_layer=planning_gate/showrunner_preflight
recommended_action=repair_or_apply_visual_plan_before_keyframes
```

## 13. Safety Rules

The brain must obey these rules:

```text
Never bypass /director/agent-run.
Never call media providers directly.
Never mark a run complete without observer evidence.
Never treat Seedream/Seedance output as self-approved.
Never ask the user to direct every creative detail.
Never spend credits without DispatchGateway budget and capability checks.
Never use DeepSeek Anthropic-compatible image input because it is unsupported.
```

## 14. Testing Requirements

Unit tests:

- adapter builds Anthropic-compatible request
- adapter parses text and JSON responses
- planner brain emits valid action only
- root cause brain maps blocked snapshots to root cause layer
- B-lane cannot execute provider work
- mailbox stores rationale and thinking artifacts
- gateway rejects direct provider execution from brain

Integration tests:

- `/api/agent-runs` with clean project calls brain and records a mailbox decision
- blocked storyboard-only run triggers root cause diagnosis
- missing image/video writeback creates observer signal and brain repair decision
- bad keyframe report triggers prompt/reference repair instead of blind video generation

Live verification:

```text
Create clean project
POST /api/agent-runs action=production_run
Check agent_events:
  source=deepseek_anthropic or showrunner
  source=decision_mailbox
  source=dispatch_gateway
Check tasks:
  image_gen queued when keyframe gate passes
Check writeback:
  selected_image populated before video_gen
```

## 15. Implementation Phases

### Phase 1: Adapter And Settings

Add the Anthropic-compatible adapter and configuration. No production behavior change yet.

### Phase 2: Planner Brain

Switch or optionally route `llm_planner.py` through the adapter. Keep the existing DeepSeek chat-completions planner as fallback.

### Phase 3: Root Cause Brain

Add diagnosis for blocked and stalled runs using `agent_run_snapshot` evidence.

### Phase 4: Showrunner Gate

Use the brain to judge goal card, story, shot responsibility, and prompt fidelity before spending Seedream/Seedance credits.

### Phase 5: Feedback Loop

Publish structured feedback explaining:

```text
what happened
where it is blocked
who judged it
what evidence was used
what the next action is
```

### Phase 6: Media Quality Loop

Read vision and FFmpeg reports, then let Showrunner decide whether to accept, regenerate, repair prompt, or repair upstream story/shot.

## 16. Final Statement

This integration should make DeepSeek act like a Claude/Opus-style reasoning partner inside the existing runtime.

It should not create another uncontrolled execution path.

The target is:

```text
DeepSeek/Claude-compatible brain thinks.
Showrunner decides.
DecisionMailbox records.
Gateway authorizes.
C-lane executes.
Observer verifies.
Feedback explains.
```

That is the architecture that can reduce endless local fixes and turn the system into a coordinated production agent.
