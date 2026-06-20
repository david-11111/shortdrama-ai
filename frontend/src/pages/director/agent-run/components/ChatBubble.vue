<template>
  <article class="bubble" :class="[message.role, { streaming: message.streaming }]">
    <div v-if="message.role === 'assistant'" class="bubble-meta">
      <span class="actor-badge">{{ actorLabel }}</span>
    </div>
    <div class="bubble-body">
      <div
        v-if="message.role === 'assistant'"
        class="bubble-content"
        v-html="renderedContent"
      ></div>
      <div v-else class="bubble-content plain">{{ message.content }}</div>
      <span v-if="message.streaming" class="typing-cursor"></span>
    </div>
    <time class="bubble-time">{{ timeLabel }}</time>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import type { ChatMessage } from '../composables/useChatMessages'

const props = defineProps<{ message: ChatMessage }>()

const actorLabel = computed(() => {
  const actor = (props.message.actor || '').toLowerCase()
  if (actor === 'deepseek') return 'DeepSeek'
  if (actor === 'executor') return '执行器'
  if (actor === 'seedream') return 'Seedream'
  if (actor === 'joy-echo' || actor === 'joy_echo' || actor === 'joyai-echo' || actor === 'joyai_echo') return 'Joy-Echo'
  if (actor === 'ltx2.3' || actor === 'ltx') return 'LTX 2.3'
  if (actor === 'seedance') return 'Seedance'
  return 'Agent'
})

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  return marked.parse(props.message.content, { async: false }) as string
})

const timeLabel = computed(() => {
  if (!props.message.timestamp) return ''
  const d = new Date(props.message.timestamp)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`
})
</script>

<style scoped>
.bubble {
  display: grid;
  gap: 6px;
  max-width: 85%;
  animation: slide-up 0.3s ease-out both;
}

.bubble.user {
  justify-self: end;
}

.bubble.assistant {
  justify-self: start;
}

.bubble-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.actor-badge {
  color: #58a6ff;
  font-size: 12px;
  font-weight: 600;
}

.bubble-body {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  border-radius: 16px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.6;
}

.user .bubble-body {
  border-radius: 16px 16px 4px 16px;
  background: #1f6feb;
  color: #ffffff;
}

.assistant .bubble-body {
  border-radius: 16px 16px 16px 4px;
  background: #161b22;
  border: 1px solid #30363d;
  color: #e6edf3;
}

.bubble-content {
  min-width: 0;
  word-break: break-word;
}

.bubble-content.plain {
  white-space: pre-wrap;
}

.bubble-content :deep(p) {
  margin: 0 0 8px;
}

.bubble-content :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble-content :deep(code) {
  background: rgba(110, 118, 129, 0.2);
  border-radius: 4px;
  padding: 2px 5px;
  font-size: 13px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.bubble-content :deep(pre) {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
}

.bubble-content :deep(ul),
.bubble-content :deep(ol) {
  margin: 4px 0;
  padding-left: 20px;
}

.typing-cursor::after {
  content: '\2588';
  animation: typing-blink 0.8s step-end infinite;
  color: #58a6ff;
  font-size: 13px;
}

.bubble-time {
  color: #6e7681;
  font-size: 11px;
  padding: 0 4px;
}

.user .bubble-time {
  text-align: right;
}

@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes typing-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
