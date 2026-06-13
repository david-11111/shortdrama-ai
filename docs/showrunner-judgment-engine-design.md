# Showrunner Judgment Engine Design

**Date:** 2026-05-28  
**Status:** Design baseline  
**Purpose:** Define who judges short-drama quality, what evidence each judge provides, and how the main chain decides whether to continue, regenerate, repair, or stop.

## 1. Core Verdict

The project should not treat Seedream, Seedance, FFmpeg, DeepSeek, or Doubao as the final judge.

The correct production model is:

```text
Worker produces
Judge observes and scores
Showrunner Coordinator decides
```

The final authority is the **Showrunner Coordinator**. It is the Claude/Codex-style coordinator for premium short-drama production.

The most important rule:

```text
The tool that creates an artifact cannot be the final judge of that artifact.
```

Seedream creates images. It cannot finally decide whether an image serves the drama.

Seedance creates video. It cannot finally decide whether the video is premium, cuttable, on-story, and likely to retain viewers.

FFmpeg inspects and assembles media. It cannot decide whether the story has emotional force.

DeepSeek can reason over text and reports. It cannot judge pixels or motion unless visual evidence has first been converted into structured observations.

## 2. Why This Layer Exists

The current main chain can run:

```text
goal -> story/shot rows -> keyframes -> video -> final edit plan
```

Real-provider testing proved the engineering chain can call Seedream and Seedance, write back selected media, publish events, and continue through dispatch gateway decisions.

But the product target is higher:

```text
精品爆款短剧 Agent
```

That requires two standards at the same time:

1. **Commercial hook:** viewers stop, understand the conflict, feel tension, continue watching, and want the next episode.
2. **Premium texture:** the work feels coherent, cinematic, emotionally controlled, visually unified, and not like low-grade template output.

The missing layer is not another provider. It is a production judgment engine.

## 3. Claude/Codex Analogy

Claude/Codex does not trust code because a worker says "done".

It reads evidence:

```text
tests
type checks
lint
logs
stack traces
diffs
runtime output
```

Then the coordinator decides whether the problem is solved.

The short-drama equivalent is:

```text
story review
goal-card alignment
reference-image review
prompt fidelity review
video technical probe
video frame review
continuity review
edit rhythm review
market/taste review
```

The Showrunner Coordinator is not a magic visual model. It is the final decision engine that reads these reports and reasons over them.

## 4. Role Boundaries

### 4.1 Showrunner Coordinator

Owns final judgment.

Responsibilities:

- Maintain the production goal card.
- Read all judge reports.
- Decide the current stage status.
- Locate the failure layer when output is not good enough.
- Select the next action and lane.
- Produce a decision packet with evidence.
- Prevent generator tools from self-approving their own outputs.

It answers:

```text
What was the user's original goal?
What is the premium/breakout target?
What artifact exists now?
Which judge reports support or reject it?
Is the problem story, asset, prompt, provider output, edit, or market fit?
What is the cheapest safe repair?
```

### 4.2 Text Judges

Usually powered by DeepSeek, a Claude-like text reasoning model, or another strong text model.

They can judge:

- User intent.
- Story premise.
- Hook strength.
- Character goal.
- Conflict.
- Emotional arc.
- Episode structure.
- Shot responsibility.
- Prompt fidelity.
- Market/taste positioning.

They cannot directly judge:

- Whether a face is stable in an image.
- Whether motion drifts across a video.
- Whether a frame is black or blurry.
- Whether a generated image actually contains the claimed subject.

### 4.3 Vision Judges

Usually powered by Doubao multimodal vision, another visual model, or a configured `vision_review_provider`.

They can judge:

- Whether an image matches the shot.
- Whether character, scene, costume, prop, and style references are visible.
- Whether a keyframe looks premium or generic.
- Whether extracted video frames keep identity and scene consistency.
- Whether the subject is clear.
- Whether the generated visual has template drift, extra people, wrong environment, or weak composition.

They cannot finally judge:

