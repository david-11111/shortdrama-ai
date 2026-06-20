<template>
  <section class="output-board" aria-label="Agent outputs">
    <!-- 顶部统计条 -->
    <header class="ob-header">
      <strong>成果</strong>
      <span>{{ summary.shot_count || shots.length || 0 }}镜</span>
      <span>{{ summary.image_count || images.length || 0 }}图</span>
      <span>{{ summary.video_count || videos.length || 0 }}视频</span>
      <button type="button" class="btn-refresh" @click="emit('refresh')">⟳</button>
    </header>

    <!-- 空状态 -->
    <div v-if="!hasOutputs" class="empty-output">
      <span class="empty-icon">□</span>
      <strong>暂无成果</strong>
      <span>Agent 执行过程中的输出将显示在这里</span>
    </div>

    <template v-else>
      <section v-if="finalVideoUrl" class="final-video-panel">
        <div class="final-video-head">
          <div>
            <strong>最终成片</strong>
            <span>{{ finalVideoTitle }}</span>
          </div>
          <a :href="assetUrl(finalVideoUrl)" target="_blank">打开</a>
        </div>
        <video :src="assetUrl(finalVideoUrl)" controls preload="metadata"></video>
      </section>

      <details class="text-sections">
        <summary>文本输出 <small>({{ textCount }})</small></summary>
        <section v-if="scriptContent" class="text-output script-output">
          <h3>剧本文案</h3>
          <p>{{ scriptContent }}</p>
        </section>

        <section v-if="directorNotes.length" class="text-output notes-output">
          <h3>导演说明</h3>
          <article v-for="note in directorNotes" :key="`${note.source || 'note'}-${note.title}`">
            <strong>{{ note.title || '说明' }}</strong>
            <p>{{ note.content }}</p>
          </article>
        </section>
      </details>

      <div v-if="clipVideos.length" class="section-header"><span>视频片段</span><small>{{ clipVideos.length }}</small></div>
      <div v-if="clipVideos.length" class="media-strip output-videos">
        <a v-for="video in clipVideos" :key="video.id || video.url" :href="assetUrl(video.url)" target="_blank" class="media-card video-card">
          <video :src="assetUrl(video.url)" preload="metadata" muted></video>
          <span>{{ video.title || `Video ${video.shot_index ?? ''}` }}</span>
        </a>
      </div>

      <div v-if="images.length" class="section-header"><span>图片</span><small>{{ images.length }}</small></div>
      <div v-if="images.length" class="media-strip output-images">
        <div v-for="image in images" :key="image.id || image.url" class="media-card-wrap">
          <a :href="assetUrl(image.url)" target="_blank" class="media-card">
            <img :src="assetUrl(image.url)" loading="lazy" @error="($event.target as HTMLImageElement).style.display='none'" />
            <span>{{ image.title || `Image ${image.shot_index ?? ''}` }}</span>
          </a>
          <button
            v-if="desktopRunning"
            type="button"
            class="media-desktop-btn"
            :disabled="desktopBusy"
            @click="openSingleInDesktop(image.url, image.title)"
            title="发送到 LTX Desktop"
          >LTX</button>
        </div>
      </div>

      <!-- 镜头缩略图网格 -->
      <div v-if="shots.length" class="section-header"><span>镜头</span><small>{{ shots.length }}</small></div>
      <div v-if="shots.length" class="shot-grid">
        <button
          v-for="shot in shots"
          :key="String(shot.shot_index)"
          type="button"
          class="shot-cell"
          :class="{
            selected: selectedShotIndex === shot.shot_index,
            'has-image': !!shot.selected_image,
            'has-video': !!shot.selected_video,
            'has-error': !!shot.last_error,
          }"
          @click="selectedShotIndex = typeof shot.shot_index === 'number' ? shot.shot_index : null"
        >
          <video
            v-if="shot.selected_video"
            :src="assetUrl(shot.selected_video)"
            preload="metadata"
            muted
          ></video>
          <img
            v-else-if="shot.selected_image"
            :src="assetUrl(shot.selected_image)"
            loading="lazy"
            @error="($event.target as HTMLImageElement).style.display='none'"
          />
          <span class="cell-index">#{{ shot.shot_index ?? '-' }}</span>
          <span class="cell-status">
            <i v-if="shot.selected_video" class="dot dot-green"></i>
            <i v-else-if="shot.selected_image" class="dot dot-blue"></i>
            <i v-else-if="shot.last_error" class="dot dot-red"></i>
            <i v-else class="dot dot-gray"></i>
          </span>
        </button>
      </div>

      <!-- 选中镜头详情区 -->
      <div v-if="selectedShot" class="shot-detail">
        <!-- 大图/视频预览 -->
        <div class="detail-preview">
          <video
            v-if="selectedShot.selected_video"
            :src="assetUrl(selectedShot.selected_video)"
            controls
            preload="metadata"
          ></video>
          <img
            v-else-if="selectedShot.selected_image"
            :src="assetUrl(selectedShot.selected_image)"
            @error="($event.target as HTMLImageElement).src=''"
          />
          <div v-else class="preview-empty">暂无媒体</div>
          <button
            v-if="selectedShot && videoProvider === 'ltx2.3' && (selectedShot.selected_video || selectedShot.selected_image)"
            type="button"
            class="btn-desktop"
            :disabled="desktopBusy"
            @click="openInDesktop(selectedShot)"
          >
            {{ desktopBusy ? '发送中…' : '在 LTX Desktop 中打开' }}
          </button>
        </div>

        <!-- 镜头元信息 -->
        <div class="detail-meta">
          <b>#{{ selectedShot.shot_index }} · {{ shotState(selectedShot) }}</b>
          <p>{{ selectedShot.prompt || '—' }}</p>
          <p v-if="selectedShot.last_error" class="meta-error">{{ safeError(selectedShot.last_error) }}</p>
        </div>

        <!-- 操作栏 -->
        <div class="detail-actions">
          <select v-model="videoProvider" :disabled="busy" @change="persistVideoProvider">
            <option value="joy-echo">Joy-Echo</option>
            <option value="ltx2.3">LTX 2.3</option>
          </select>
          <span v-if="videoProvider === 'ltx2.3'" :class="desktopRunning ? 'ltx-local-badge' : 'ltx-remote-badge'">{{ desktopRunning ? '桌面版' : '远程' }}</span>
          <label class="duration-control">
            <span>时长</span>
            <input
              v-model.number="videoDuration"
              type="number"
              min="5"
              max="300"
              step="5"
              :disabled="busy"
              @change="persistVideoDuration"
            />
            <span>秒</span>
          </label>
          <button type="button" :disabled="busy" @click="generateBatchForSelected">生成多图</button>
          <button type="button" :disabled="busy || !selectedPool || !mainCandidate(selectedPool)" @click="generateVideoForSelected">生成视频</button>
        </div>

        <!-- 候选图网格 -->
        <div v-if="selectedPool?.candidates?.length" class="candidate-strip">
          <button
            v-for="c in selectedPool.candidates"
            :key="c.artifact_id || c.url"
            type="button"
            class="cand-thumb"
            :class="{ active: c.selected }"
            @click="selectCandidate(selectedPool!, c)"
            :disabled="busy || c.selected"
          >
            <img :src="assetUrl(c.url)" loading="lazy" @error="($event.target as HTMLImageElement).style.display='none'" />
            <i v-if="c.selected" class="check">✓</i>
          </button>
        </div>

        <!-- 操作反馈 -->
        <p v-if="actionMessage" class="action-msg">{{ actionMessage }}</p>
        <p v-if="actionError" class="action-err">{{ actionError }}</p>
      </div>

      <!-- 未选中时显示摘要 -->
      <div v-else class="shot-detail hint">
        <span>← 点击镜头查看详情</span>
        <a v-if="finalVideoUrl" :href="assetUrl(finalVideoUrl)" target="_blank">打开成片 ↗</a>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  generateAgentRunKeyframeBatch,
  generateAgentRunVideoFromPool,
  normalizeMediaUrl,
  selectAgentRunKeyframeCandidate,
  type AgentRunKeyframeCandidate,
  type AgentRunKeyframePoolItem,
  type AgentRunOutputs,
} from '@/api/director'
import { getLtxDesktopHealth, openInLtxDesktop } from '@/api/ltxDesktop'
import { useTaskPoller } from '@/composables/useTaskPoller'

