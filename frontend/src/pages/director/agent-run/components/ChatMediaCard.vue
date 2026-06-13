<template>
  <div class="media-card">
    <div class="media-header">
      <span class="media-icon">{{ message.mediaType === 'video' ? '\u25B6' : '\uD83D\uDDBC' }}</span>
      <strong>{{ message.mediaType === 'video' ? '\u89C6\u9891\u7247\u6BB5\u5DF2\u5199\u56DE' : '\u5173\u952E\u5E27\u5DF2\u5199\u56DE' }}</strong>
      <span class="media-actor">{{ actorLabel }}</span>
    </div>
    <p v-if="message.content" class="media-detail">{{ message.content }}</p>
    <div v-if="message.mediaUrls?.length" class="media-grid">
      <img
        v-for="(url, i) in message.mediaUrls.slice(0, 8)"
        :key="i"
        :src="url"
        loading="lazy"
        class="media-thumb"
        @click="openPreview(url)"
        @error="($event.target as HTMLImageElement).style.display='none'"
      />
    </div>
    <time class="media-time">{{ timeLabel }}</time>

    <teleport to="body">
      <div v-if="previewUrl" class="media-overlay" @click.self="previewUrl = ''">
        <div class="media-overlay-content">
          <img :src="previewUrl" />
          <button type="button" class="overlay-close" @click="previewUrl = ''">\u2715</button>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatMessage } from '../composables/useChatMessages'

const props = defineProps<{ message: ChatMessage }>()

const previewUrl = ref('')

function openPreview(url: string) {
  previewUrl.value = url
}

const actorLabel = computed(() => {
  const actor = (props.message.actor || '').toLowerCase()
  if (actor === 'seedream') return 'Seedream'
  if (actor === 'seedance') return 'Seedance'
  return actor || 'Provider'
})

const timeLabel = computed(() => {
  if (!props.message.timestamp) return ''
  const d = new Date(props.message.timestamp)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
})
</script>

<style scoped>
.media-card {
  display: grid;
  gap: 10px;
  max-width: 90%;
  border: 1px solid #30363d;
  border-radius: 12px;
  background: #161b22;
  padding: 14px 18px;
  animation: slide-up 0.3s ease-out both;
}

.media-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.media-icon {
  font-size: 16px;
}

.media-header strong {
  color: #e6edf3;
  font-size: 14px;
}

.media-actor {
  color: #8b949e;
  font-size: 12px;
  margin-left: auto;
}

.media-detail {
  margin: 0;
  color: #8b949e;
  font-size: 13px;
  line-height: 1.5;
}

.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
}

.media-thumb {
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid #30363d;
  background: #0d1117;
  cursor: pointer;
}
.media-thumb:hover {
  border-color: #58a6ff;
}

.media-time {
  color: #6e7681;
  font-size: 11px;
}

/* Overlay */
.media-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: grid;
  place-content: center;
  background: rgba(1, 4, 9, 0.85);
}
.media-overlay-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
}
.media-overlay-content img {
  display: block;
  max-width: 90vw;
  max-height: 85vh;
  object-fit: contain;
  border-radius: 8px;
}
.overlay-close {
  position: absolute;
  top: -12px;
  right: -12px;
  width: 28px;
  height: 28px;
  border: 1px solid #30363d;
  border-radius: 50%;
  background: #0d1117;
  color: #e6edf3;
  font-size: 14px;
  cursor: pointer;
  display: grid;
  place-content: center;
}

@keyframes slide-up {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