- Full series market potential.
- Whether a weak visual should be accepted for budget reasons.
- Whether the system should rewrite story before regenerating images.

### 4.4 FFmpeg / Technical Media Probe

FFmpeg is a technical witness, not a creative judge.

It can provide:

- Duration.
- Resolution.
- Codec.
- Audio track presence.
- Black-frame detection.
- Frozen-frame detection.
- Frame extraction.
- Scene boundaries.
- Export success/failure.
- Concatenation errors.

It cannot judge:

- Whether a shot has emotional force.
- Whether the character feels premium.
- Whether the opening hook will retain viewers.
- Whether the story is coherent.

### 4.5 Generation Workers

Seedream:

- Produces reference images and keyframes.
- Writes back image candidates.
- Must be judged by Image/Visual Judge.

Seedance:

- Produces image-to-video clips.
- Writes back video variants.
- Must be judged by Video Judge and FFmpeg probe.

FFmpeg export:

- Produces preview/final video from a plan.
- Must be judged by Edit Judge and technical delivery checks.

## 5. The Production Goal Card

Every judgment must compare artifacts against one durable target.

The goal card is the equivalent of a test spec for drama.

For a user prompt like:

```text
我做这个工具快一个月了，从开始立项，到现在，经历了很多，我希望你能把这个过程做成短剧
```

The Showrunner should first produce:

```json
{
  "format": "premium_short_drama",
  "source_type": "real_project_process",
  "core_theme": "AI工具创业/开发过程中的困惑、坚持和突破",
  "main_character": "想做出精品爆款短剧Agent的工具开发者",
  "central_conflict": "链路能跑，但系统不会判断剧本、参考图、视频和成片质量",
  "emotional_arc": ["期待", "焦虑", "怀疑", "反复测试", "发现核心问题", "重新建立判断引擎"],
  "visual_anchors": ["电脑屏幕", "文档", "测试日志", "失败提示", "AI生成结果", "深夜工作场景"],
  "premium_constraints": ["克制", "真实", "高级感", "统一视觉风格", "避免廉价爽文模板"],
  "market_constraints": ["前三秒有问题钩子", "中段有冲突升级", "结尾有下一步悬念"],
  "must_not": ["泛化成电视剧主角", "把项目ID写进创作prompt", "无目标空镜", "无剧情职责的模板分镜"]
}
```

If the goal card is wrong, every downstream artifact will drift.

Therefore the first quality gate is:

```text
Goal Card Gate
```

## 6. Judgment Stages

### 6.1 Goal Card Gate

Question:

```text
Did the system understand the user goal as the right kind of production?
```

Inputs:

- Raw user goal.
- Project docs.
- Existing workspace memory.
- Previous chat/run context when available.

Checks:

- Is this traditional drama, documentary short drama, product drama, manga drama, or promotional narrative?
- Is the core conflict explicit?
- Is the target audience implied?
- Is the premium/breakout strategy explicit?
- Are forbidden drifts recorded?

Failure examples:

- User wants a real project process, but the system produces generic "电视剧主角".
- User wants premium short drama, but the system produces a plain report.

Repair:

- Rewrite goal card.
- Regenerate story outline from the corrected card.

### 6.2 Story Judge

Question:

```text
Does the script serve the goal card and contain a watchable short-drama structure?
```

Checks:

- Opening hook.
- Character goal.
- Conflict.
- Obstacle.
- Reversal.
- Emotional escalation.
- Ending hook.
- Premium tone.
- Commercial retention potential.

Output:

```json
{
  "stage": "story",
  "score": 0,
  "status": "pass | needs_review | regenerate",
  "commercial_hook_score": 0,
  "premium_texture_score": 0,
  "problems": [],
  "root_cause": "goal_card | premise | character | conflict | pacing | tone",
  "suggested_action": "continue | rewrite_story | ask_showrunner"
}
```

### 6.3 Shot Responsibility Judge

Question:

```text
Does each shot have a clear dramatic job?
```

Each shot should declare:

- What story beat it covers.
- What emotion it should deliver.
- What visual anchor it must include.
- What continuity it must preserve.
- What viewer-retention function it serves.

Bad shot:

```text
电视剧主角进入核心场景
```

Good shot responsibility:

```text
第1镜：深夜，开发者盯着第四次失败的测试日志，屏幕反光压在脸上。职责是建立真实困境和前三秒钩子。
```

Repair:

- Rewrite shot rows.
- Do not generate keyframes until shot responsibility is clear.

### 6.4 Reference / Keyframe Judge

Question:

```text
Does the image lock the right character, scene, style, and narrative object for this story?
```

Inputs:

- Goal card.
- Shot responsibility.
- Prompt.
- Reference assets.
- Generated image URL.
- Vision report.

Checks:

- Character identity.
- Scene identity.
- Style unity.
- Narrative props.
- Composition.
- Premium texture.
- Market clickability.
- Whether the image is usable as a video first frame.

Failure examples:

- Looks like a generic office stock image.
- No developer/computer/testing context.
- Character not stable across shots.
- Project ID appears as literal creative content.

Repair:

- If reference assets are missing: generate/lock references first.
- If prompt is weak: rewrite prompt before regenerating.
- If provider output drifted: regenerate keyframe with same improved prompt.

### 6.5 Prompt Fidelity Judge

Question:

```text
Did the prompt faithfully translate the story and shot responsibility into provider-ready language?
```

Checks:

- No raw project IDs or system labels.
- Concrete subject/action/scene/emotion.
- Continuity anchors included.
- Provider constraints included.
- Negative constraints included.
- The prompt still serves the goal card.

Repair:

- Rewrite prompt.
- Do not spend provider credits until prompt passes.

### 6.6 Video Judge

Question:

```text
Does the video complete the shot responsibility and remain cuttable?
```

Inputs:

- Goal card.
- Shot responsibility.
- Keyframe image.
- Video prompt.
- Seedance result URL.
- FFmpeg probe report.
- Extracted frames.
- Vision review report.

Checks:

- Duration and resolution.
- Black/frozen frames.
- Subject stability.
- Identity drift.
- Motion matches shot responsibility.
- Emotion delivery.
- Continuity with previous/next shot.
- Cuttable start/end.
- Premium texture.

Repair:

- If technical failure: retry or change provider.
- If motion drift: regenerate video with stronger motion constraints or shorter duration.
- If keyframe is wrong: go back to keyframe.
- If prompt is wrong: rewrite prompt.
- If story beat is wrong: go back to shot/story.

### 6.7 Edit Judge

Question:

```text
Do the available clips form a coherent, premium, watchable sequence?
```

Checks:

- Story continuity.
- Emotional progression.
- Pacing.
- Hook delivery.
- Ending hook.
- Clip order.
- Transitions.
- Subtitle/BGM/voiceover readiness.
- Missing clip impact.
- Whether preview/final export is justified.

Repair:

- Reorder clips.
- Trim clips.
- Regenerate weak clips.
- Generate missing shots.
- Export partial preview only if explicitly marked partial.

### 6.8 Market/Taste Judge

Question:

```text
Is this both likely to retain viewers and premium enough for the product positioning?
```

This judge scores two axes:

```text
breakout_potential
premium_texture
```

Breakout checks:

- First 3 seconds hook.
- Visible conflict.
- Relatable pain.
- Curiosity gap.
- Reversal or escalation.
- Comment/share potential.
- Next-episode desire.

Premium checks:

- Emotional restraint.
- Non-generic characterization.
- Visual unity.
- Cinematic composition.
- Avoidance of cheap melodrama.
- High-quality pacing.

The Showrunner should not blindly maximize one axis. A cheap viral trick that destroys premium texture should fail.

## 7. Unified Judge Report Contract

All judges should output a common report shape.