const props = defineProps<{
  outputs?: AgentRunOutputs | null
  runId?: string
}>()

const emit = defineEmits<{
  refresh: []
}>()

type ShotRow = NonNullable<AgentRunOutputs['shots']>[number]

const busy = ref(false)
const actionMessage = ref('')
const actionError = ref('')
type VideoProvider = 'joy-echo' | 'ltx2.3'

const videoProvider = ref<VideoProvider>(readVideoProvider())
const videoDuration = ref(readVideoDuration())
const selectedShotIndex = ref<number | null>(null)
const actionPollers = [useTaskPoller(), useTaskPoller(), useTaskPoller(), useTaskPoller()]
const actionTaskTimers: Array<ReturnType<typeof setInterval>> = []
const desktopRunning = ref(false)
const desktopBusy = ref(false)

const summary = computed(() => props.outputs?.summary || { image_count: 0, video_count: 0, shot_count: 0 })
const images = computed(() => props.outputs?.images || [])
const videos = computed(() => props.outputs?.videos || [])
const shots = computed(() => props.outputs?.shots || [])
const keyframePools = computed(() => props.outputs?.keyframe_pool || [])
const finalVideo = computed(() => {
  const summaryUrl = String(summary.value.final_video_url || '').trim()
  const finalItems = videos.value.filter((item) => isFinalVideo(item))
  if (summaryUrl) {
    return finalItems.find((item) => String(item.url || '').trim() === summaryUrl)
      || finalItems[finalItems.length - 1]
      || { url: summaryUrl, title: 'Final video' }
  }
  return finalItems[finalItems.length - 1] || null
})
const finalVideoUrl = computed(() => String(finalVideo.value?.url || '').trim())
const finalVideoTitle = computed(() => String(finalVideo.value?.title || finalVideo.value?.summary || 'Final video').trim())
const clipVideos = computed(() =>
  videos.value.filter((item) => {
    if (isFinalVideo(item)) return false
    return String(item.url || '').trim() !== finalVideoUrl.value
  }),
)
const scriptContent = computed(() => {
  const script = props.outputs?.script
  const content = String(script?.content || '').trim()
  if (content) return content
  return (script?.items || [])
    .map((item) => String(item.content || '').trim())
    .filter(Boolean)
    .join('\n\n')
})
const directorNotes = computed(() =>
  (props.outputs?.director_notes || []).filter((item) => String(item.content || '').trim()),
)
const selectedShot = computed(() => shots.value.find((s) => s.shot_index === selectedShotIndex.value) || null)
const selectedPool = computed(() => keyframePools.value.find((p) => p.shot_index === selectedShotIndex.value) || null)
const textCount = computed(() => {
  let count = 0
  if (scriptContent.value) count++
  count += directorNotes.value.length
  return count
})
const hasOutputs = computed(() => Boolean(
  scriptContent.value ||
  directorNotes.value.length ||
  shots.value.length ||
  images.value.length ||
  videos.value.length ||
  keyframePools.value.length,
))

