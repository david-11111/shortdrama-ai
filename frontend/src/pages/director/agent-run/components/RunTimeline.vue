<template>
  <section class="panel">
    <div class="panel-title">
      <h2>实时执行</h2>
      <div class="filters">
        <button
          v-for="item in filters"
          :key="item.value"
          type="button"
          :class="{ active: modelValue === item.value }"
          @click="$emit('update:modelValue', item.value)"
        >
          {{ item.label }}
        </button>
      </div>
    </div>

    <div ref="scroller" class="timeline">
      <button
        v-for="event in visibleEvents"
        :key="event.id"
        type="button"
        class="event"
        :class="[`event-${event.level || event.event_type || 'info'}`]"
        @click="$emit('inspect', event)"
      >
        <span class="event-icon">{{ iconFor(event.event_type || event.level) }}</span>
        <span class="event-main">
          <strong>{{ event.text || event.title || event.event_type }}</strong>
          <small>{{ formatTime(event.time || event.created_at) }} · {{ event.source || event.node_id || 'agent' }}</small>
        </span>
        <span class="event-type">{{ event.event_type || event.level }}</span>
      </button>
      <div v-if="!visibleEvents.length" class="empty">还没有执行事件</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { AgentEvent, AgentRunSnapshotStreamItem } from '@/api/director'

export type TimelineEvent = (Partial<AgentRunSnapshotStreamItem> & Partial<AgentEvent>) & {
  id: string
  text?: string
  level?: string
  time?: string | null
  title?: string
  created_at?: string
  node_id?: string
}

const props = defineProps<{
  events: TimelineEvent[]
  modelValue: string
}>()

defineEmits<{
  'update:modelValue': [value: string]
  inspect: [event: TimelineEvent]
}>()

const scroller = ref<HTMLElement | null>(null)

const filters = [
  { label: '全部', value: 'all' },
  { label: '判断', value: 'decision' },
  { label: '工具', value: 'tool' },
  { label: '风险', value: 'risk' },
  { label: '产物', value: 'artifact' },
]

const visibleEvents = computed(() => {
  if (props.modelValue === 'all') return props.events
  if (props.modelValue === 'tool') {
    return props.events.filter((event) => ['tool_call', 'tool_result'].includes(String(event.event_type)))
  }
  return props.events.filter((event) => String(event.event_type || event.level) === props.modelValue)
})

watch(
  () => props.events.length,
  async () => {
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  },
)

function iconFor(type?: string) {
  const icons: Record<string, string> = {
    decision: 'D',
    tool_call: 'T',
    tool_result: '✓',
    artifact: '#',
    writeback: '↳',
    risk: '!',
    error: '×',
    warning: '!',
    success: '✓',
  }
  return icons[type || ''] || '·'
}

function formatTime(value?: string | null) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  background: #0b0b0c;
  border: 1px solid #3f3f46;
  border-radius: 7px;
  overflow: hidden;
}

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid #27272a;
}

h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 16px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.filters button {
  border: 1px solid #3f3f46;
  border-radius: 6px;
  background: #111113;
  padding: 5px 9px;
  color: #d4d4d8;
  cursor: pointer;
}

.filters button.active {
  border-color: #f97316;
  background: #431407;
  color: #fed7aa;
}

.timeline {
  max-height: 620px;
  overflow: auto;
  padding: 8px;
}

.event {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  border: 0;
  border-radius: 7px;
  background: #0b0b0c;
  padding: 10px;
  text-align: left;
  cursor: pointer;
}

.event:hover {
  background: #18181b;
}

.event-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #27272a;
  color: #e5e7eb;
  font-weight: 800;
}

.event-main {
  min-width: 0;
}

.event-main strong,
.event-main small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-main strong {
  color: #f8fafc;
  font-size: 13px;
}

.event-main small,
.event-type {
  color: #a1a1aa;
  font-size: 12px;
}

.event-error .event-icon {
  background: #fee2e2;
  color: #991b1b;
}

.event-warning .event-icon,
.event-risk .event-icon {
  background: #fef3c7;
  color: #92400e;
}

.event-success .event-icon,
.event-artifact .event-icon,
.event-writeback .event-icon {
  background: #dcfce7;
  color: #166534;
}

.empty {
  padding: 32px 12px;
  color: #71717a;
  text-align: center;
}
</style>
