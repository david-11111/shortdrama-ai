<template>
  <article class="event-item" :class="`event-${tone}`">
    <div class="dot">{{ icon }}</div>
    <div class="body">
      <header>
        <div>
          <em>{{ actorLabel }}</em>
          <strong>{{ title }}</strong>
        </div>
        <time>{{ timeLabel }}</time>
      </header>
      <p v-if="detail">{{ detail }}</p>
      <div v-if="mediaUrl" class="inline-media">
        <img
          v-if="!isVideo"
          :src="mediaUrl"
          loading="lazy"
          class="inline-thumb"
          @click="showOverlay = true"
          @error="($event.target as HTMLImageElement).style.display='none'"
        />
        <video
          v-else
          :src="mediaUrl"
          class="inline-thumb"
          preload="metadata"
          @click="showOverlay = true"
        ></video>
      </div>
      <button v-if="hasPayload" class="evidence-link" type="button" @click="expanded = true">
        查看证据
      </button>
    </div>

    <!-- 大图 overlay -->
    <teleport to="body">
      <div v-if="showOverlay && mediaUrl" class="media-overlay" @click.self="showOverlay = false">
        <div class="media-overlay-content">
          <img v-if="!isVideo" :src="mediaUrl" />
          <video v-else :src="mediaUrl" controls autoplay></video>
          <button type="button" class="overlay-close" @click="showOverlay = false">✕</button>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="expanded" class="evidence-overlay" @click.self="expanded = false">
        <aside class="evidence-panel">
          <header>
            <div>
              <span>服务端证据</span>
              <strong>{{ title }}</strong>
            </div>
            <button type="button" @click="expanded = false">关闭</button>
          </header>
          <dl>
            <div v-if="eventType">
              <dt>event</dt>
              <dd>{{ eventType }}</dd>
            </div>
            <div v-if="phase">
              <dt>phase</dt>
              <dd>{{ phase }}</dd>
            </div>
            <div v-if="status">
              <dt>status</dt>
              <dd>{{ status }}</dd>
            </div>
            <div v-if="reasonText">
              <dt>reason</dt>
              <dd>{{ reasonText }}</dd>
            </div>
          </dl>
          <pre>{{ payload }}</pre>
        </aside>
      </div>
    </teleport>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TimelineEvent } from './EventTimeline.vue'

const props = defineProps<{
  event: TimelineEvent
}>()

const expanded = ref(false)
const showOverlay = ref(false)

const meta = computed(() => (props.event.meta || props.event.data || {}) as Record<string, any>)
const rawEvent = computed(() => (meta.value.raw_event && typeof meta.value.raw_event === 'object' ? meta.value.raw_event : props.event) as Record<string, any>)
const eventType = computed(() => String(rawEvent.value.event_type || props.event.event_type || props.event.level || ''))
const phase = computed(() => String(rawEvent.value.phase || props.event.phase || props.event.node_id || ''))
const status = computed(() => String(rawEvent.value.status || props.event.status || ''))
const actor = computed(() => String(props.event.actor || rawEvent.value.actor || rawEvent.value.source || '').toLowerCase())

// 内联产物缩略图
const mediaUrl = computed(() => {
  if (!['writeback', 'writeback_summary', 'artifact'].includes(eventType.value)) return ''
  const evt = rawEvent.value
  const url = evt.url || evt.image_url || evt.video_url || evt.selected_image || evt.selected_video
    || evt.meta?.url || evt.meta?.image_url || evt.meta?.video_url || ''
  if (!url || typeof url !== 'string') return ''
  if (url.startsWith('http') || url.startsWith('/')) return url
  return ''
})
const isVideo = computed(() => /\.(mp4|webm|mov)(\?|$)/i.test(mediaUrl.value) || eventType.value === 'artifact' && rawEvent.value.artifact_type === 'video')

const title = computed(() => cleanText(props.event.title || props.event.summary || props.event.text || eventType.value || '执行事件'))
const detail = computed(() => {
  const value = cleanText(props.event.detail || '')
  if (isEvidenceText(value)) return ''
  return value && value !== title.value ? value : ''
})
const reasonText = computed(() => cleanText(rawEvent.value.reason || rawEvent.value.meta?.agent_event?.reason || rawEvent.value.meta?.reason || ''))
const hasPayload = computed(() => Boolean(meta.value.raw_event || props.event.meta || props.event.data))
const payload = computed(() => JSON.stringify(meta.value.raw_event || props.event.meta || props.event.data || props.event, null, 2))

