<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useAgentEvents } from '@/composables/useAgentEvents'

const session = inject<any>('session')
const collapsed = ref(false)
const expandedEventIds = ref(new Set<string>())
const agentEvents = useAgentEvents()

const projectId = computed(() => String(session?.projectId?.value || '').trim())
const events = computed(() => {
  const rows = Array.isArray(agentEvents.events.value) ? agentEvents.events.value : []
  return [...rows].sort((a: any, b: any) => toMs(b.created_at) - toMs(a.created_at)).slice(0, 200)
})
const currentRunId = computed(() => String(events.value[0]?.run_id || ''))
const currentRunStatus = computed(() => {
  const runId = currentRunId.value
  const scoped = runId ? events.value.filter((item: any) => String(item.run_id || '') === runId) : events.value
  if (scoped.some((item: any) => item.event_type === 'error' || item.status === 'failed')) return 'failed'
  if (scoped.some((item: any) => item.status === 'blocked' || item.event_type === 'risk')) return 'blocked'
  if (scoped.some((item: any) => ['running', 'pending', 'queued', 'created'].includes(String(item.status || '')))) return 'running'
  if (scoped.length) return 'completed'
  return 'waiting'
})
const budget = computed(() => {
  let spent = 0
  let allowed = 0
  for (const event of events.value as any[]) {
    const meta = event.meta || event.data || {}
    spent = maxNumber(spent, meta.spent_credits, meta.credits_spent, meta.consumed_credits)
    allowed = maxNumber(allowed, meta.allowed_max_credits, meta.estimated_max_credits, meta.budget, meta.credits)
  }
  return { spent, allowed }
})

function maxNumber(current: number, ...values: any[]) {
  return values.reduce((next, value) => {
    const num = Number(value)
    return Number.isFinite(num) && num > next ? num : next
  }, current)
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
}

