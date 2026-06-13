<template>
  <section class="panel">
    <div class="panel-title">
      <h2>制作流程</h2>
      <span>{{ completedCount }}/{{ nodes.length }}</span>
    </div>
    <div class="node-list">
      <button
        v-for="node in nodes"
        :key="node.id"
        type="button"
        class="node"
        :class="[`node-${node.status}`, { active: node.id === selectedNodeId }]"
        @click="$emit('select', node.id)"
      >
        <span class="node-index">{{ node.index ?? '-' }}</span>
        <span class="node-body">
          <strong>{{ node.title }}</strong>
          <small>{{ node.summary || node.status }}</small>
        </span>
        <span class="node-progress">{{ node.progress }}%</span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRunSnapshotNode } from '@/api/director'

const props = defineProps<{
  nodes: AgentRunSnapshotNode[]
  selectedNodeId: string
}>()

defineEmits<{
  select: [nodeId: string]
}>()

const completedCount = computed(() =>
  props.nodes.filter((node) => ['completed', 'done'].includes(node.status)).length,
)
</script>

<style scoped>
.panel {
  background: #0b0b0c;
  border: 1px solid #3f3f46;
  border-radius: 7px;
  overflow: hidden;
}

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid #27272a;
}

h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 16px;
}

.panel-title span {
  color: #a1a1aa;
  font-size: 13px;
}

.node-list {
  display: grid;
}

.node {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 48px;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 13px 16px;
  border: 0;
  border-bottom: 1px solid #18181b;
  background: #0b0b0c;
  text-align: left;
  cursor: pointer;
}

.node:last-child {
  border-bottom: 0;
}

.node:hover,
.node.active {
  background: #18181b;
}

.node-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #27272a;
  color: #d4d4d8;
  font-weight: 700;
  font-size: 12px;
}

.node-body {
  min-width: 0;
}

.node-body strong,
.node-body small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-body strong {
  color: #e5e7eb;
  font-size: 14px;
}

.node-body small {
  margin-top: 4px;
  color: #a1a1aa;
  font-size: 12px;
}

.node-progress {
  color: #a1a1aa;
  font-size: 12px;
  text-align: right;
}

.node-running .node-index {
  background: #1d4ed8;
  color: #dbeafe;
}

.node-completed .node-index,
.node-done .node-index {
  background: #166534;
  color: #dcfce7;
}

.node-failed .node-index,
.node-blocked .node-index {
  background: #991b1b;
  color: #fee2e2;
}
</style>
