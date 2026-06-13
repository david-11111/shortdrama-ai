<template>
  <aside v-if="open" class="drawer">
    <div class="drawer-header">
      <div>
        <p>{{ selectedNode?.title || '事件证据' }}</p>
        <h2>{{ drawerTitle }}</h2>
      </div>
      <button type="button" @click="$emit('close')">关闭</button>
    </div>

    <div class="drawer-body">
      <section v-if="selectedNode" class="summary">
        <dl>
          <div>
            <dt>状态</dt>
            <dd>{{ selectedNode.status }}</dd>
          </div>
          <div>
            <dt>进度</dt>
            <dd>{{ selectedNode.progress }}%</dd>
          </div>
          <div>
            <dt>任务</dt>
            <dd>{{ selectedNode.task_ids.length }}</dd>
          </div>
          <div>
            <dt>事件</dt>
            <dd>{{ selectedNode.event_ids.length }}</dd>
          </div>
        </dl>
        <p>{{ selectedNode.brain_summary || selectedNode.summary }}</p>
      </section>

      <section v-if="eventPayload">
        <h3>当前事件</h3>
        <div class="evidence-card">
          <p v-if="selectedEvent?.title"><strong>标题</strong><span>{{ selectedEvent.title }}</span></p>
          <p v-if="selectedEvent?.detail"><strong>详情</strong><span>{{ selectedEvent.detail }}</span></p>
          <p v-if="selectedEvent?.source"><strong>来源</strong><span>{{ selectedEvent.source }}</span></p>
          <p v-if="selectedEvent?.status"><strong>状态</strong><span>{{ selectedEvent.status }}</span></p>
        </div>
        <pre>{{ eventPayload }}</pre>
      </section>

      <section v-if="evidence">
        <h3>节点证据</h3>
        <div class="section-list">
          <article v-for="section in evidenceSections" :key="section.key" class="evidence-section">
            <div class="evidence-section-title">
              <strong>{{ section.label }}</strong>
              <span>{{ section.count }}</span>
            </div>
            <pre>{{ section.payload }}</pre>
          </article>
        </div>
      </section>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRunSnapshotNode } from '@/api/director'

const props = defineProps<{
  open: boolean
  selectedNode: AgentRunSnapshotNode | null
  evidence: Record<string, unknown> | null
  selectedEvent: Record<string, unknown> | null
}>()

defineEmits<{
  close: []
}>()

const drawerTitle = computed(() =>
  String(props.selectedEvent?.event_type || props.selectedEvent?.level || props.selectedNode?.summary || '查看执行证据'),
)

const eventPayload = computed(() =>
  props.selectedEvent ? JSON.stringify(props.selectedEvent, null, 2) : '',
)

const evidenceSections = computed(() => {
  const evidence = props.evidence || {}
  const sections = [
    ['state_ledger', '状态账本'],
    ['brain_trace', '大脑轨迹'],
    ['detailed_flow', '详细流程'],
    ['raw_reads', '原始读取清单'],
    ['tool_events', '工具事件'],
    ['tasks', '任务'],
    ['artifacts', '产物'],
    ['shots', '镜头'],
    ['backend_links', '后台定位'],
  ]
  return sections.map(([key, label]) => {
    const value = evidence[key]
    return {
      key,
      label,
      count: Array.isArray(value) ? value.length : value && typeof value === 'object' ? Object.keys(value).length : value ? 1 : 0,
      payload: JSON.stringify(value || (Array.isArray(value) ? [] : {}), null, 2),
    }
  })
})

const evidence = computed(() =>
  props.evidence && Object.keys(props.evidence).length ? props.evidence : null,
)
</script>

<style scoped>
.drawer {
  position: fixed;
  inset: 0 0 0 auto;
  z-index: 40;
  display: flex;
  width: min(560px, 100vw);
  flex-direction: column;
  border-left: 1px solid #f97316;
  background: #0b0b0c;
  box-shadow: -16px 0 40px rgba(15, 23, 42, 0.16);
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 20px;
  border-bottom: 1px solid #27272a;
}

.drawer-header p {
  margin: 0 0 6px;
  color: #fb923c;
  font-size: 12px;
}

.drawer-header h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 18px;
}

.drawer-header button {
  align-self: flex-start;
  border: 1px solid #3f3f46;
  border-radius: 6px;
  background: #111113;
  color: #e5e7eb;
  padding: 7px 10px;
  cursor: pointer;
}

.drawer-body {
  overflow: auto;
  padding: 20px;
}

.summary {
  border: 1px solid #3f3f46;
  border-radius: 8px;
  background: #111113;
  padding: 14px;
}

dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0 0 12px;
}

dt {
  color: #a1a1aa;
  font-size: 12px;
}

dd {
  margin: 4px 0 0;
  color: #f8fafc;
  font-weight: 700;
}

h3 {
  margin: 20px 0 10px;
  color: #f8fafc;
  font-size: 14px;
}

pre {
  overflow: auto;
  max-height: 380px;
  margin: 0;
  border-radius: 8px;
  background: #050505;
  color: #e5e7eb;
  padding: 14px;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.evidence-card {
  display: grid;
  gap: 8px;
  margin-bottom: 10px;
  border: 1px solid #27272a;
  border-radius: 8px;
  background: #111113;
  padding: 12px;
}

.evidence-card p {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  margin: 0;
  color: #d4d4d8;
  font-size: 12px;
}

.evidence-card strong {
  color: #fb923c;
}

.evidence-card span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.section-list {
  display: grid;
  gap: 12px;
}

.evidence-section {
  border: 1px solid #27272a;
  border-radius: 8px;
  overflow: hidden;
}

.evidence-section-title {
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
  background: #111113;
}

.evidence-section-title strong {
  color: #f8fafc;
  font-size: 13px;
}

.evidence-section-title span {
  color: #fb923c;
  font-size: 12px;
}
</style>
