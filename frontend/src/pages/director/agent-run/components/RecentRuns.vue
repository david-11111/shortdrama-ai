<template>
  <section class="recent-panel">
    <h2>最近执行</h2>
    <div v-if="runs.length" class="run-list">
      <button v-for="run in runs" :key="run.run_id" type="button" @click="$emit('open', run.run_id)">
        <span class="dot" :class="`dot-${statusTone(run.status)}`"></span>
        <strong>{{ run.goal || `Run ${shortId(run.run_id)}` }}</strong>
        <em>{{ statusLabel(run.status) }}</em>
        <small>{{ formatTime(run.created_at) }}</small>
        <small>{{ run.credits || 0 }} 积分</small>
      </button>
    </div>
    <p v-else>暂无最近执行</p>
  </section>
</template>

<script setup lang="ts">
export interface RecentRunItem {
  run_id: string
  project_id: string
  project_name?: string
  goal: string
  status: string
  mode?: string
  created_at: string
  credits?: number
}

defineProps<{
  runs: RecentRunItem[]
}>()

defineEmits<{
  open: [runId: string]
}>()

function statusTone(status: string) {
  if (['completed', 'done'].includes(status)) return 'success'
  if (['failed', 'blocked', 'cancelled'].includes(status)) return 'error'
  return 'running'
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    completed: '完成',
    done: '完成',
    failed: '失败',
    blocked: '阻断',
    running: '运行中',
    dispatching: '派发中',
    waiting_approval: '待确认',
    created: '已创建',
    queued: '排队中',
  }
  return labels[status] || status || '未知'
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function shortId(id: string) {
  return id ? id.slice(0, 8) : ''
}
</script>

<style scoped>
.recent-panel {
  width: min(600px, 100%);
  margin: 0 auto;
  padding-top: 18px;
}

h2 {
  margin: 0 0 10px;
  color: #e6edf3;
  font-size: 13px;
  font-weight: 650;
}

.run-list {
  display: grid;
  gap: 2px;
}

button {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) 70px 108px 70px;
  gap: 10px;
  align-items: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #8b949e;
  padding: 7px 8px;
  text-align: left;
  cursor: pointer;
}

button:hover {
  background: #161b22;
}

strong,
small,
em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

strong {
  color: #e6edf3;
  font-size: 12px;
}

em,
small {
  font-size: 11px;
  font-style: normal;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
}

.dot-success {
  background: #3fb950;
}

.dot-running {
  background: #d29922;
}

.dot-error {
  background: #f85149;
}

p {
  color: #8b949e;
  text-align: center;
}

@media (max-width: 720px) {
  button {
    grid-template-columns: 18px minmax(0, 1fr) 64px;
  }

  button small {
    display: none;
  }
}
</style>
