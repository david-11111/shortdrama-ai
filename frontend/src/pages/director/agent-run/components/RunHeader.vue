<template>
  <header class="run-header">
    <div class="run-heading">
      <p class="kicker">ShortDrama Agent</p>
      <h1>{{ title }}</h1>
      <p class="meta">
        <span>{{ projectName }}</span>
        <span>run_id: {{ shortRunId }}</span>
        <span>phase: {{ run?.current_phase || 'waiting' }}</span>
      </p>
    </div>
    <div class="run-status">
      <span class="status-pill" :class="`status-${run?.status || 'unknown'}`">{{ run?.status || 'unknown' }}</span>
      <span class="mode-pill">{{ run?.mode || 'step' }}</span>
    </div>
  </header>

  <section class="budget-strip">
    <div>
      <span>预算上限</span>
      <strong>{{ budget?.allowed_max_credits ?? 0 }}</strong>
    </div>
    <div>
      <span>预计最大</span>
      <strong>{{ budget?.estimated_max_credits ?? 0 }}</strong>
    </div>
    <div>
      <span>已预留</span>
      <strong>{{ budget?.reserved_credits ?? 0 }}</strong>
    </div>
    <div>
      <span>已消耗</span>
      <strong>{{ budget?.spent_credits ?? 0 }}</strong>
    </div>
    <div>
      <span>剩余</span>
      <strong>{{ budget?.remaining_run_budget ?? 0 }}</strong>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRunSnapshot } from '@/api/director'

const props = defineProps<{
  snapshot: AgentRunSnapshot | null
}>()

const run = computed(() => props.snapshot?.run)
const budget = computed(() => props.snapshot?.budget)
const title = computed(() => run.value?.goal || '等待执行目标')
const projectName = computed(() => props.snapshot?.project.name || run.value?.project_id || '未知项目')
const shortRunId = computed(() => {
  const id = run.value?.run_id || ''
  return id ? `${id.slice(0, 8)}...${id.slice(-6)}` : 'pending'
})
</script>

<style scoped>
.run-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 26px 18px;
  border: 1px solid #f97316;
  border-radius: 7px 7px 0 0;
  background: #0b0b0c;
}

.kicker {
  margin: 0 0 8px;
  color: #fb923c;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  color: #f8fafc;
  font-size: 26px;
  line-height: 1.25;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 12px 0 0;
  color: #a1a1aa;
  font-size: 13px;
}

.meta span {
  padding-right: 10px;
  border-right: 1px solid #3f3f46;
}

.meta span:last-child {
  border-right: 0;
}

.run-status {
  display: flex;
  gap: 8px;
  white-space: nowrap;
}

.status-pill,
.mode-pill {
  border-radius: 999px;
  padding: 7px 11px;
  font-size: 12px;
  font-weight: 700;
}

.status-pill {
  background: #1e293b;
  color: #bfdbfe;
}

.status-completed,
.status-done {
  background: #dcfce7;
  color: #166534;
}

.status-failed,
.status-blocked {
  background: #fee2e2;
  color: #991b1b;
}

.status-running,
.status-dispatching {
  background: #dbeafe;
  color: #1d4ed8;
}

.mode-pill {
  border: 1px solid #3f3f46;
  background: #18181b;
  color: #fbbf24;
}

.budget-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0;
  background: #0b0b0c;
  border-right: 1px solid #f97316;
  border-bottom: 1px solid #f97316;
  border-left: 1px solid #f97316;
  border-radius: 0 0 7px 7px;
}

.budget-strip div {
  background: #0b0b0c;
  padding: 14px 18px;
  border-right: 1px solid #27272a;
}

.budget-strip div:last-child {
  border-right: 0;
}

.budget-strip span {
  display: block;
  margin-bottom: 5px;
  color: #71717a;
  font-size: 12px;
}

.budget-strip strong {
  color: #e5e7eb;
  font-size: 18px;
}

@media (max-width: 860px) {
  .run-header {
    flex-direction: column;
    padding: 22px;
  }

  .budget-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