watch(
  shots,
  (items) => {
    if (!items.length) {
      selectedShotIndex.value = null
      return
    }
    if (selectedShotIndex.value != null && items.some((shot) => shot.shot_index === selectedShotIndex.value)) {
      return
    }
    const preferred = items.find((shot) => shot.selected_video)
      || items.find((shot) => shot.selected_image)
      || items[0]
    selectedShotIndex.value = typeof preferred?.shot_index === 'number' ? preferred.shot_index : null
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    const { data } = await getLtxDesktopHealth()
    desktopRunning.value = data.running
  } catch {
    desktopRunning.value = false
  }
})

async function openSingleInDesktop(url: string, title?: string) {
  if (!url) return
  desktopBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const { data } = await openInLtxDesktop({
      media_url: normalizeMediaUrl(url),
      action: 'image-to-video',
      prompt: title || '',
    })
    actionMessage.value = data.message || `已发送 ${title || '图片'} 到 LTX Desktop`
  } catch (err: any) {
    actionError.value = userFacingError(err)
  } finally {
    desktopBusy.value = false
  }
}

async function openInDesktop(shot: ShotRow) {
  const mediaUrl = shot.selected_video || shot.selected_image
  if (!mediaUrl) return
  desktopBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const { data } = await openInLtxDesktop({
      media_url: normalizeMediaUrl(mediaUrl),
      action: shot.selected_video ? 'preview' : 'image-to-video',
    })
    actionMessage.value = data.message || '已发送到 LTX Desktop'
  } catch (err: any) {
    actionError.value = userFacingError(err)
  } finally {
    desktopBusy.value = false
  }
}

