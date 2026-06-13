# P0 Fix: Queue-Aware Task Reconciler — "Queued but Lost" Bug

## Problem Statement

Tasks can enter a "zombie" state: `status='queued'` in PostgreSQL but no corresponding
message exists in the Redis broker. Root cause: the two-phase commit gap between
`await session.commit()` (DB) and `celery_app.send_task()` (Redis). If the process
crashes, restarts, or the Redis publish silently fails in that window, the task is
orphaned forever (until the 30-minute blunt cleanup marks it `failed`).

Current impact: 30 minutes of undetected downtime per orphaned task.

## Design Goals

1. Detect orphaned tasks within **60 seconds**, not 30 minutes.
2. **Re-dispatch** (not just fail) — give the task a second chance.
3. Prevent duplicate execution via idempotency lock.
4. Refund credits and notify user only after exhausting retries.
5. Expose reconciliation metrics for operational visibility.
6. Harden Redis persistence to prevent broker message loss on restart.

## Implementation Plan

### Step 1: Add `reconcile_orphaned_tasks` beat task (new function in `admin_tasks.py`)

Logic (runs every 60 seconds):

```
1. SELECT task_id, task_type, run_id, credit_transaction_id, created_at
   FROM tasks
   WHERE status = 'queued'
     AND created_at < NOW() - interval '3 minutes'
     AND (reconcile_attempts IS NULL OR reconcile_attempts < 3)
   LIMIT 50;

2. For each task:
   a. Determine the Celery queue from task_type (video_tasks→video, etc.)
   b. Check if task_id exists in the broker queue (scan Redis list keys)
      — Use pipeline LRANGE with sampling (not full scan for performance)
      — OR: use a lightweight "dispatch receipt" SET in Redis (see Step 2)
   c. If message IS in broker: skip (it'll be picked up eventually)
   d. If message NOT in broker:
      - Increment `reconcile_attempts` in DB
      - Re-dispatch via celery_app.send_task() with the original args
      - Log structured event: {event: "task_reconciled", task_id, attempt}

3. For tasks where reconcile_attempts >= 3:
   - Mark status = 'failed'
   - Refund credits (call credit_service.refund)
   - Publish WebSocket notification
   - Log structured event: {event: "task_abandoned", task_id}
```

### Step 2: Add "Dispatch Receipt" pattern (lightweight broker presence check)

Problem: Scanning Redis Lists (LRANGE) for a specific task_id is O(N) and unreliable
with priority queues (11 keys per queue). Instead, we add a lightweight receipt:

```
On send_task() success:
  → Redis SET "dispatch:{task_id}" "" EX 3600   (1-hour TTL)

On worker task start (publish_progress status='running'):
  → Redis DEL "dispatch:{task_id}"

On task complete/fail:
  → Redis DEL "dispatch:{task_id}"  (belt-and-suspenders)
```

The reconciler checks: `EXISTS dispatch:{task_id}`.
- If EXISTS → message was sent to broker, worker just hasn't started yet. Skip.
- If NOT EXISTS and task is still `queued` after 3 min → orphan confirmed. Re-dispatch.

This is O(1) per check, no LRANGE scanning needed.

### Step 3: Add `reconcile_attempts` column to tasks table

Alembic migration:

```sql
ALTER TABLE tasks ADD COLUMN reconcile_attempts smallint NOT NULL DEFAULT 0;
```

Lightweight, no index needed (the WHERE clause filters on status + created_at which
should already have an index).

### Step 4: Idempotency lock in worker entry

In `_shared.py` or at the top of each task handler, add:

```python
LOCK_KEY = f"task_exec_lock:{task_id}"
acquired = redis_client.set(LOCK_KEY, "1", nx=True, ex=task_time_limit)
if not acquired:
    # Another worker is already executing this task
    logger.warning("Duplicate execution blocked for task %s", task_id)
    return  # ACK the message, don't execute
```

Release on completion/failure. This prevents the re-dispatched message from causing
duplicate work if the original message was merely delayed (not lost).

### Step 5: Redis persistence hardening (docker-compose)

Add to the redis service command:

```yaml
redis:
  command: ["redis-server", "--appendonly", "yes", "--appendfsync", "everysec"]
```

This ensures messages survive Redis container restarts with at most 1 second of data loss.

### Step 6: Prometheus metrics

Add to `monitoring/health.py`:

```python
_RECONCILED = Counter(
    "task_reconciliation_total",
    "Task reconciliation actions.",
    ("action",),  # "redispatched", "abandoned", "skipped_in_queue"
    registry=_REGISTRY,
)
```

Expose in `/metrics` endpoint.

### Step 7: Update beat schedule

```python
"orphan-task-reconciler": {
    "task": "app.tasks.admin_tasks.reconcile_orphaned_tasks",
    "schedule": 60,  # every 60 seconds
},
```

## Files to Modify

| File | Change |
|------|--------|
| `app/tasks/admin_tasks.py` | Add `reconcile_orphaned_tasks` function |
| `app/celery_app.py` | Add beat schedule entry |
| `app/services/task_submission.py` | Add dispatch receipt SET after send_task |
| `app/tasks/_shared.py` | Add dispatch receipt DEL on status transitions; add exec lock |
| `app/tasks/video_tasks.py` | Add idempotency lock at entry |
| `app/tasks/image_tasks.py` | Add idempotency lock at entry |
| `monitoring/health.py` | Add reconciliation counter metric |
| `docker-compose.yml` | Add `--appendonly yes` to redis command |
| `alembic/versions/XXX_add_reconcile_attempts.py` | New migration |

## Risk Assessment

- **Blast radius**: Low. The reconciler only touches tasks already in a broken state.
- **Performance**: O(N) where N = orphaned tasks (expected: 0-2 at any time). 
  Receipt check is O(1) per task. No table scans (uses indexed status + created_at).
- **Rollback plan**: Remove beat schedule entry → reconciler stops. No data corruption.
- **Testing**: Can be tested by manually setting a task to 'queued' without sending to broker,
  then verifying it gets re-dispatched within 60s.

## Execution Order

1. Migration (add column) — can be applied with zero downtime (nullable, has default)
2. Docker-compose Redis hardening — requires redis restart (schedule during low traffic)
3. Code changes — deploy as a unit
4. Verify: create a synthetic orphan task, confirm reconciler picks it up