```json
{
  "report_version": "showrunner_judge_v1",
  "run_id": "",
  "project_id": "",
  "stage": "goal | story | shot | reference | prompt | keyframe | video | edit | market",
  "artifact_ref": {
    "type": "text | image | video | edit_plan | final_video",
    "id": "",
    "url": "",
    "shot_index": null
  },
  "scores": {
    "goal_alignment": 0,
    "commercial_hook": 0,
    "premium_texture": 0,
    "continuity": 0,
    "technical_validity": 0,
    "cuttability": 0
  },
  "status": "pass | needs_review | regenerate | blocked",
  "root_cause_layer": "goal_card | story | shot | reference | prompt | keyframe | video | edit | provider | technical | unknown",
  "evidence": [
    {
      "kind": "text | frame | ffmpeg | vision | db | event",
      "ref": "",
      "summary": ""
    }
  ],
  "problems": [],
  "suggested_action": "continue | rewrite_story | lock_references | rewrite_prompt | regenerate_keyframe | regenerate_video | revise_edit | export_preview | ask_human | block",
  "confidence": 0.0
}
```

The report is evidence. It is not the final decision.

## 8. Showrunner Decision Packet

The Showrunner Coordinator converts reports into an authoritative decision packet.

```json
{
  "packet_version": "showrunner_decision_v1",
  "run_id": "",
  "stage_id": "",
  "action": "",
  "status": "execute | wait | recover | blocked | complete",
  "reason": "",
  "selected_lane": "a_lane_project_brain | b_lane_agent_runs | c_lane_production",
  "evidence_refs": [],
  "judge_reports": [],
  "root_cause_layer": "",
  "allowed_writes": [],
  "success_criteria": [],
  "failure_policy": {
    "retryable": false,
    "fallback_action": "",
    "require_human_confirmation": false
  },
  "quality_bar": {
    "minimum_goal_alignment": 75,
    "minimum_commercial_hook": 70,
    "minimum_premium_texture": 72,
    "minimum_continuity": 70
  }
}
```

This packet is what should flow through the existing dispatch gateway.

## 9. Failure Attribution

When a target artifact is not good enough, the system must not blindly retry the last provider call.

The Showrunner must attribute the failure.

```text
If the concept is wrong -> repair goal card.
If the story is weak -> rewrite story.
If shot responsibility is vague -> rewrite shot.
If reference assets are missing -> lock/generate references.
If prompt lost the intent -> rewrite prompt.
If keyframe is wrong -> regenerate keyframe.
If video motion drifted -> regenerate video.
If clips are usable but rhythm is bad -> revise edit.
If export is broken -> fix FFmpeg/export pipeline.
```

This mirrors Claude/Codex root-cause behavior:

```text
Do not patch the symptom. Locate the layer that produced the bad output.
```

## 10. Existing Code Anchors

Current relevant modules:

- `app/services/main_chain_controller.py`
- `app/services/run_coordination.py`
- `app/services/run_dispatch_gateway.py`
- `app/services/project_brain.py`
- `app/services/project_brain_ledgers.py`
- `app/services/post_generation_review.py`
- `app/services/vision_review.py`
- `app/tasks/image_tasks.py`
- `app/tasks/video_tasks.py`
- `app/tasks/director_tasks.py`
- `app/services/final_edit.py`
- `app/services/video_edit.py`

Current gap:

- `post_generation_review.py` and `vision_review.py` already provide lightweight image/video review hooks.
- They do not yet represent a full Showrunner judgment engine.
- Existing review statuses can block stages, but the system does not yet consistently identify whether the root cause is story, reference, prompt, provider output, or edit.

## 11. Integration With The 7-Layer Main Chain

The judgment engine should not create a parallel orchestration path.

It should plug into the existing 7-layer loop:

```text
L1 Goal Intake
  -> build/update Goal Card

L2 Coordinator
  -> Showrunner Coordinator owns final judgment

L3 Planner
  -> proposes story/visual/video/edit actions

L4 Unified State Reader
  -> loads artifacts, judge reports, events, tasks, shots, edit plans

L5 Decision Packet
  -> includes judge reports and root_cause_layer

L6 Dispatch Gateway
  -> only executes authorized repairs/generation/export

L7 Observation / Reflection / Feedback
  -> runs judge probes after writeback and feeds next decision
```