function assetUrl(value?: string) {
  return normalizeMediaUrl(value)
}

function isFinalVideo(item: { id?: unknown; kind?: unknown; source?: unknown }) {
  const text = `${item.id || ''} ${item.kind || ''} ${item.source || ''}`.toLowerCase()
  return text.includes('final_video') || text.includes('final-video')
}

function mainCandidate(pool: AgentRunKeyframePoolItem) {
  return (pool.candidates || []).find((item) => item.selected && item.url) || (pool.candidates || []).find((item) => item.url)
}

function shotState(shot: ShotRow) {
  if (shot.selected_video) return '视频完成'
  if (shot.selected_image) return '关键帧完成'
  if (String(shot.status || '') === 'provider_waiting') return '等待 provider'
  if (shot.last_error) return '需处理'
  return friendlyStatus(shot.status) || '等待'
}

function friendlyStatus(value?: string | null) {
  const labels: Record<string, string> = {
    created: '已创建',
    queued: '排队中',
    pending: '等待中',
    running: '生成中',
    dispatching: '派发中',
    provider_waiting: '等待 provider',
    provider_requesting: '请求 provider',
    done: '已完成',
    completed: '已完成',
    failed: '失败',
    dead_letter: '待恢复',
    cancelled: '已取消',
    ready: '可用',
  }
  return labels[String(value || '')] || ''
}

function safeError(value?: string) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (/saturated|backpressure|too many requests|429|rate limit/i.test(text)) return 'Provider 暂时繁忙'
  return text
}

async function generateBatch(pool: AgentRunKeyframePoolItem) {
  if (!props.runId || pool.shot_index == null) return
  await runAction(async () => {
    const { data } = await generateAgentRunKeyframeBatch(props.runId!, {
      shot_index: pool.shot_index,
      count: 3,
      variation_strategy: 'angle',
    })
    trackActionTasks(data)
    actionMessage.value = `第 ${pool.shot_index} 镜已派发 ${data?.count ?? 3} 张候选关键帧。`
    emit('refresh')
  })
}

async function selectCandidate(pool: AgentRunKeyframePoolItem, candidate: AgentRunKeyframeCandidate) {
  if (!props.runId || pool.shot_index == null || !candidate.url) return
  await runAction(async () => {
    await selectAgentRunKeyframeCandidate(props.runId!, {
      shot_index: pool.shot_index,
      url: candidate.url,
      artifact_id: candidate.artifact_id || '',
    })
    actionMessage.value = `第 ${pool.shot_index} 镜主图已更新。`
    emit('refresh')
  })
}