function toggleEvent(id: string) {
  const next = new Set(expandedEventIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedEventIds.value = next
}

function isExpanded(id: string) {
  return expandedEventIds.value.has(id)
}

function eventIcon(type = '') {
  const icons: Record<string, string> = {
    tool_call: '⚙',
    tool_result: '✓',
    error: '✕',
    risk: '⚠',
    writeback: '↩',
    artifact: '◆',
    decision: '◇',
    trace: '·',
  }
  return icons[type] || '·'
}

function eventSummary(event: any) {
  const meta = event?.meta || event?.data || {}
  if (event?.title || event?.detail) return [event.title, event.detail].filter(Boolean).join('：')
  if (meta.reason) return String(meta.reason)
  if (meta.action || meta.tool) return [meta.tool, meta.action].filter(Boolean).join(' / ')
  if (meta.field || meta.shot_index) return `shot=${meta.shot_index || '-'} field=${meta.field || '-'}`
  if (meta.url) return String(meta.url)
  return String(event?.event_type || '执行事件')
}

function jsonPayload(event: any) {
  return JSON.stringify(event?.meta || event?.data || event || {}, null, 2)
}

function formatTime(value: any) {
  const ms = toMs(value)
  if (!ms) return '-'
  return new Date(ms).toLocaleTimeString()
}

function toMs(value: any) {
  if (!value) return 0
  if (typeof value === 'number') return value
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? ms : 0
}

async function resetProjectSubscription(nextProjectId: string, previousProjectId = '') {
  if (previousProjectId) agentEvents.unsubscribe()
  agentEvents.clear()
  expandedEventIds.value = new Set()
  if (!nextProjectId) return
  agentEvents.subscribe(nextProjectId)
  await agentEvents.loadHistory(nextProjectId, { limit: 200 })
}

onMounted(() => {
  if (projectId.value) void resetProjectSubscription(projectId.value)
})

watch(
  projectId,
  (value, previous) => {
    if (value === previous) return
    void resetProjectSubscription(value, previous)
  },
)
</script>

<template>
  <section class="agent-log-panel" :class="{ collapsed }" aria-label="Agent 执行日志">
    <button class="agent-log-header" type="button" @click="toggleCollapsed">
      <div>
        <p class="eyebrow">Agent Timeline</p>
        <h3>Agent 执行日志</h3>
      </div>
      <div class="run-summary">
        <span class="run-status" :class="`status-${currentRunStatus}`">{{ currentRunStatus }}</span>
        <code>{{ currentRunId || 'no-run' }}</code>
        <span class="toggle-mark">{{ collapsed ? '展开' : '收起' }}</span>
      </div>
    </button>

    <div v-show="!collapsed" class="agent-log-body">
      <div v-if="events.length" class="timeline">
        <article v-for="event in events" :key="event.id" class="timeline-event" :class="`event-${event.event_type}`">
          <button class="event-button" type="button" @click="toggleEvent(event.id)">
            <time>{{ formatTime(event.created_at) }}</time>
            <span class="event-icon">{{ eventIcon(event.event_type) }}</span>
            <span class="event-text">{{ eventSummary(event) }}</span>
            <span class="event-type">{{ event.event_type }}</span>
          </button>
          <pre v-if="isExpanded(event.id)" class="event-json">{{ jsonPayload(event) }}</pre>
        </article>
      </div>
      <div v-else class="empty-state">
        <strong>{{ projectId ? '暂无 Agent 事件' : '请先选择项目' }}</strong>
        <p>历史事件加载后会显示在这里；新的 execution_event 会通过 WebSocket 实时追加。</p>
      </div>
    </div>

    <footer v-show="!collapsed" class="agent-log-footer">
      <span>已消耗积分 / 预算</span>
      <strong>{{ budget.spent }} / {{ budget.allowed || '-' }}</strong>
    </footer>
  </section>
</template>

<style scoped>
.agent-log-panel {
  margin-bottom: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.agent-log-header {
  width: 100%;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg);
  color: var(--color-text);
  padding: 0.9rem 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  text-align: left;
  cursor: pointer;
}

.collapsed .agent-log-header {
  border-bottom: 0;
}

.eyebrow {
  margin: 0 0 0.2rem;
  color: var(--color-primary);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.agent-log-header h3 {
  margin: 0;
  font-size: 1.02rem;
}

.run-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.run-summary code {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.run-status,
.toggle-mark,
.event-type {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.16rem 0.5rem;
  font-size: 0.7rem;
  color: var(--color-text-secondary);
  background: var(--color-bg-secondary);
}

.status-running {
  color: var(--color-primary);
  border-color: color-mix(in srgb, var(--color-primary) 45%, var(--color-border));
}

.status-completed {
  color: var(--color-success);
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
}

.status-failed,
.status-blocked {
  color: var(--color-error);
  border-color: color-mix(in srgb, var(--color-error) 45%, var(--color-border));
}

.agent-log-body {
  max-height: 520px;
  overflow: auto;
}

.timeline {
  padding: 0.4rem 1rem 1rem;
}

.timeline-event {
  position: relative;
  padding: 0.45rem 0 0.45rem 1.1rem;
}

.timeline-event::before {
  content: '';
  position: absolute;
  left: 0.35rem;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-border);
}

.event-button {
  position: relative;
  z-index: 1;
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  display: grid;
  grid-template-columns: 72px 28px minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 0.7rem;
  text-align: left;
  cursor: pointer;
}

.event-button:hover {
  border-color: color-mix(in srgb, var(--color-primary) 45%, var(--color-border));
}

.event-button time {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.event-icon {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-bg));
  color: var(--color-primary);
  font-weight: 800;
}

.event-error .event-icon {
  color: var(--color-error);
  background: color-mix(in srgb, var(--color-error) 14%, var(--color-bg));
}

.event-risk .event-icon {
  color: var(--color-warning);
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg));
}

.event-tool_result .event-icon,
.event-writeback .event-icon {
  color: var(--color-success);
  background: color-mix(in srgb, var(--color-success) 14%, var(--color-bg));
}

.event-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
}

.event-json {
  margin: 0.45rem 0 0;
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 72%, black);
  color: var(--color-text-secondary);
  overflow: auto;
  max-height: 260px;
  font-size: 0.72rem;
  line-height: 1.45;
}

.empty-state {
  padding: 1rem;
}

.empty-state strong {
  display: block;
  color: var(--color-text);
  font-size: 0.9rem;
}

.empty-state p {
  margin: 0.35rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.agent-log-footer {
  border-top: 1px solid var(--color-border);
  padding: 0.75rem 1rem;
  display: flex;
  justify-content: flex-end;
  gap: 0.65rem;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.agent-log-footer strong {
  color: var(--color-text);
}

@media (max-width: 760px) {
  .agent-log-header,
  .run-summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .event-button {
    grid-template-columns: 64px 28px minmax(0, 1fr);
  }

  .event-type {
    grid-column: 3;
    width: max-content;
  }
}
</style>
