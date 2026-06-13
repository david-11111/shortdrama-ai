<script setup lang="ts">
import { ref } from 'vue'

interface ShotRow {
  shot_index: number
  prompt: string
  duration: number
  status: string
  image_candidates?: Array<string | { url?: string; image_url?: string; video_url?: string }>
  video_variants?: Array<string | { url?: string; image_url?: string; video_url?: string }>
  selected_image?: string | null
  selected_video?: string | null
  selected: boolean
  character_refs?: string[]
  scene_refs?: string[]
  style_refs?: string[]
  last_error?: string
}

defineProps<{
  rows: ShotRow[]
}>()

const emit = defineEmits<{
  updateRow: [idx: number, data: Partial<ShotRow>]
  openRefs: [idx: number]
  toggleSelect: [idx: number, val: boolean]
  selectAll: [val: boolean]
}>()

const allSelected = ref(false)
const FALLBACK_THUMB = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 120 120%22%3E%3Crect width=%22120%22 height=%22120%22 fill=%22%23e5e7eb%22/%3E%3Cpath d=%22M20 84l24-24 16 16 20-20 20 28H20z%22 fill=%22%239ca3af%22/%3E%3Ccircle cx=%2244%22 cy=%2242%22 r=%228%22 fill=%22%239ca3af%22/%3E%3C/svg%3E'

const trustedHostSuffixes = [
  'aliyuncs.com',
  'myqcloud.com',
  'qpic.cn',
]

function toggleAll() {
  allSelected.value = !allSelected.value
  emit('selectAll', allSelected.value)
}

const statusColors: Record<string, string> = {
  draft: '#6b7280',
  ready: '#3b82f6',
  generating_image: '#f59e0b',
  generating_video: '#f59e0b',
  image_done: '#10b981',
  video_done: '#10b981',
  error: '#ef4444',
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    draft: '草稿',
    ready: '就绪',
    generating_image: '生成图中',
    generating_video: '生成视频中',
    image_done: '图完成',
    video_done: '视频完成',
    error: '错误',
  }
  return map[s] || s
}

function isGenerating(s: string): boolean {
  return s === 'generating_image' || s === 'generating_video'
}