async function generateVideo(pool: AgentRunKeyframePoolItem) {
  const candidate = mainCandidate(pool)
  if (!props.runId || pool.shot_index == null || !candidate?.url) return
  await runAction(async () => {
    const duration = boundedVideoDuration(videoDuration.value)
    videoDuration.value = duration
    persistVideoDuration()
    const { data } = await generateAgentRunVideoFromPool(props.runId!, {
      shot_index: pool.shot_index,
      provider: videoProvider.value,
      duration,
      mode: 'best_single',
      candidate_url: candidate.url,
      artifact_id: candidate.artifact_id || '',
      selected_artifact_ids: (pool.candidates || [])
        .filter((item) => item.selected && item.artifact_id)
        .map((item) => item.artifact_id),
    })
    trackActionTasks(data)
    actionMessage.value = `第 ${pool.shot_index} 镜 ${duration} 秒视频已派发生成。`
    emit('refresh')
  })
}

function trackActionTasks(data: any) {
  stopActionTaskTimers()
  const ids = actionTaskIds(data).slice(0, actionPollers.length)
  ids.forEach((taskId, index) => {
    const poller = actionPollers[index]
    poller.start(taskId)
    const timer = setInterval(() => {
      if (!poller.isPolling.value && poller.status.value) {
        clearInterval(timer)
        emit('refresh')
      }
    }, 300)
    actionTaskTimers.push(timer)
  })
}

function actionTaskIds(data: any): string[] {
  const ids = Array.isArray(data?.child_task_ids)
    ? data.child_task_ids
    : Array.isArray(data?.task_ids)
      ? data.task_ids
      : data?.task_id
        ? [data.task_id]
        : []
  return ids.map((id: unknown) => String(id || '').trim()).filter(Boolean)
}

function stopActionTaskTimers() {
  while (actionTaskTimers.length) {
    const timer = actionTaskTimers.pop()
    if (timer) clearInterval(timer)
  }
}

onUnmounted(stopActionTaskTimers)

function readVideoProvider(): VideoProvider {
  const value = localStorage.getItem('agent-run:video-provider')
  return value === 'ltx2.3' ? 'ltx2.3' : 'joy-echo'
}

function persistVideoProvider() {
  localStorage.setItem('agent-run:video-provider', videoProvider.value)
}

function readVideoDuration(): number {
  return boundedVideoDuration(Number(localStorage.getItem('agent-run:video-duration') || 60))
}

function boundedVideoDuration(value: number): number {
  if (!Number.isFinite(value)) return 60
  return Math.min(300, Math.max(5, Math.round(value)))
}

function persistVideoDuration() {
  videoDuration.value = boundedVideoDuration(videoDuration.value)
  localStorage.setItem('agent-run:video-duration', String(videoDuration.value))
}

async function generateBatchForSelected() {
  if (!selectedPool.value) return
  await generateBatch(selectedPool.value)
}

async function generateVideoForSelected() {
  if (!selectedPool.value) return
  await generateVideo(selectedPool.value)
}

async function runAction(action: () => Promise<void>) {
  busy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    await action()
  } catch (err: any) {
    actionError.value = userFacingError(err)
  } finally {
    busy.value = false
  }
}

function userFacingError(err: any) {
  const detail = err?.response?.data?.detail
  if (detail && typeof detail === 'object') {
    if (detail.user_message) return String(detail.user_message)
    if (detail.code === 'active_tasks' || detail.active_task_count) {
      return `当前已有 ${detail.active_task_count || 1} 个任务正在执行，先等待完成或刷新成果区后再继续。`
    }
    if (detail.code === 'gate_blocked') return String(detail.recovery || '当前阶段还不能执行这个动作，请先完成前置步骤。')
    if (detail.message && /already has active tasks/i.test(String(detail.message))) {
      return '当前已有任务正在执行，先等待完成或刷新成果区后再继续。'
    }
    return '操作没有执行，请查看当前阶段状态后再试。'
  }
  const message = String(detail || err?.message || '')
  if (/already has active tasks/i.test(message)) return '当前已有任务正在执行，先等待完成或刷新成果区后再继续。'
  if (/network error/i.test(message)) return '网络连接异常，请刷新后重试。'
  return message || '操作失败'
}
</script>

<style scoped>
.output-board {
  display: grid;
  grid-template-rows: 36px auto minmax(0, 1fr);
  min-height: 0;
  background: #0d1117;
}

