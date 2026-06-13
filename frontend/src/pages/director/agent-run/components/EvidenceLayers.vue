<template>
  <section class="panel evidence-layers">
    <div class="panel-title">
      <div>
        <h2>流程证据账本</h2>
        <p>把后台日志、项目大脑、生产账本和技法证据挂到当前 run 下。</p>
      </div>
      <span>{{ totalCount }} 条</span>
    </div>

    <div class="layer-tabs">
      <button
        v-for="layer in orderedLayers"
        :key="layer.id"
        type="button"
        :class="{ active: activeLayerId === layer.id }"
        @click="activeLayerId = layer.id"
      >
        <strong>{{ layerTitle(layer.id, layer.title) }}</strong>
        <small>{{ layer.count }}</small>
      </button>
    </div>

    <div v-if="activeLayer" class="layer-body">
      <div class="layer-summary">
        <strong>{{ layerTitle(activeLayer.id, activeLayer.title) }}</strong>
        <span>{{ activeLayer.summary || '暂无摘要' }}</span>
      </div>

      <div class="layer-items">
        <button
          v-for="(item, index) in previewItems"
          :key="`${activeLayer.id}-${index}`"
          type="button"
          class="layer-item"
          @click="$emit('inspect', { layerId: activeLayer.id, item, index })"
        >
          <span>{{ index + 1 }}</span>
          <strong>{{ itemTitle(item) }}</strong>
          <small>{{ itemDetail(item) }}</small>
        </button>
        <div v-if="!previewItems.length" class="empty">这一层还没有证据。</div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AgentRunSnapshotEvidenceLayer } from '@/api/director'

const props = defineProps<{
  layers?: Record<string, AgentRunSnapshotEvidenceLayer>
}>()

defineEmits<{
  inspect: [payload: { layerId: string; item: unknown; index: number }]
}>()

const layerOrder = [
  'state_machine_flow',
  'agent_execution_log',
  'brain_trace',
  'detailed_flow_ledger',
  'raw_read_list',
  'production_stream_terminal',
  'progress_ledger',
  'creative_technique_ledger',
]

const layerLabels: Record<string, string> = {
  state_machine_flow: '状态机',
  agent_execution_log: '执行日志',
  brain_trace: '项目大脑',
  detailed_flow_ledger: '详细流程',
  raw_read_list: '读取清单',
  production_stream_terminal: '生产终端',
  progress_ledger: '进度账本',
  creative_technique_ledger: '技法账本',
}

const activeLayerId = ref('state_machine_flow')

const orderedLayers = computed(() => {
  const layers = props.layers || {}
  const ordered = layerOrder.map((id) => layers[id]).filter(Boolean)
  const rest = Object.values(layers).filter((layer) => !layerOrder.includes(layer.id))
  return [...ordered, ...rest]
})

const activeLayer = computed(() =>
  orderedLayers.value.find((layer) => layer.id === activeLayerId.value) || orderedLayers.value[0] || null,
)

const previewItems = computed(() => activeLayer.value?.items || [])

const totalCount = computed(() =>
  orderedLayers.value.reduce((total, layer) => total + Number(layer.count || 0), 0),
)

watch(
  orderedLayers,
  (layers) => {
    if (layers.length && !layers.some((layer) => layer.id === activeLayerId.value)) {
      activeLayerId.value = layers[0].id
    }
  },
  { immediate: true },
)

function layerTitle(id: string, fallback?: string) {
  return layerLabels[id] || fallback || id
}

function itemTitle(item: unknown) {
  const row = unwrap(item)
  return String(
    row.title ||
      row.phase ||
      row.event_type ||
      row.task_type ||
      row.label ||
      row.kind ||
      row.node_title ||
      row.path ||
      '证据项',
  )
}

function itemDetail(item: unknown) {
  const row = unwrap(item)
  return String(
    row.detail ||
      row.summary ||
      row.decision_summary ||
      row.output_summary ||
      row.decision ||
      row.value ||
      row.status ||
      row.updated_at ||
      '',
  )
}

function unwrap(item: unknown): Record<string, any> {
  if (!item || typeof item !== 'object') return {}
  const row = item as Record<string, any>
  if (row.data && typeof row.data === 'object') return row.data as Record<string, any>
  return row
}
</script>

<style scoped>
.panel {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  min-height: 0;
  height: 100%;
  background: #0b0b0c;
  border: 1px solid #3f3f46;
  border-radius: 7px;
  overflow: hidden;
}

.panel-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid #27272a;
}

h2,
p {
  margin: 0;
}

h2 {
  color: #f8fafc;
  font-size: 16px;
}

p {
  margin-top: 5px;
  color: #a1a1aa;
  font-size: 12px;
}

.panel-title span {
  color: #fb923c;
  font-size: 12px;
  white-space: nowrap;
}

.layer-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid #27272a;
}

.layer-tabs button {
  min-width: 0;
  border: 0;
  border-right: 1px solid #18181b;
  background: #0b0b0c;
  padding: 10px 8px;
  text-align: left;
  cursor: pointer;
}

.layer-tabs button.active,
.layer-tabs button:hover {
  background: #18181b;
}

.layer-tabs strong,
.layer-tabs small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.layer-tabs strong {
  color: #e5e7eb;
  font-size: 12px;
}

.layer-tabs small {
  margin-top: 4px;
  color: #fb923c;
  font-size: 11px;
}

.layer-body {
  min-height: 0;
  overflow: auto;
  padding: 14px;
}

.layer-summary {
  display: grid;
  gap: 5px;
  margin-bottom: 12px;
}

.layer-summary strong {
  color: #f8fafc;
  font-size: 14px;
}

.layer-summary span {
  color: #a1a1aa;
  font-size: 12px;
}

.layer-items {
  display: grid;
  gap: 7px;
}

.layer-item {
  display: grid;
  grid-template-columns: 26px minmax(100px, 0.42fr) minmax(0, 1fr);
  gap: 9px;
  align-items: center;
  border: 1px solid #27272a;
  border-radius: 7px;
  background: #050505;
  padding: 9px 10px;
  text-align: left;
  cursor: pointer;
}

.layer-item:hover {
  border-color: #f97316;
}

.layer-item span {
  color: #71717a;
  font-size: 12px;
}

.layer-item strong,
.layer-item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.layer-item strong {
  color: #e5e7eb;
  font-size: 12px;
}

.layer-item small {
  color: #a1a1aa;
  font-size: 12px;
}

.empty {
  padding: 18px 8px;
  color: #71717a;
  text-align: center;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .layer-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .layer-item {
    grid-template-columns: 24px minmax(0, 1fr);
  }

  .layer-item small {
    grid-column: 2;
  }
}
</style>