const actorLabel = computed(() => {
  if (actor.value === 'user') return '你'
  if (actor.value === 'deepseek') return 'DeepSeek'
  if (actor.value === 'state_machine') return '状态机'
  if (actor.value === 'executor') return '执行器'
  if (actor.value === 'seedream') return 'Seedream'
  if (actor.value === 'seedance') return 'Seedance'
  if (actor.value === 'kling') return 'Kling'
  if (actor.value === 'ffmpeg') return 'FFmpeg'
  return 'Agent'
})

const tone = computed(() => {
  if (status.value === 'provider_waiting') return 'running'
  if (eventType.value === 'error' || status.value === 'failed') return 'error'
  if (eventType.value === 'risk' || status.value === 'blocked') return 'risk'
  if (['tool_result', 'writeback', 'writeback_summary', 'artifact'].includes(eventType.value) || ['done', 'completed'].includes(status.value)) return 'success'
  if (['tool_call', 'progress'].includes(eventType.value) || ['queued', 'running', 'dispatching', 'dispatched'].includes(status.value)) return 'running'
  return 'default'
})

const icon = computed(() => {
  if (tone.value === 'error' || tone.value === 'risk') return '!'
  if (tone.value === 'success') return '✓'
  return '•'
})

const timeLabel = computed(() => {
  const value = props.event.time || props.event.created_at
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString('zh-CN', { hour12: false })
})

function cleanText(value: unknown) {
  const text = String(value || '').trim()
  if (!text) return ''
  if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) return ''
  return text
}

function isEvidenceText(value: string) {
  const text = value.trim()
  if (!text) return false
  return /\b(files|consumed|covered|partial|missing|total|phase|provider|task_id|artifact_id|next_action|can_continue|mode|prompt|shot_index|field|acquire_key)=/i.test(text)
}
</script>

<style scoped>
.event-item {
  position: relative;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 12px;
  padding: 12px 0;
}

.dot {
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid #30363d;
  border-radius: 50%;
  background: #0d1117;
  color: #8b949e;
  font-size: 13px;
}

.event-running .dot {
  border-color: #58a6ff;
  color: #58a6ff;
}

.event-success .dot {
  border-color: #3fb950;
  color: #7ee787;
}

.event-risk .dot,
.event-error .dot {
  border-color: #f85149;
  color: #ff7b72;
}

.body {
  min-width: 0;
}

header {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: baseline;
}

header div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

em {
  color: #58a6ff;
  font-size: 12px;
  font-style: normal;
}

strong {
  color: #e6edf3;
  font-size: 14px;
  line-height: 1.45;
}

time,
p,
button {
  color: #8b949e;
  font-size: 12px;
}

p {
  margin: 5px 0 0;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.evidence-link {
  margin-top: 6px;
  border: 0;
  background: transparent;
  padding: 0;
  color: #58a6ff;
  cursor: pointer;
}

.evidence-link:hover {
  text-decoration: underline;
}

/* Inline media thumbnail */
.inline-media {
  margin-top: 8px;
}
.inline-thumb {
  display: block;
  max-width: 120px;
  max-height: 80px;
  border-radius: 6px;
  border: 1px solid #30363d;
  object-fit: cover;
  cursor: pointer;
  background: #010409;
}
.inline-thumb:hover {
  border-color: #58a6ff;
}

/* Media overlay */
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
.media-overlay-content img,
.media-overlay-content video {
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

.evidence-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
  background: rgba(1, 4, 9, 0.56);
}

.evidence-panel {
  width: min(680px, 100vw);
  height: 100%;
  overflow: auto;
  border-left: 1px solid #30363d;
  background: #0d1117;
  padding: 22px;
}

.evidence-panel header {
  align-items: flex-start;
  margin-bottom: 18px;
}

.evidence-panel header span {
  color: #8b949e;
  font-size: 12px;
}

.evidence-panel header button {
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #161b22;
  padding: 7px 10px;
  cursor: pointer;
}

dl {
  display: grid;
  gap: 8px;
  margin: 0 0 16px;
}

dl div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px;
}

dt {
  color: #8b949e;
}

dd {
  margin: 0;
  color: #e6edf3;
  overflow-wrap: anywhere;
}

pre {
  margin: 0;
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #010409;
  color: #c9d1d9;
  padding: 14px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