/* Header */
.ob-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  border-bottom: 1px solid #21262d;
  font-size: 12px;
}
.ob-header strong { color: #e6edf3; }
.ob-header span { color: #8b949e; }
.btn-refresh {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: #8b949e;
  font-size: 14px;
  cursor: pointer;
}
.btn-refresh:hover { color: #58a6ff; }

/* Empty */
.empty-output {
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  padding: 48px 24px;
  color: #6e7681;
  font-size: 13px;
  text-align: center;
}
.empty-output strong {
  color: #8b949e;
  font-size: 14px;
}
.empty-icon {
  font-size: 22px;
  color: #484f58;
}

/* Collapsible text sections */
.text-sections {
  border-bottom: 1px solid #21262d;
}
.text-sections summary {
  padding: 6px 12px;
  font-size: 12px;
  color: #8b949e;
  cursor: pointer;
  user-select: none;
  background: #0d1117;
  border-bottom: 1px solid #21262d;
}
.text-sections summary:hover {
  color: #e6edf3;
}
.text-sections summary small {
  color: #484f58;
  font-size: 11px;
}

/* Section headers (media sections) */
.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: #8b949e;
  border-bottom: 1px solid #21262d;
  background: #0d1117;
}
.section-header small {
  color: #484f58;
  font-size: 11px;
}

.text-output {
  margin: 8px;
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #0d1117;
  padding: 10px;
}

.text-output h3 {
  margin: 0 0 8px;
  color: #f0f6fc;
  font-size: 14px;
}

.text-output p {
  margin: 0;
  color: #c9d1d9;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.text-output article + article {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #21262d;
}

.text-output strong {
  display: block;
  margin-bottom: 4px;
  color: #8ddb8c;
  font-size: 12px;
}

.final-video-panel {
  margin: 8px;
  border: 1px solid #3fb950;
  border-radius: 8px;
  background: #090c10;
  overflow: hidden;
}

.final-video-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(63, 185, 80, 0.32);
}

.final-video-head div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.final-video-head strong {
  color: #e6edf3;
  font-size: 14px;
}

.final-video-head span {
  overflow: hidden;
  color: #8b949e;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.final-video-head a {
  margin-left: auto;
  border: 1px solid #3fb950;
  border-radius: 6px;
  color: #8ddb8c;
  padding: 4px 8px;
  font-size: 12px;
  text-decoration: none;
}

.final-video-panel video {
  display: block;
  width: 100%;
  max-height: min(46vh, 420px);
  aspect-ratio: 16 / 9;
  object-fit: contain;
  background: #010409;
}

.media-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 8px;
  padding: 8px;
}

.output-images {
  display: flex;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 10px;
  border-top: 1px solid #21262d;
  border-bottom: 1px solid #21262d;
}

.output-images .media-card-wrap {
  flex: 0 0 116px;
  position: relative;
}
.output-images .media-card {
  display: block;
}

.media-card {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: #c9d1d9;
  font-size: 11px;
  text-decoration: none;
}

.media-card img,
.media-card video,
.shot-cell video {
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  border: 1px solid #30363d;
  border-radius: 6px;
  background: #010409;
}

.media-card span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Shot grid */
.shot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(56px, 1fr));
  gap: 4px;
  padding: 8px;
  overflow-y: auto;
  max-height: min(320px, 40vh);
  border-bottom: 1px solid #21262d;
}