## 12. Implementation Phases

### Phase 1: Contract And Data Model

Goal: make judgment first-class without changing provider behavior.

Tasks:

1. Add `ShowrunnerGoalCard`.
2. Add `ShowrunnerJudgeReport`.
3. Add `ShowrunnerDecisionPacket` extension fields.
4. Persist reports as `agent_events` and/or `agent_artifacts`.
5. Surface report summaries in snapshots.

### Phase 2: Text Judgment

Goal: stop generic story and prompt drift before media generation.

Tasks:

1. Build Goal Card from user instruction plus workspace docs.
2. Add Story Judge.
3. Add Shot Responsibility Judge.
4. Add Prompt Fidelity Judge.
5. Block keyframe/video generation when story or prompt is below threshold.

### Phase 3: Visual Judgment

Goal: make image/keyframe review meaningful.

Tasks:

1. Wire a real vision review provider.
2. Expand image review dimensions beyond current face/reference checks.
3. Compare generated image against Goal Card and shot responsibility.
4. Attribute failures to reference, prompt, or provider output.

### Phase 4: Video Judgment

Goal: judge generated video as a drama clip, not just a URL.

Tasks:

1. Add FFmpeg probe and frame extraction for each generated video.
2. Send selected frames to Vision Judge with shot responsibility and keyframe context.
3. Score motion, identity drift, emotion delivery, continuity, and cuttability.
4. Feed report into main-chain terminal reflection.

### Phase 5: Edit And Final Film Judgment

Goal: decide whether the sequence is a premium short-drama artifact.

Tasks:

1. Judge final edit plan before export.
2. Judge preview export after FFmpeg.
3. Score continuity, rhythm, hook, ending, subtitles/BGM/voiceover readiness.
4. Block final export unless the sequence meets the quality bar or is explicitly marked partial.

### Phase 6: Learning Loop

Goal: improve future decisions from past runs.

Tasks:

1. Store episode-level decisions and outcomes.
2. Track which repairs improved scores.
3. Build reusable failure patterns:
   - generic prompt drift
   - missing reference assets
   - weak first 3 seconds
   - identity drift
   - uncuttable motion
4. Use patterns to recommend earlier prevention.

## 13. Minimum Viable Judgment Engine

The first useful version does not need a perfect visual model.

Minimum useful loop:

```text
Goal Card
-> Story Judge
-> Shot Responsibility Judge
-> Prompt Fidelity Judge
-> existing image/video review
-> Showrunner root-cause decision
```

This would already prevent the failure observed in real testing:

```text
raw prompt contained project id
shot text became generic "电视剧主角"
image/video generation succeeded technically
but the creative target was wrong
```

The first Showrunner gate should have blocked before Seedream spend:

```text
root_cause_layer = "story/shot/prompt"
suggested_action = "rewrite_shots_and_prompts"
```

## 14. Non-Goals

This engine does not promise guaranteed virality.

It can only raise probability by enforcing:

- stronger hooks,
- clearer conflicts,
- better continuity,
- higher visual quality,
- better edit readiness,
- fewer generic outputs,
- less provider-credit waste.

It also should not ask the user to become the director. Human confirmation is only for high-cost, high-risk, or subjective final preference. The default mode is autonomous Showrunner judgment.

## 15. Final Architecture Statement

The premium short-drama agent needs a judgment engine as strong as its generation pipeline.

The correct authority model is:

```text
Seedream / Seedance / FFmpeg
  = hands and tools

DeepSeek / Doubao / vision model / FFmpeg probes
  = evidence providers and specialist judges

Showrunner Coordinator
  = final production brain
```

The system succeeds only when every artifact is judged against the same goal card:

```text
Does this serve the story?
Does this improve retention?
Does this preserve premium texture?
Does this move the project toward a complete short drama?
```

If not, the Showrunner must know which layer to repair before spending again.
