<template>
  <div class="progress-card">
    <div class="progress-header">
      <span class="progress-icon pulse"></span>
      <span class="progress-label">{{ message.progressLabel || message.content }}</span>
      <span class="progress-actor">{{ actorLabel }}</span>
    </div>
    <div v-if="hasProgress" class="progress-bar-wrap">
      <div class="progress-bar" :style="{ width: progressPct + '%' }"></div>
      <span class="progress-text">{{ message.progress }}/{{ message.progressTotal }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '../composables/useChatMessages'

const props = defineProps<{ message: ChatMessage }>()

const actorLabel = computed(() => {
  const actor = (props.message.actor || '').toLowerCase()
  if (actor === 'seedance') return 'Seedance'
  if (actor === 'seedream') return 'Seedream'
  return actor || 'Provider'
})

const hasProgress = computed(() =>
  props.message.progress != null && props.message.progressTotal != null && props.message.progressTotal > 0,
)

const progressPct = computed(() => {
  if (!hasProgress.value) return 0
  return Math.min(100, Math.round(((props.message.progress || 0) / (props.message.progressTotal || 1)) * 100))
})
</script>

<style scoped>
.progress-card {
  display: grid;
  gap: 10px;
  max-width: 80%;
  border: 1px solid rgba(245, 158, 11, 0.25);
  border-radius: 12px;
  background: #161b22;
  padding: 14px 18px;
  animation: slide-up 0.3s ease-out both;
}

.progress-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-icon {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #f59e0b;
}

.progress-icon.pulse {
  animation: pulse-glow 2s infinite;
}

.progress-label {
  color: #e6edf3;
  font-size: 13px;
}

.progress-actor {
  color: #8b949e;
  font-size: 12px;
  margin-left: auto;
}

.progress-bar-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-bar-wrap::before {
  content: '';
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #21262d;
  position: relative;
}

.progress-bar {
  position: absolute;
  height: 6px;
  border-radius: 3px;
  background: linear-gradient(90deg, #58a6ff, #a371f7);
  transition: width 0.4s ease;
}

.progress-bar-wrap {
  position: relative;
  height: 6px;
  border-radius: 3px;
  background: #21262d;
}

.progress-bar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
}

.progress-text {
  position: absolute;
  right: 0;
  top: -18px;
  color: #8b949e;
  font-size: 11px;
}

@keyframes slide-up {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(245, 158, 11, 0); }
}
</style>