.shot-cell {
  position: relative;
  aspect-ratio: 1;
  border: 2px solid #30363d;
  border-radius: 6px;
  background: #161b22;
  overflow: hidden;
  cursor: pointer;
  padding: 0;
}
.shot-cell img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.shot-cell video {
  display: block;
  height: 100%;
  aspect-ratio: auto;
}
.shot-cell.selected { border-color: #58a6ff; }
.shot-cell.has-video { border-color: #3fb950; }
.shot-cell.has-error { border-color: #f85149; }

.cell-index {
  position: absolute;
  bottom: 2px;
  left: 3px;
  font-size: 10px;
  color: #fff;
  text-shadow: 0 1px 2px #000;
}
.cell-status {
  position: absolute;
  top: 3px;
  right: 3px;
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.dot-green { background: #3fb950; }
.dot-blue { background: #58a6ff; }
.dot-red { background: #f85149; }
.dot-gray { background: #484f58; }

/* Detail panel */
.shot-detail {
  display: grid;
  gap: 10px;
  padding: 12px 16px;
  overflow-y: auto;
  align-content: start;
  max-height: min(360px, 50vh);
  border-top: 1px solid #30363d;
}
.shot-detail.hint {
  place-content: center;
  text-align: center;
  color: #6e7681;
  font-size: 13px;
}
.shot-detail.hint a {
  color: #58a6ff;
  margin-top: 8px;
}

.detail-preview video,
.detail-preview img {
  width: 100%;
  max-height: 200px;
  object-fit: contain;
  border-radius: 6px;
  background: #010409;
}
.preview-empty {
  display: grid;
  place-content: center;
  height: 80px;
  border-radius: 6px;
  background: #161b22;
  color: #484f58;
  font-size: 12px;
}

.detail-meta b { color: #e6edf3; font-size: 14px; }
.detail-meta p { margin: 4px 0 0; color: #8b949e; font-size: 13px; line-height: 1.5; }
.meta-error { color: #f85149 !important; }

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.detail-actions select,
.detail-actions input,
.detail-actions button {
  border: 1px solid #30363d;
  border-radius: 6px;
  background: #161b22;
  color: #e6edf3;
  padding: 5px 9px;
  font-size: 12px;
  cursor: pointer;
}
.duration-control {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #8b949e;
  font-size: 12px;
}
.duration-control input {
  width: 72px;
  cursor: text;
}
.detail-actions button:disabled {
  color: #484f58;
  cursor: not-allowed;
}

/* Candidate strip */
.candidate-strip {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 4px 0;
}
.cand-thumb {
  position: relative;
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  border: 2px solid #30363d;
  border-radius: 6px;
  overflow: hidden;
  padding: 0;
  cursor: pointer;
  background: #0d1117;
}
.cand-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.cand-thumb.active { border-color: #3fb950; }
.cand-thumb .check {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  background: rgba(63, 185, 80, 0.3);
  color: #fff;
  font-style: normal;
  font-size: 16px;
}

.action-msg { margin: 0; color: #8ddb8c; font-size: 11px; }
.action-err { margin: 0; color: #f85149; font-size: 11px; }

/* Media card LTX Desktop button */
.media-desktop-btn {
  position: absolute;
  top: 4px;
  right: 4px;
  z-index: 2;
  border: 1px solid #a371f7;
  border-radius: 4px;
  background: rgba(13, 17, 23, 0.85);
  color: #d2a8ff;
  padding: 1px 6px;
  font-size: 10px;
  cursor: pointer;
  line-height: 1.5;
  opacity: 0;
  transition: opacity 0.15s;
}
.media-card-wrap:hover .media-desktop-btn {
  opacity: 1;
}
.media-desktop-btn:hover {
  background: #1c2333;
  border-color: #c084fc;
}
.media-desktop-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* LTX Desktop button */
.btn-desktop {
  display: block;
  width: 100%;
  margin-top: 8px;
  border: 1px solid #a371f7;
  border-radius: 6px;
  background: #161b22;
  color: #d2a8ff;
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
  text-align: center;
}
.btn-desktop:hover {
  background: #1c2333;
  border-color: #c084fc;
}
.btn-desktop:disabled {
  color: #484f58;
  border-color: #30363d;
  cursor: not-allowed;
  background: #161b22;
}

/* LTX provider badges */
.ltx-local-badge {
  display: inline-block;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(88, 166, 255, 0.15);
  color: #58a6ff;
  white-space: nowrap;
}
.ltx-remote-badge {
  display: inline-block;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(248, 81, 73, 0.15);
  color: #f85149;
  white-space: nowrap;
}
</style>