function isAllowedMediaUrl(rawUrl?: string | null): boolean {
  if (!rawUrl) return false
  if (rawUrl.startsWith('/assets/') || rawUrl.startsWith('/uploads/')) return true

  let parsed: URL
  try {
    parsed = new URL(rawUrl, window.location.origin)
  } catch {
    return false
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
  if (parsed.hostname === window.location.hostname) return true
  if (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') return true
  return trustedHostSuffixes.some((suffix) => parsed.hostname === suffix || parsed.hostname.endsWith(`.${suffix}`))
}

function mediaUrl(rawUrl?: string | { url?: string; image_url?: string; video_url?: string } | null): string {
  if (typeof rawUrl === 'string') return rawUrl
  if (!rawUrl || typeof rawUrl !== 'object') return ''
  return String(rawUrl.url || rawUrl.image_url || rawUrl.video_url || '')
}

function safeMediaUrl(rawUrl?: string | { url?: string; image_url?: string; video_url?: string } | null): string {
  const url = mediaUrl(rawUrl)
  return isAllowedMediaUrl(url) ? url : FALLBACK_THUMB
}

function onThumbError(event: Event) {
  const target = event.target as HTMLImageElement
  if (target.src !== FALLBACK_THUMB) {
    target.src = FALLBACK_THUMB
  }
}
</script>

<template>
  <div class="shot-table-wrap">
    <table class="shot-table">
      <thead>
        <tr>
          <th class="col-check">
            <input type="checkbox" :checked="allSelected" @change="toggleAll" />
          </th>
          <th class="col-idx">#</th>
          <th class="col-prompt">提示词</th>
          <th class="col-duration">时长</th>
          <th class="col-status">状态</th>
          <th class="col-images">参考图</th>
          <th class="col-videos">视频</th>
          <th class="col-refs">Refs</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.shot_index">
          <td class="col-check">
            <input
              type="checkbox"
              :checked="row.selected"
              @change="emit('toggleSelect', row.shot_index, !row.selected)"
            />
          </td>
          <td class="col-idx">{{ row.shot_index }}</td>
          <td class="col-prompt">
            <textarea
              :value="row.prompt"
              rows="2"
              @blur="e => emit('updateRow', row.shot_index, { prompt: (e.target as HTMLTextAreaElement).value })"
            />
          </td>
          <td class="col-duration">
            <input
              type="number"
              :value="row.duration"
              min="1"
              max="60"
              @blur="e => emit('updateRow', row.shot_index, { duration: Number((e.target as HTMLInputElement).value) })"
            />
          </td>
          <td class="col-status">
            <span
              class="status-badge"
              :class="{ generating: isGenerating(row.status) }"
              :style="{ '--badge-color': statusColors[row.status] || '#6b7280' }"
              :title="row.status === 'error' ? row.last_error : undefined"
            >
              {{ statusLabel(row.status) }}
            </span>
          </td>
          <td class="col-images">
            <div class="thumb-row">
              <img
                v-for="(img, i) in (row.image_candidates || [])"
                :key="i"
                :src="safeMediaUrl(img)"
                :class="['thumb', { active: row.selected_image === mediaUrl(img) }]"
                alt=""
                @click="emit('updateRow', row.shot_index, { selected_image: mediaUrl(img) })"
                @error="onThumbError"
              />
              <span v-if="!row.image_candidates?.length" class="no-data">-</span>
            </div>
          </td>
          <td class="col-videos">
            <div class="thumb-row">
              <img
                v-for="(vid, i) in (row.video_variants || [])"
                :key="i"
                :src="safeMediaUrl(vid)"
                :class="['thumb', { active: row.selected_video === mediaUrl(vid) }]"
                alt=""
                @click="emit('updateRow', row.shot_index, { selected_video: mediaUrl(vid) })"
                @error="onThumbError"
              />
              <span v-if="!row.video_variants?.length" class="no-data">-</span>
            </div>
          </td>
          <td class="col-refs">
            <div class="ref-tags">
              <span
                v-for="r in (row.character_refs || [])"
                :key="'c-' + r"
                class="ref-tag char"
              >C</span>
              <span
                v-for="r in (row.scene_refs || [])"
                :key="'s-' + r"
                class="ref-tag scene"
              >S</span>
              <span
                v-for="r in (row.style_refs || [])"
                :key="'st-' + r"
                class="ref-tag style"
              >St</span>
              <button class="edit-refs-btn" @click="emit('openRefs', row.shot_index)">+</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.shot-table-wrap {
  overflow-x: auto;
  flex: 1;
}

.shot-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.shot-table th,
.shot-table td {
  padding: var(--space-sm);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}

.shot-table th {
  background: var(--color-bg-secondary);
  font-weight: 600;
  position: sticky;
  top: 0;
  z-index: 1;
}

.col-check { width: 36px; text-align: center; }
.col-idx { width: 40px; }
.col-prompt { min-width: 200px; }
.col-duration { width: 70px; }
.col-status { width: 90px; }
.col-images { width: 120px; }
.col-videos { width: 120px; }
.col-refs { width: 100px; }

.col-prompt textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-xs);
  font-size: 12px;
  font-family: var(--font-sans);
  background: var(--color-bg);
  color: var(--color-text);
}

.col-duration input {
  width: 56px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-xs);
  font-size: 12px;
  background: var(--color-bg);
  color: var(--color-text);
}

.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  color: #fff;
  background: var(--badge-color);
}

.status-badge.generating {
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.thumb-row {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  border: 2px solid transparent;
  cursor: pointer;
}

.thumb.active {
  border-color: var(--color-primary);
}

.no-data {
  color: var(--color-text-secondary);
}

.ref-tags {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
  align-items: center;
}

.ref-tag {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  color: #fff;
}

.ref-tag.char { background: #8b5cf6; }
.ref-tag.scene { background: #06b6d4; }
.ref-tag.style { background: #f97316; }

.edit-refs-btn {
  width: 20px;
  height: 20px;
  border: 1px dashed var(--color-border);
  border-radius: 3px;
  background: none;
  cursor: pointer;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.edit-refs-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
</style>
