<template>
  <div class="step-card" :class="[message.stepStatus]">
    <div class="step-header">
      <span class="step-icon">{{ statusIcon }}</span>
      <strong class="step-title">{{ message.stepTitle }}</strong>
      <span class="step-actor">{{ actorLabel }}</span>
    </div>
    <p v-if="message.stepDetail" class="step-detail">{{ message.stepDetail }}</p>
    <ul v-if="message.stepItems?.length" class="step-items">
      <li v-for="(item, i) in message.stepItems" :key="i" :class="item.status">
        <span class="item-icon">{{ itemIcon(item.status) }}</span>
        {{ item.label }}
      </li>
    </ul>
    <time class="step-time">{{ timeLabel }}</time>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '../composables/useChatMessages'

const props = defineProps<{ message: ChatMessage }>()

const statusIcon = computed(() => {
  if (props.message.stepStatus === 'done') return '\u2713'
  if (props.message.stepStatus === 'error') return '!'
  return '\u25B6'
})

const actorLabel = computed(() => {
  const actor = (props.message.actor || '').toLowerCase()
  if (actor === 'deepseek') return 'DeepSeek'
  if (actor === 'executor') return '\u6267\u884C\u5668'
  return 'Agent'
})

function itemIcon(status: string) {
  if (status === 'done') return '\u2713'
  if (status === 'running') return '\u25B6'
  return '\u25CB'
}

const timeLabel = computed(() => {
  if (!props.message.timestamp) return ''
  const d = new Date(props.message.timestamp)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
})
</script>

<style scoped>
.step-card {
  display: grid;
  gap: 8px;
  max-width: 90%;
  border: 1px solid #30363d;
  border-radius: 12px;
  background: #161b22;
  padding: 14px 18px;
  animation: slide-up 0.3s ease-out both;
}

.step-card.done {
  border-color: rgba(63, 185, 80, 0.3);
}

.step-card.running {
  border-color: rgba(88, 166, 255, 0.3);
}

.step-card.error {
  border-color: rgba(248, 81, 73, 0.3);
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.step-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
}

.done .step-icon {
  background: rgba(63, 185, 80, 0.15);
  color: #3fb950;
}

.running .step-icon {
  background: rgba(88, 166, 255, 0.15);
  color: #58a6ff;
}

.error .step-icon {
  background: rgba(248, 81, 73, 0.15);
  color: #f85149;
}

.step-title {
  color: #e6edf3;
  font-size: 14px;
}

.step-actor {
  color: #8b949e;
  font-size: 12px;
  margin-left: auto;
}

.step-detail {
  margin: 0;
  color: #8b949e;
  font-size: 13px;
  line-height: 1.5;
}

.step-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.step-items li {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #8b949e;
  font-size: 13px;
}

.step-items li.done {
  color: #3fb950;
}

.step-items li.running {
  color: #58a6ff;
}

.item-icon {
  font-size: 11px;
}

.step-time {
  color: #6e7681;
  font-size: 11px;
}

@keyframes slide-up {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
