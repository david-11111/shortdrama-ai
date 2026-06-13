# Agent Runtime — Health Check & Metrics 建议

> 当前已落地的基础监控在 `monitoring/health.py`：`/health`、`/health/detailed`、
> `/metrics`、HTTP 请求计数/延迟、Celery 队列深度和 API uptime。
> 本文下面的 `agent_*` 指标仍是 Agent Runtime 专项扩展建议，不能当作已上线指标使用。

## 概述

Agent Runtime 涉及长时运行的 AI 任务（单次 run 可持续数分钟），需要专项监控指标，
与普通 HTTP 请求的 p99 延迟监控逻辑不同。

---

## 推荐 Prometheus 指标

### 1. agent_runs_active（Gauge）

```
agent_runs_active{project_id="...", mode="auto|step"}
```

- **含义**：当前 status='running' 的 agent_runs 数量
- **采集方式**：定时查询 DB（每 30s）或在 create/update 时 inc/dec
- **告警阈值**：单用户 > 5 时告警（可能卡死）

### 2. agent_run_duration_seconds（Histogram）

```
agent_run_duration_seconds{mode="auto|step", status="done|failed|interrupted"}
```

- **含义**：agent run 从 started_at 到 ended_at 的耗时
- **桶建议**：[30, 60, 120, 300, 600, 1200]
- **告警阈值**：p95 > 600s 时告警

### 3. agent_events_per_run（Histogram）

```
agent_events_per_run{event_type="log|progress|error|artifact"}
```

- **含义**：每次 run 产生的 event 数量
- **用途**：检测 event 风暴（单次 run > 500 events 可能是死循环）
- **告警阈值**：单 run event 数 > 500

### 4. agent_credits_spent_total（Counter）

```
agent_credits_spent_total{user_id="...", trigger_type="user_click|auto"}
```

- **含义**：agent 累计消耗积分
- **用途**：成本控制，配合 cost_guard 阈值

### 5. agent_run_errors_total（Counter）

```
agent_run_errors_total{error_type="budget_exceeded|preflight_blocked|llm_timeout|unknown"}
```

- **含义**：agent run 失败分类计数
- **告警阈值**：5min 内 > 10 次 llm_timeout 告警

---

## /health/detailed 扩展建议

在现有 `/health/detailed` 端点中追加 `agent` 检查项（由 api-biz 实现）：

```json
{
  "agent": {
    "status": "ok",
    "active_runs": 3,
    "stale_runs": 0
  }
}
```

**stale_runs** = status='running' 且 started_at < NOW() - INTERVAL '30 minutes' 的 run 数量，
表示可能卡死的任务，需要人工介入。

SQL：
```sql
SELECT COUNT(*) FROM agent_runs
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '30 minutes';
```

---

## Grafana Dashboard 扩展

当前 `monitoring/grafana-dashboard.json` 只包含已实现的 API 和队列指标。
等 `agent_*` 指标真正暴露到 `/metrics` 后，再追加 "Agent Runtime" row，包含以下 panel：

| Panel | 查询 | 类型 |
|-------|------|------|
| Active Runs | `agent_runs_active` | Stat |
| Run Duration p95 | `histogram_quantile(0.95, agent_run_duration_seconds_bucket)` | Time series |
| Events/Run | `agent_events_per_run` | Histogram |
| Credits Spent | `rate(agent_credits_spent_total[5m])` | Time series |
| Error Rate | `rate(agent_run_errors_total[5m])` | Time series |

---

## 索引覆盖说明（migration 018）

migration 018 新增的两个索引对应以下高频查询：

| 索引 | 覆盖查询 |
|------|---------|
| `idx_agent_events_run_created_desc` | `SELECT ... FROM agent_events WHERE run_id=? ORDER BY created_at DESC LIMIT N`（前端轮询最新事件） |
| `idx_agent_runs_project_user_created` | `SELECT ... FROM agent_runs WHERE project_id=? AND user_id=? ORDER BY started_at DESC`（项目历史 run 列表） |

原有 `idx_agent_events_run_created`（ASC）保留，用于顺序回放场景。
