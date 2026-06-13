<template>
  <section class="chat-stream">
    <header class="chat-header">
      <div>
        <p class="eyebrow">Agent Run</p>
        <h1>{{ goal || 'Agent Run' }}</h1>
        <p class="chat-status">{{ statusText }}</p>
      </div>
      <button type="button" @click="$emit('refresh')">刷新</button>
    </header>

    <div ref="scroller" class="messages">
      <div v-if="!messages.length" class="empty-state">
        <div class="empty-icon">AI</div>
        <strong>等待 Agent 响应</strong>
        <span>发送指令后，Agent 的回复将在这里流式展示</span>
      </div>

      <template v-for="msg in messages" :key="msg.id">
        <ChatBubble v-if="msg.type === 'text'" :message="msg" />
        <ChatStepCard v-else-if="msg.type === 'step_card'" :message="msg" />
        <ChatMediaCard v-else-if="msg.type === 'media_card'" :message="msg" />
        <ChatProgressBar v-else-if="msg.type === 'progress'" :message="msg" />
        <div v-else-if="msg.type === 'error'" class="error-card">
          <span class="error-icon">!</span>
          <p>{{ msg.content }}</p>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ChatMessage } from '../composables/useChatMessages'
import ChatBubble from './ChatBubble.vue'
import ChatStepCard from './ChatStepCard.vue'
import ChatMediaCard from './ChatMediaCard.vue'
import ChatProgressBar from './ChatProgressBar.vue'

const props = defineProps<{
  messages: ChatMessage[]
  goal: string
  status: string
}>()

defineEmits<{ refresh: [] }>()

const scroller = ref<HTMLElement | null>(null)

const statusText = (() => {
  const labels: Record<string, string> = {
    completed: '已完成',
    done: '已完成',
    failed: '失败',
    blocked: '阻断',
    cancelled: '已取消',
    answered: '已答复',
    running: '运行中',
    dispatching: '派发中',
    provider_waiting: '等待 Provider',
    queued: '排队中',
    created: '已创建',
    loading: '加载中',
  }
  return labels[props.status] || props.status || '加载中'
})()

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (scroller.value) {
      scroller.value.scrollTop = scroller.value.scrollHeight
    }
  },
)

watch(
  () => props.messages.find((m) => m.streaming)?.content,
  async () => {
    await nextTick()
    if (scroller.value) {
      const { scrollTop, scrollHeight, clientHeight } = scroller.value
      if (scrollHeight - scrollTop - clientHeight < 150) {
        scroller.value.scrollTop = scrollHeight
      }
    }
  },
)
</script>

<style scoped>
.chat-stream {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  height: 100%;
  background: #0d1117;
}

.chat-header {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  border-bottom: 1px solid #30363d;
  background: rgba(13, 17, 23, 0.96);
  padding: 20px 28px 18px;
  backdrop-filter: blur(8px);
}

.chat-header h1 {
  margin: 0;
  color: #e6edf3;
  font-size: 18px;
  line-height: 1.35;
}

.chat-header p {
  margin: 0;
}

.eyebrow {
  margin-bottom: 4px;
  color: #58a6ff;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.chat-status {
  margin-top: 4px;
  color: #8b949e;
  font-size: 13px;
}

.chat-header button {
  align-self: flex-start;
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #161b22;
  color: #e6edf3;
  padding: 8px 12px;
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.chat-header button:hover {
  border-color: #58a6ff;
}

.messages {
  display: grid;
  align-content: start;
  gap: 16px;
  overflow-y: auto;
  padding: 24px 28px 48px;
}

.empty-state {
  display: grid;
  justify-items: center;
  gap: 12px;
  margin-top: 80px;
  text-align: center;
}

.empty-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1f6feb, #a371f7);
  color: white;
  font-size: 14px;
  font-weight: 700;
}

.empty-state strong {
  color: #e6edf3;
  font-size: 16px;
}

.empty-state span {
  color: #8b949e;
  font-size: 13px;
}

.error-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 90%;
  border: 1px solid rgba(248, 81, 73, 0.3);
  border-radius: 12px;
  background: #161b22;
  padding: 14px 18px;
  animation: slide-up 0.3s ease-out both;
}

.error-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 24px;
  border-radius: 50%;
  background: rgba(248, 81, 73, 0.15);
  color: #f85149;
  font-size: 12px;
  font-weight: 700;
}

.error-card p {
  margin: 0;
  color: #ffb3ad;
  font-size: 13px;
  line-height: 1.5;
}

@keyframes slide-up {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 760px) {
  .chat-header {
    padding: 16px;
  }
  .messages {
    padding: 16px;
  }
}
</style>
