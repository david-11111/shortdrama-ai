# P1 Fix: State Machine Premature Advancement — "1/8 shots triggers final edit"

## Problem

`generate_videos` stage marks itself "completed" when `selected_video_count > 0`.
With only 1 of 8 shots having a video, the state machine advances to `final_cut`
→ `plan_final_edit`. Users expect ALL shots to have videos before entering editing.

## Root Cause (3 interacting defects)

1. `models.py` line 175: `generate_videos` completed condition is `selected_video_count > 0`
   — should require all shots to have videos (or no active/pending video tasks remain).

2. `models.py` line 188: `review_videos` completed condition is the same — too permissive.

3. `run_coordination.py` `_has_enough_output_to_continue()` uses `any()` — allows
   advancement with partial results.

## Fix Strategy

**Add a new derived metric** `video_generation_complete` (boolean) to `StatsAccumulator.finalize()`:

```
video_generation_complete = (selected_video_count >= shot_count)
                            OR (selected_video_count > 0 AND video_task_active_count == 0 AND video_task_failed_count == 0)
```

This means: "all shots have a video" OR "all dispatched tasks are done with no failures."
The second clause handles partial dispatches (e.g., only some shots were planned for video).

Then change `generate_videos` status_rules:
- `running` when `video_task_active_count > 0`
- `completed` when `video_generation_complete` is truthy

And `review_videos` status_rules:
- `completed` when `video_generation_complete` is truthy

## Files to Change

| File | Change |
|------|--------|
| `app/services/state_machine/stats.py` | Add `video_generation_complete` and `image_generation_complete` to `finalize()` |
| `app/services/state_machine/models.py` | Change `generate_videos` and `review_videos` status_rules to use new metric |
| `app/services/run_coordination.py` | Fix `_has_enough_output_to_continue()` to use a threshold |

## Detailed Changes

### 1. stats.py — Add coverage booleans

```python
def finalize(self) -> dict[str, Any]:
    video_gen_complete = (
        (self._selected_video_count >= self._shot_count > 0)
        or (self._selected_video_count > 0
            and self._video_active == 0
            and self._video_failed == 0)
    )
    image_gen_complete = (
        (self._selected_image_count >= self._shot_count > 0)
        or (self._selected_image_count > 0
            and self._image_active == 0
            and self._image_failed == 0)
    )
    return {
        ...existing fields...
        "video_generation_complete": video_gen_complete,
        "image_generation_complete": image_gen_complete,
    }
```

### 2. models.py — Update status_rules

```python
# generate_videos (line 173-176):
status_rules=(
    _r("running", _c("video_task_active_count", ">", 0)),
    _r("completed", _c("video_generation_complete", "truthy")),
),

# review_videos (line 188):
status_rules=(_r("completed", _c("video_generation_complete", "truthy")),),
```

### 3. run_coordination.py — Fix threshold

```python
def _has_enough_output_to_continue(facts, action):
    if action == "plan_final_edit":
        videos = sum(1 for s in facts.shots if s.get("selected_video"))
        return videos >= len(facts.shots)  # ALL shots must have video
    if action == "generate_videos":
        images = sum(1 for s in facts.shots if s.get("selected_image"))
        return images >= len(facts.shots)
    return False
```

## Rollback

Revert the 3 files. State machine will revert to old behavior. No data migration needed.

## Testing

After deploying: advance the run through generate_videos with only 1/8 shots complete.
Verify the state machine stays in `generate_videos` (status=running or pending) and
does NOT advance to `final_cut`/`plan_final_edit`.
