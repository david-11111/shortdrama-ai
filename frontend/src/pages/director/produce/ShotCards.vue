<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskPoller } from '@/composables/useTaskPoller'
import { directorExportFinal, directorProduce, normalizeMediaUrl } from '@/api/director'
import { applyShotSafeRewrite, continueProjectBrain, listShotRows, rollbackShotSafeRewrite } from '@/api/workbench'
import type { MediaCandidate, MediaReview, PromptRevisionPayload, Shot } from '@/composables/useDirectorSession'
import {
  deriveShotProductionState as deriveUnifiedShotProductionState,
} from './productionState'

const session = inject<any>('session')
const router = useRouter()
const pollingShots = ref(false)
const autoPolling = ref(false)
const exportingFinal = ref(false)
const exportProgress = ref(0)
const exportStage = ref('')
const finalUrl = ref('')
const exportError = ref('')
const productionError = ref('')
const rewritingShotIndex = ref<number | null>(null)
const rollingBackShotIndex = ref<number | null>(null)
const expandedShotIndex = ref<number | null>(null)
let shotTimer: ReturnType<typeof setInterval> | null = null

const isBusy = computed(() => exportingFinal.value || Number(session?.activeTaskCount?.value || 0) > 0)
const hasCuttableVideos = computed(() => {
  const shots = Array.isArray(session?.shots?.value) ? session.shots.value : []
  return shots.some((shot: Shot) => Boolean(String(shot.selected_video || '').trim()))
})

type ShotNextAction = 'safe_rewrite' | 'fill_assets' | 'generate_image' | 'manual_review' | 'regenerate' | 'generate_video' | 'edit' | 'done'

interface ShotProductionState {
  severity: 1 | 2 | 3 | 4
  next_action: ShotNextAction
  title: string
  reason: string
  cta: string
  detail: string
  complete: boolean
}

interface ShotCardItem {
  shot: Shot
  state: ShotProductionState
}

function pickFirstVideoUrl(raw: any): string | null {
  if (!Array.isArray(raw)) return null
  for (const item of raw) {
    if (typeof item === 'string' && item.trim()) return item.trim()
    if (item && typeof item === 'object') {
      const url = mediaUrl(item)
      if (url) return url
    }
  }
  return null
}

function mediaUrl(item: any): string {
  if (typeof item === 'string') return item.trim()
  if (!item || typeof item !== 'object') return ''
  return String(item.url || item.video_url || item.image_url || '').trim()
}

function displayUrl(value: string | null | undefined): string {
  return normalizeMediaUrl(value)
}

function selectedImageCandidate(shot: Shot): MediaCandidate | null {
  return findCandidate(shot.image_candidates, shot.selected_image)
}

function selectedVideoCandidate(shot: Shot): MediaCandidate | null {
  return findCandidate(shot.video_variants, shot.selected_video)
}

function findCandidate(items: Array<string | MediaCandidate>, selected: string | null): MediaCandidate | null {
  if (!selected) return null
  const selectedUrl = displayUrl(selected)
  for (const item of items || []) {
    const url = mediaUrl(item)
    if (displayUrl(url) !== selectedUrl) continue
    return typeof item === 'string' ? { url: item } : item
  }
  return null
}

function reviewOf(candidate: MediaCandidate | null): MediaReview | null {
  if (!candidate) return null
  if (candidate.review) return candidate.review
  const status = String(candidate.review_status || '').trim()
  if (!status && candidate.review_score === undefined) return null
  return {
    status: status || 'needs_review',
    score: Number(candidate.review_score || 0),
    notes: [],
    actions: [],
  }
}

function primaryReview(shot: Shot): { kind: 'image' | 'video'; review: MediaReview } | null {
  const videoReview = reviewOf(selectedVideoCandidate(shot))
  if (videoReview) return { kind: 'video', review: videoReview }
  const imageReview = reviewOf(selectedImageCandidate(shot))
  if (imageReview) return { kind: 'image', review: imageReview }
  return null
}

function reviewLabel(status = '') {
  const map: Record<string, string> = {
    usable: '可进视频',
    cuttable: '可剪辑',
    needs_review: '需复核',
    regenerate: '需重生',
  }
  return map[status] || status || '未审片'
}

function normalizePromptRevisionPayload(raw: any): PromptRevisionPayload {
  const items = Array.isArray(raw?.items) ? raw.items : []
  const latest = raw?.latest || items.find((item: any) => !item?.rolled_back_at) || null
  return {
    latest,
    items,
    count: Number(raw?.count ?? items.length ?? 0),
  }
}

function latestPromptRevision(shot: Shot) {
  const payload = shot.prompt_revision
  if (payload?.latest && !payload.latest.rolled_back_at) return payload.latest
  const items = Array.isArray(payload?.items) ? payload.items : []
  return items.find((item) => !item.rolled_back_at) || null
}

function revisionSourceLabel(source = '') {
  return source || 'unknown'
}

function formatRevisionTime(value = '') {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function reviewDecision(review: MediaReview, kind: 'image' | 'video') {
  if (review.status === 'usable') return kind === 'image' ? '可继续生成视频' : '可进入成片链路'
  if (review.status === 'cuttable') return '可剪辑，建议进入成片台精修'
  if (review.status === 'needs_review') return '人工确认后继续'
  if (review.status === 'regenerate') return kind === 'image' ? '建议重生关键帧' : '建议重生视频'
  return '等待制片判断'
}

function reviewNotes(review: MediaReview) {
  return Array.isArray(review.notes) ? review.notes.filter(Boolean) : []
}

function reviewActions(review: MediaReview) {
  return Array.isArray(review.actions) ? review.actions.filter(Boolean) : []
}

function deriveShotProductionState(shot: Shot): ShotProductionState {
  const state = deriveUnifiedShotProductionState(shot)
  const actionMap: Record<string, ShotNextAction> = {
    needs_rewrite: 'safe_rewrite',
    blocked: 'safe_rewrite',
    needs_assets: 'fill_assets',
    can_generate_image: 'generate_image',
    needs_image_review: state.review_status === 'regenerate' ? 'regenerate' : 'manual_review',
    can_generate_video: 'generate_video',
    needs_video_review: state.review_status === 'regenerate' ? 'regenerate' : 'manual_review',
    can_edit: 'edit',
    done: 'done',
  }
  const severityMap: Record<string, 1 | 2 | 3 | 4> = {
    danger: 4,
    warning: 3,
    ready: 2,
    info: 1,
    done: 1,
  }
  const nextAction = actionMap[state.next_action] || 'done'
  return {
    severity: severityMap[state.severity] || 1,
    next_action: nextAction,
    title: state.title,
    reason: state.reason,
    cta: state.primary_action_label,
    detail: state.blocking_refs.length ? `缺失参考：${state.blocking_refs.join('、')}` : state.reason,
    complete: nextAction === 'edit' || nextAction === 'done',
  }
}

const shotCards = computed<ShotCardItem[]>(() => {
  const shots = Array.isArray(session?.shots?.value) ? session.shots.value : []
  return shots
    .map((shot: Shot) => ({ shot, state: deriveShotProductionState(shot) }))
    .sort((a: ShotCardItem, b: ShotCardItem) => b.state.severity - a.state.severity || a.shot.index - b.shot.index)
})

const activeShotCards = computed(() => shotCards.value.filter((item) => !item.state.complete))
const completedShotCards = computed(() => shotCards.value.filter((item) => item.state.complete))
const failedShotCards = computed(() => shotCards.value.filter(({ shot }) => isFailedShot(shot)))

function shotThumbnail(shot: Shot) {
  return displayUrl(shot.selected_image)
}

function shotVideoUrl(shot: Shot) {
  return displayUrl(shot.selected_video)
}

function isFailedShot(shot: Shot) {
  const status = String(shot.status || '').toLowerCase()
  return Boolean(shot.last_error) || ['failed', 'error', 'dead_letter', 'cancelled'].includes(status)
}

function toggleShotDetail(shot: Shot) {
  expandedShotIndex.value = expandedShotIndex.value === shot.index ? null : shot.index
}

function isExpanded(shot: Shot) {
  return expandedShotIndex.value === shot.index
}

function acknowledgeReview(shot: Shot) {
  productionError.value = `分镜 #${shot.index} 已标记为人工确认，请根据审片备注决定继续生成或重生。`
}

function fillAssets(shot: Shot) {
  productionError.value = `分镜 #${shot.index} 需要补资产：请到参考图/资产池补齐角色、场景、道具、服装或风格参考。`
}

function runPrimaryAction(shot: Shot, state: ShotProductionState) {
  if (state.next_action === 'safe_rewrite') {
    void applySafeRewrite(shot)
    return
  }
  if (state.next_action === 'fill_assets') {
    fillAssets(shot)
    return
  }
  if (state.next_action === 'generate_image') {
    void produceOneImage(shot)
    return
  }
  if (state.next_action === 'manual_review') {
    acknowledgeReview(shot)
    return
  }
  if (state.next_action === 'regenerate') {
    const review = primaryReview(shot)
    if (review) regenerateFromReview(shot, review.kind)
    return
  }
  if (state.next_action === 'generate_video') {
    void produceOneVideo(shot)
    return
  }
  if (state.next_action === 'edit' || state.next_action === 'done') {
    void goFinalCut()
  }
}

function primaryDisabled(shot: Shot, state: ShotProductionState) {
  if (isBusy.value && state.next_action !== 'fill_assets' && state.next_action !== 'manual_review') return true
  if (state.next_action === 'safe_rewrite') return rewritingShotIndex.value === shot.index || !shot.director_preflight?.safe_prompt
  if (state.next_action === 'generate_video') return !shot.selected_image
  if (state.next_action === 'regenerate') {
    const review = primaryReview(shot)
    return review?.kind === 'video' && !shot.selected_image
  }
  if (state.next_action === 'edit' || state.next_action === 'done') return exportingFinal.value || !shot.selected_video
  return false
}

function primaryLabel(shot: Shot, state: ShotProductionState) {
  if (state.next_action === 'safe_rewrite' && rewritingShotIndex.value === shot.index) return '改写中...'
  if ((state.next_action === 'edit' || state.next_action === 'done') && exportingFinal.value) return '导出中...'
  return state.cta
}

async function goFinalCut() {
  const projectId = String(session?.projectId?.value || '').trim()
  if (!projectId) return
  await router.push(`/director/final-cut/${projectId}`)
}

function mapShots(rows: any[]): Shot[] {
  return rows.map((r: any) => {
    const shot: Shot = {
      index: Number(r.shot_index || r.index || 0),
      prompt: r.prompt || '',
      duration: Number(r.duration || 5),
      status: r.status || 'draft',
      image_candidates: r.image_candidates || [],
      video_variants: r.video_variants || [],
      selected_image: r.selected_image || null,
      selected_video: r.selected_video || pickFirstVideoUrl(r.video_variants || r.video_variants_json) || null,
      character_refs: r.character_refs_json || r.character_refs || [],
      scene_refs: r.scene_refs_json || r.scene_refs || [],
      prop_refs: r.prop_refs_json || r.prop_refs || [],
      costume_refs: r.costume_refs_json || r.costume_refs || [],
      style_refs: r.style_refs_json || r.style_refs || [],
      last_error: r.last_error || '',
      prompt_revision: r.prompt_revision ? normalizePromptRevisionPayload(r.prompt_revision) : undefined,
      director_preflight: r.director_preflight || undefined,
    }
    return { ...shot, production_state: deriveUnifiedShotProductionState(shot) }
  })
}

function syncRefImagesFromShots(nextShots: Shot[]) {
  const existing = Array.isArray(session.refImages.value) ? session.refImages.value : []
  const keepPending = existing.filter((item: any) => item?.pending)
  const byUrl = new Map<string, any>()

  existing.forEach((item: any) => {
    if (item?.url) byUrl.set(item.url, item)
  })

  nextShots.forEach((shot: Shot) => {
    if (!shot.selected_image) return
    if (byUrl.has(shot.selected_image)) return
    byUrl.set(shot.selected_image, {
      id: `shot-${shot.index}-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`,
      url: shot.selected_image,
      view: `shot_${shot.index}`,
      lineage_role: 'derived',
      selected: false,
      pending: false,
    })
  })

  const merged = [...keepPending, ...Array.from(byUrl.values())]
  session.refImages.value = merged
}

function isGenerating(status: string) {
  return status.includes('generating') || status.includes('running')
}

function badgeLabel(status: string) {
  const map: Record<string, string> = {
    draft: '草稿',
    ready: '就绪',
    generating_image: '出图中',
    image_done: '图完成',
    generating_video: '视频中',
    video_done: '视频完成',
    error: '失败',
  }
  return map[status] || status
}

function blockedShots() {
  return session.shots.value.filter((shot: Shot) => shot.director_preflight?.risk_level === 'blocked')
}

function formatApiError(error: any) {
  const detail = error?.response?.data?.detail
  if (detail?.error === 'director_preflight_blocked') {
    const shots = Array.isArray(detail.blocked_shots) ? detail.blocked_shots : []
    const labels = shots.map((item: any) => `#${item.shot_index || '?'}`).join('、')
    return `${detail.message || '生成前审查未通过'}${labels ? `：${labels}` : ''}`
  }
  if (typeof detail === 'string') return detail
  return error?.message || '任务提交失败'
}

function ensureNoBlockedShots() {
  const blocked = blockedShots()
  if (!blocked.length) return true
  productionError.value = `有 ${blocked.length} 个高风险分镜，请先应用安全改写或手动修正：${blocked.map((shot: Shot) => `#${shot.index}`).join('、')}`
  return false
}

async function loadShots() {
  if (!session.projectId.value) return
  pollingShots.value = true
  try {
    const { data } = await listShotRows(session.projectId.value)
    const rows = data?.items || data?.rows || data || []
    const nextShots = Array.isArray(rows) ? mapShots(rows) : []
    session.shots.value = nextShots
    syncRefImagesFromShots(nextShots)
  } catch {
    session.shots.value = []
  } finally {
    pollingShots.value = false
  }
}

function startAutoPoll() {
  stopAutoPoll()
  if (!session.projectId.value) return
  autoPolling.value = true
  void loadShots()
  shotTimer = setInterval(() => {
    void loadShots()
  }, 5000)
}

function stopAutoPoll() {
  autoPolling.value = false
  if (shotTimer) {
    clearInterval(shotTimer)
    shotTimer = null
  }
}

function trackTask(taskId: string, onComplete?: (result: any, status: string) => void) {
  const poller = useTaskPoller()
  session.beginTask()
  poller.start(taskId)
  const timer = setInterval(() => {
    if (poller.stageText.value) exportStage.value = poller.stageText.value
    exportProgress.value = Math.max(exportProgress.value, Number(poller.progress.value || 0))
    if (!poller.isPolling.value && poller.status.value) {
      clearInterval(timer)
      session.endTask()
      onComplete?.(poller.result.value, poller.status.value)
      void loadShots()
    }
  }, 200)
}

function continueTaskIds(data: any): string[] {
  const ids = Array.isArray(data?.child_task_ids)
    ? data.child_task_ids
    : Array.isArray(data?.task_ids)
      ? data.task_ids
      : data?.task_id
        ? [data.task_id]
        : []
  return ids.map((id: unknown) => String(id || '').trim()).filter(Boolean)
}

async function batchImages() {
  if (!session.projectId.value) return
  if (!session.shots.value.length) return
  productionError.value = ''
  if (!ensureNoBlockedShots()) return
  try {
    const { data } = await continueProjectBrain(session.projectId.value, { action: 'generate_keyframes' })
    continueTaskIds(data).forEach((id) => trackTask(id))
  } catch (error: any) {
    productionError.value = formatApiError(error)
  }
}

async function produceOneImage(shot: Shot) {
  if (!session.projectId.value) return
  if (!shot?.index) return
  productionError.value = ''
  if (shot.director_preflight?.risk_level === 'blocked') {
    productionError.value = `分镜 #${shot.index} 仍是高风险，请先应用安全改写。`
    return
  }
  try {
    const { data } = await continueProjectBrain(session.projectId.value, {
      action: 'generate_keyframes',
      instruction: `generate keyframe for shot #${shot.index}`,
      shot_indices: [shot.index],
    })
    continueTaskIds(data).forEach((id) => trackTask(id))
  } catch (error: any) {
    productionError.value = formatApiError(error)
  }
}

async function batchVideos() {
  await produceVideosOnly()
}

async function produceVideosOnly() {
  if (!session.projectId.value) return
  productionError.value = ''
  if (!ensureNoBlockedShots()) return
  const shotIndices = session.shots.value
    .filter((s: Shot) => s.selected_image)
    .map((s: Shot) => s.index)
  if (!shotIndices.length) return
  try {
    const { data } = await directorProduce({
      project_id: session.projectId.value,
      shot_indices: shotIndices,
      skip_images: true,
      provider: 'joy-echo',
      anchor_locks: { ...session.anchorLocks.value },
    })
    if (data?.task_id) {
      trackTask(data.task_id)
    }
  } catch (error: any) {
    productionError.value = formatApiError(error)
  }
}

async function produce() {
  if (!session.projectId.value) return
  productionError.value = ''
  if (!ensureNoBlockedShots()) return
  try {
    const { data } = await directorProduce({
      project_id: session.projectId.value,
      provider: 'joy-echo',
      anchor_locks: { ...session.anchorLocks.value },
    })
    if (data?.task_id) {
      trackTask(data.task_id)
    }
  } catch (error: any) {
    productionError.value = formatApiError(error)
  }
}

async function produceOneVideo(shot: Shot) {
  if (!session.projectId.value) return
  if (!shot?.index || !shot.selected_image) return
  productionError.value = ''
  if (shot.director_preflight?.risk_level === 'blocked') {
    productionError.value = `分镜 #${shot.index} 仍是高风险，请先应用安全改写。`
    return
  }
  try {
    const { data } = await directorProduce({
      project_id: session.projectId.value,
      shot_indices: [shot.index],
      skip_images: true,
      provider: 'joy-echo',
      anchor_locks: { ...session.anchorLocks.value },
    })
    if (data?.task_id) {
      trackTask(data.task_id)
    }
  } catch (error: any) {
    productionError.value = formatApiError(error)
  }
}

function regenerateFromReview(shot: Shot, kind: 'image' | 'video') {
  if (kind === 'video') {
    void produceOneVideo(shot)
    return
  }
  void produceOneImage(shot)
}

async function applySafeRewrite(shot: Shot) {
  if (!session.projectId.value || !shot?.index) return
  rewritingShotIndex.value = Number(shot.index)
  productionError.value = ''
  try {
    const { data } = await applyShotSafeRewrite(session.projectId.value, Number(shot.index))
    if (data?.prompt) {
      session.shots.value = session.shots.value.map((row: Shot) => {
        if (Number(row.index) !== Number(shot.index)) return row
        return {
          ...row,
          prompt: data.prompt,
          director_preflight: data.director_preflight || undefined,
          prompt_revision: normalizePromptRevisionPayload({ latest: data.prompt_revision, items: data.prompt_revision ? [data.prompt_revision] : [] }),
        }
      })
    }
    expandedShotIndex.value = Number(shot.index)
    await loadShots()
  } catch (error: any) {
    productionError.value = error?.response?.data?.detail || error?.message || '应用安全改写失败'
  } finally {
    rewritingShotIndex.value = null
  }
}

async function rollbackSafeRewrite(shot: Shot) {
  if (!session.projectId.value || !shot?.index) return
  const revision = latestPromptRevision(shot)
  if (!revision) return
  rollingBackShotIndex.value = Number(shot.index)
  productionError.value = ''
  try {
    await rollbackShotSafeRewrite(session.projectId.value, Number(shot.index), { revision_id: revision.revision_id })
    await loadShots()
    expandedShotIndex.value = null
  } catch (error: any) {
    productionError.value = error?.response?.data?.detail?.message || error?.response?.data?.detail || error?.message || '回滚安全改写失败'
  } finally {
    rollingBackShotIndex.value = null
  }
}

async function exportFinal() {
  if (!session.projectId.value) return
  exportError.value = ''
  finalUrl.value = ''
  exportProgress.value = 0
  exportStage.value = '提交最终成片导出...'
  exportingFinal.value = true
  const shotIndices = session.shots.value
    .filter((s: Shot) => s.selected_video)
    .map((s: Shot) => s.index)
  try {
    const { data } = await directorExportFinal({
      project_id: session.projectId.value,
      shot_indices: shotIndices.length ? shotIndices : undefined,
    })
    trackTask(data.task_id, (result, status) => {
      exportingFinal.value = false
      if (status === 'done' && result?.final_url) {
        finalUrl.value = result.final_url
        exportProgress.value = 100
        exportStage.value = `最终成片已导出，共 ${result.clip_count || data.clip_count || 0} 段`
      } else {
        exportError.value = '最终成片导出失败，请到任务详情查看错误'
      }
    })
  } catch (error: any) {
    exportingFinal.value = false
    exportError.value = error?.response?.data?.detail?.message || error?.response?.data?.detail || error?.message || '导出提交失败'
  }
}

onMounted(() => {
  if (session.projectId.value) startAutoPoll()
})

watch(
  () => session.projectId.value,
  (value) => {
    if (value) startAutoPoll()
    else stopAutoPoll()
  },
)

onUnmounted(() => {
  stopAutoPoll()
})
</script>

<template>
  <section class="shot-cards card">
    <div class="shots-header">
      <h3>分镜卡片 ({{ session.shots.value.length }})</h3>
      <span class="polling-tag" :class="{ active: autoPolling }">{{ autoPolling ? '自动轮询中' : '未轮询' }}</span>
    </div>

    <div class="export-actions">
      <button
        class="tool-btn tool-btn--primary transition-all"
        type="button"
        :disabled="!hasCuttableVideos"
        @click="goFinalCut"
      >
        <span>▶</span>
        <b>进入剪辑台预览</b>
      </button>
      <button
        class="tool-btn tool-btn--export transition-all"
        type="button"
        :disabled="exportingFinal || !session.shots.value.some((s: Shot) => s.selected_video)"
        @click="exportFinal"
      >
        <span>▶</span>
        <b>{{ exportingFinal ? '导出中...' : '导出最终成片' }}</b>
      </button>
      <a v-if="finalUrl" class="final-link" :href="finalUrl" target="_blank" rel="noopener">打开成片</a>
    </div>
    <div v-if="exportingFinal || exportError" class="export-panel">
      <div class="export-row">
        <strong>最终成片</strong>
        <span v-if="exportingFinal">{{ exportProgress }}%</span>
      </div>
      <div v-if="exportingFinal" class="export-progress">
        <div :style="{ width: `${exportProgress}%` }"></div>
      </div>
      <p v-if="exportStage" class="export-stage">{{ exportStage }}</p>
      <p v-if="exportError" class="shot-error">{{ exportError }}</p>
    </div>

    <div class="toolbar">
      <button class="tool-btn transition-all" type="button" :disabled="!session.shots.value.length" @click="batchImages">
        <span>⊞</span>
        <b>全部分镜出图</b>
      </button>
      <button class="tool-btn transition-all" type="button" :disabled="!session.shots.value.some((s: Shot) => s.selected_image)" @click="batchVideos">
        <span>▶</span>
        <b>已选图批量视频</b>
      </button>
      <button class="tool-btn transition-all" type="button" :disabled="!session.shots.value.some((s: Shot) => s.selected_image)" @click="produceVideosOnly">
        <span>▣</span>
        <b>仅视频生产</b>
      </button>
      <button class="tool-btn tool-btn--primary transition-all" type="button" :disabled="!session.shots.value.length" @click="produce">
        <span>⚙</span>
        <b>全流程生产（图+视频）</b>
      </button>
    </div>
    <p class="toolbar-hint">参考图在左侧“参考图 > 生成参考图”；“全流程生产”=先出图再出视频；如果你已绑好参考图，直接用“仅视频生产”或卡片内“单条视频”。</p>

    <p v-if="productionError" class="shot-error production-error">{{ productionError }}</p>

    <div class="anchor-locks">
      <label><input type="checkbox" v-model="session.anchorLocks.value.lock_character" /> 锁角色</label>
      <label><input type="checkbox" v-model="session.anchorLocks.value.lock_scene" /> 锁场景</label>
      <label><input type="checkbox" v-model="session.anchorLocks.value.lock_costume" /> 锁服装</label>
      <label><input type="checkbox" v-model="session.anchorLocks.value.lock_prop" /> 锁道具</label>
    </div>
    <p class="anchor-note">锁定项会随“仅视频生产 / 全流程生产 / 单条视频”请求下发，作用于连续性约束。</p>

    <section v-if="failedShotCards.length" class="failed-shots">
      <div class="failed-head">
        <strong>失败镜头</strong>
        <span>{{ failedShotCards.length }} 个需要重试</span>
      </div>
      <article v-for="{ shot } in failedShotCards" :key="`failed-${shot.index}`" class="failed-row">
        <div>
          <b>#{{ shot.index }}</b>
          <p>{{ shot.last_error || badgeLabel(shot.status) || '生成失败' }}</p>
        </div>
        <div class="failed-actions">
          <button class="shot-action-btn transition-all" type="button" @click="produceOneImage(shot)">重试关键帧</button>
          <button class="shot-action-btn transition-all" type="button" :disabled="!shot.selected_image" @click="produceOneVideo(shot)">重试视频</button>
        </div>
      </article>
    </section>

    <div v-if="pollingShots && !session.shots.value.length" class="empty">分镜加载中...</div>
    <div v-else-if="!session.shots.value.length" class="empty">暂无分镜，请先通过导演对话生成脚本。</div>

    <div v-else class="problem-board">
      <div v-if="activeShotCards.length" class="problem-group">
        <div class="problem-group-head">
          <strong>待处理</strong>
          <span>{{ activeShotCards.length }} 个问题</span>
        </div>
        <article
          v-for="{ shot, state } in activeShotCards"
          :key="shot.index"
          :id="`shot-${shot.index}`"
          class="problem-card transition-all"
          :class="[`severity-${state.severity}`, { running: isGenerating(shot.status), expanded: isExpanded(shot) }]"
        >
          <div class="problem-main">
            <div class="problem-shot">
              <span class="shot-idx">#{{ shot.index }}</span>
              <span class="badge" :class="{ generating: isGenerating(shot.status) }">{{ badgeLabel(shot.status) }}</span>
            </div>
            <div class="problem-copy">
              <h4>{{ state.title }}</h4>
              <p>{{ state.reason }}</p>
            </div>
            <div class="problem-thumb">
              <img v-if="shotThumbnail(shot)" :src="shotThumbnail(shot)" alt="" />
              <span v-else>{{ shot.duration }}s</span>
            </div>
            <button
              class="primary-action transition-all"
              type="button"
              :disabled="primaryDisabled(shot, state)"
              @click="runPrimaryAction(shot, state)"
            >
              {{ primaryLabel(shot, state) }}
            </button>
            <button class="detail-toggle" type="button" @click="toggleShotDetail(shot)">
              {{ isExpanded(shot) ? '收起' : '查看详情' }}
            </button>
          </div>

          <div v-if="isExpanded(shot)" class="problem-detail">
            <div class="detail-grid">
              <section>
                <h5>Prompt</h5>
                <p>{{ shot.prompt || '暂无 prompt' }}</p>
                <template v-if="shot.director_preflight?.safe_prompt">
                  <h5>Safe Prompt</h5>
                  <p>{{ shot.director_preflight.safe_prompt }}</p>
                </template>
              </section>
              <section v-if="shot.director_preflight?.risk_count">
                <h5>导演审查</h5>
                <p>{{ state.detail }}</p>
                <ul>
                  <li v-for="risk in shot.director_preflight.risks" :key="risk.code || risk.title">{{ risk.title }}：{{ risk.reason }}</li>
                </ul>
              </section>
              <section v-if="primaryReview(shot)">
                <h5>审片报告</h5>
                <p>{{ reviewLabel(primaryReview(shot)?.review.status) }} · {{ primaryReview(shot)?.review.score || 0 }} 分 · {{ reviewDecision(primaryReview(shot)!.review, primaryReview(shot)!.kind) }}</p>
                <div v-if="reviewNotes(primaryReview(shot)!.review).length">
                  <strong>Notes</strong>
                  <ul>
                    <li v-for="note in reviewNotes(primaryReview(shot)!.review)" :key="note">{{ note }}</li>
                  </ul>
                </div>
                <div v-if="reviewActions(primaryReview(shot)!.review).length">
                  <strong>Actions</strong>
                  <ul>
                    <li v-for="action in reviewActions(primaryReview(shot)!.review)" :key="action">{{ action }}</li>
                  </ul>
                </div>
              </section>
              <section v-if="shot.prompt_revision?.count">
                <div class="detail-section-head">
                  <h5>版本记录</h5>
                  <button
                    v-if="latestPromptRevision(shot)"
                    class="shot-action-btn transition-all"
                    type="button"
                    :disabled="rollingBackShotIndex === shot.index"
                    @click="rollbackSafeRewrite(shot)"
                  >
                    {{ rollingBackShotIndex === shot.index ? '回滚中...' : '回滚安全改写' }}
                  </button>
                </div>
                <template v-for="revision in shot.prompt_revision.items || []" :key="revision.revision_id">
                  <dl class="revision-detail">
                    <dt>来源</dt>
                    <dd>{{ revisionSourceLabel(revision.source) }}</dd>
                    <dt>时间</dt>
                    <dd>{{ formatRevisionTime(revision.created_at) }}</dd>
                    <dt>原 prompt</dt>
                    <dd>{{ revision.original_prompt || '-' }}</dd>
                    <dt>改写 prompt</dt>
                    <dd>{{ revision.rewritten_prompt || '-' }}</dd>
                    <dt>状态</dt>
                    <dd>{{ revision.rolled_back_at ? `已回滚 ${formatRevisionTime(revision.rolled_back_at)}` : '已应用' }}</dd>
                  </dl>
                </template>
              </section>
              <section v-if="shot.selected_video || shot.selected_image || shot.last_error">
                <h5>素材</h5>
                <video v-if="shotVideoUrl(shot)" :src="shotVideoUrl(shot)" controls preload="metadata"></video>
                <img v-else-if="shotThumbnail(shot)" :src="shotThumbnail(shot)" alt="" />
                <p v-if="shot.last_error" class="shot-error">{{ shot.last_error }}</p>
                <div class="detail-actions">
                  <a
                    v-if="shotVideoUrl(shot)"
                    class="shot-action-btn shot-action-link transition-all"
                    :href="shotVideoUrl(shot)"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    打开视频
                  </a>
                  <button class="shot-action-btn transition-all" type="button" @click="produceOneImage(shot)">重出关键帧</button>
                  <button class="shot-action-btn transition-all" type="button" :disabled="!shot.selected_image" @click="produceOneVideo(shot)">重出视频</button>
                </div>
              </section>
            </div>
          </div>
        </article>
      </div>

      <details v-if="completedShotCards.length" class="problem-group completed-group">
        <summary>
          <strong>可继续 / 已完成</strong>
          <span>{{ completedShotCards.length }} 条</span>
        </summary>
        <article
          v-for="{ shot, state } in completedShotCards"
          :key="shot.index"
          :id="`shot-${shot.index}`"
          class="problem-card compact transition-all"
          :class="[`severity-${state.severity}`, { expanded: isExpanded(shot) }]"
        >
          <div class="problem-main">
            <div class="problem-shot">
              <span class="shot-idx">#{{ shot.index }}</span>
              <span class="badge">{{ badgeLabel(shot.status) }}</span>
            </div>
            <div class="problem-copy">
              <h4>{{ state.title }}</h4>
              <p>{{ state.reason }}</p>
            </div>
            <div class="problem-thumb">
              <img v-if="shotThumbnail(shot)" :src="shotThumbnail(shot)" alt="" />
              <span v-else>{{ shot.duration }}s</span>
            </div>
            <button class="primary-action transition-all" type="button" :disabled="primaryDisabled(shot, state)" @click="runPrimaryAction(shot, state)">
              {{ primaryLabel(shot, state) }}
            </button>
            <button class="detail-toggle" type="button" @click="toggleShotDetail(shot)">
              {{ isExpanded(shot) ? '收起' : '查看详情' }}
            </button>
          </div>
          <div v-if="isExpanded(shot)" class="problem-detail">
            <div class="detail-grid">
              <section>
                <h5>Prompt</h5>
                <p>{{ shot.prompt || '暂无 prompt' }}</p>
              </section>
              <section v-if="primaryReview(shot)">
                <h5>审片报告</h5>
                <p>{{ reviewLabel(primaryReview(shot)?.review.status) }} · {{ primaryReview(shot)?.review.score || 0 }} 分 · {{ reviewDecision(primaryReview(shot)!.review, primaryReview(shot)!.kind) }}</p>
                <ul v-if="reviewNotes(primaryReview(shot)!.review).length">
                  <li v-for="note in reviewNotes(primaryReview(shot)!.review)" :key="note">{{ note }}</li>
                </ul>
                <ul v-if="reviewActions(primaryReview(shot)!.review).length">
                  <li v-for="action in reviewActions(primaryReview(shot)!.review)" :key="action">{{ action }}</li>
                </ul>
              </section>
              <section v-if="shot.prompt_revision?.count">
                <div class="detail-section-head">
                  <h5>版本记录</h5>
                  <button
                    v-if="latestPromptRevision(shot)"
                    class="shot-action-btn transition-all"
                    type="button"
                    :disabled="rollingBackShotIndex === shot.index"
                    @click="rollbackSafeRewrite(shot)"
                  >
                    回滚安全改写
                  </button>
                </div>
                <template v-for="revision in shot.prompt_revision.items || []" :key="revision.revision_id">
                  <dl class="revision-detail">
                    <dt>原 prompt</dt>
                    <dd>{{ revision.original_prompt || '-' }}</dd>
                    <dt>改写 prompt</dt>
                    <dd>{{ revision.rewritten_prompt || '-' }}</dd>
                  </dl>
                </template>
              </section>
              <section v-if="shot.selected_video || shot.selected_image">
                <h5>素材</h5>
                <video v-if="shotVideoUrl(shot)" :src="shotVideoUrl(shot)" controls preload="metadata"></video>
                <img v-else-if="shotThumbnail(shot)" :src="shotThumbnail(shot)" alt="" />
              </section>
            </div>
          </div>
        </article>
      </details>
    </div>
  </section>
</template>

<style scoped>
.card {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.shot-cards {
  padding: 1rem;
}

.shots-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

h3 {
  margin: 0;
  font-size: 0.98rem;
}

.polling-tag {
  font-size: 0.74rem;
  color: var(--color-text-secondary);
}

.polling-tag.active {
  color: var(--color-success);
}

.export-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.75rem;
}

.tool-btn--export {
  border-color: color-mix(in srgb, var(--color-success) 65%, var(--color-border));
}

.final-link {
  display: inline-flex;
  align-items: center;
  height: 34px;
  padding: 0 0.75rem;
  border: 1px solid color-mix(in srgb, var(--color-success) 55%, var(--color-border));
  border-radius: var(--radius-md);
  color: var(--color-success);
  background: color-mix(in srgb, var(--color-success) 10%, var(--color-bg));
  font-size: 0.78rem;
}

.export-panel {
  margin-bottom: 0.75rem;
  padding: 0.7rem;
  border: 1px solid color-mix(in srgb, var(--color-success) 30%, var(--color-border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 72%, var(--color-bg));
}

.export-row {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
  font-size: 0.82rem;
}

.export-progress {
  margin-top: 0.55rem;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--color-bg);
}

.export-progress div {
  height: 100%;
  border-radius: inherit;
  background: var(--color-success);
  transition: width 0.2s ease;
}

.export-stage {
  margin: 0.45rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.75rem;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.75rem;
}

.tool-btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  border-radius: var(--radius-md);
  height: 34px;
  padding: 0 0.75rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}

.tool-btn span {
  font-size: 0.85rem;
}

.tool-btn b {
  font-size: 0.78rem;
  font-weight: 600;
}

.tool-btn--primary {
  border-color: color-mix(in srgb, var(--color-primary) 65%, var(--color-border));
}

.tool-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
}

.tool-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.toolbar-hint {
  margin: 0 0 0.75rem;
  font-size: 0.74rem;
  color: var(--color-text-secondary);
}

.anchor-locks {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
  margin-bottom: 0.8rem;
}

.anchor-locks label {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.anchor-note {
  margin: -0.35rem 0 0.8rem;
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}

.failed-shots {
  display: grid;
  gap: 0.55rem;
  margin-bottom: 0.8rem;
  padding: 0.7rem;
  border: 1px solid color-mix(in srgb, var(--color-error) 52%, var(--color-border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-error) 9%, var(--color-bg-secondary));
}

.failed-head,
.failed-row,
.failed-actions {
  display: flex;
  align-items: center;
  gap: 0.55rem;
}

.failed-head,
.failed-row {
  justify-content: space-between;
}

.failed-head strong,
.failed-row b {
  color: var(--color-text);
  font-size: 0.82rem;
}

.failed-head span,
.failed-row p {
  color: var(--color-text-secondary);
  font-size: 0.74rem;
}

.failed-row p {
  margin: 0.15rem 0 0;
}

.problem-board {
  display: grid;
  gap: 0.85rem;
}

.problem-group {
  display: grid;
  gap: 0.55rem;
}

.problem-group-head,
.completed-group summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  color: var(--color-text);
  font-size: 0.84rem;
}

.problem-group-head span,
.completed-group summary span {
  color: var(--color-text-secondary);
  font-size: 0.74rem;
}

.completed-group {
  border-top: 1px solid var(--color-border);
  padding-top: 0.75rem;
}

.completed-group summary {
  cursor: pointer;
  list-style: none;
}

.completed-group summary::-webkit-details-marker {
  display: none;
}

.completed-group[open] {
  gap: 0.55rem;
}

.problem-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 58%, var(--color-bg));
  overflow: hidden;
}

.problem-card:hover {
  border-color: color-mix(in srgb, var(--color-primary) 46%, var(--color-border));
}

.problem-card.running {
  border-color: color-mix(in srgb, var(--color-primary) 68%, var(--color-border));
}

.problem-card.severity-4 {
  border-left: 3px solid var(--color-error);
}

.problem-card.severity-3 {
  border-left: 3px solid var(--color-warning);
}

.problem-card.severity-2 {
  border-left: 3px solid var(--color-primary);
}

.problem-card.severity-1 {
  border-left: 3px solid var(--color-success);
}

.problem-main {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr) 72px 112px 72px;
  align-items: center;
  gap: 0.75rem;
  min-height: 74px;
  padding: 0.55rem 0.65rem;
}

.problem-shot {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.problem-copy {
  min-width: 0;
}

.problem-copy h4 {
  margin: 0;
  color: var(--color-text);
  font-size: 0.88rem;
  line-height: 1.25;
}

.problem-copy p {
  margin: 0.22rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.75rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.problem-thumb {
  width: 64px;
  height: 42px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  overflow: hidden;
  display: grid;
  place-items: center;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.problem-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.primary-action,
.detail-toggle {
  height: 32px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.74rem;
}

.primary-action {
  border: 1px solid color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
  background: var(--color-primary);
  color: #fff;
  font-weight: 700;
}

.detail-toggle {
  border: 1px solid var(--color-border);
  background: var(--color-bg);
  color: var(--color-text-secondary);
}

.primary-action:hover:not(:disabled),
.detail-toggle:hover {
  transform: translateY(-1px);
}

.primary-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.problem-detail {
  border-top: 1px solid var(--color-border);
  padding: 0.75rem;
  background: color-mix(in srgb, var(--color-bg) 70%, var(--color-bg-secondary));
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.75rem;
}

.detail-grid section {
  min-width: 0;
  padding: 0.65rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
}

.detail-grid h5 {
  margin: 0 0 0.4rem;
  color: var(--color-text);
  font-size: 0.78rem;
}

.detail-grid p,
.detail-grid li,
.detail-grid dd,
.detail-grid dt {
  font-size: 0.74rem;
  line-height: 1.45;
}

.detail-grid p {
  margin: 0;
  color: var(--color-text-secondary);
  word-break: break-word;
}

.detail-grid ul {
  margin: 0.4rem 0 0;
  padding-left: 1rem;
  color: var(--color-text-secondary);
}

.detail-grid strong {
  display: block;
  margin: 0.5rem 0 0.2rem;
  color: var(--color-text);
  font-size: 0.72rem;
}

.detail-grid img,
.detail-grid video {
  width: 100%;
  max-height: 220px;
  object-fit: contain;
  border-radius: var(--radius-sm);
  background: #000;
}

.detail-section-head,
.detail-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.detail-actions {
  justify-content: flex-start;
  margin-top: 0.5rem;
}

.problem-detail .revision-detail {
  margin: 0.45rem 0 0;
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 0.25rem 0.5rem;
}

.problem-detail .revision-detail dt {
  color: var(--color-text-secondary);
}

.problem-detail .revision-detail dd {
  margin: 0;
  color: var(--color-text);
  word-break: break-word;
}

.shots-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 0.8rem;
}

.shot-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 0.7rem;
  background: color-mix(in srgb, var(--color-bg-secondary) 65%, var(--color-bg));
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.16);
}

.shot-card:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--color-primary) 58%, var(--color-border));
}

.shot-card.running {
  border-color: color-mix(in srgb, var(--color-primary) 68%, var(--color-border));
  animation: pulse-glow 2s ease-in-out infinite;
}

.shot-top {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.35rem;
}

.shot-idx {
  font-weight: 700;
  font-size: 0.82rem;
}

.badge {
  padding: 0.14rem 0.48rem;
  border-radius: 999px;
  font-size: 0.68rem;
  border: 1px solid color-mix(in srgb, var(--color-text-secondary) 40%, transparent);
  color: var(--color-text-secondary);
}

.badge.generating {
  border-color: color-mix(in srgb, var(--color-warning) 58%, var(--color-border));
  color: var(--color-warning);
  animation: pulse-glow 1.5s ease-in-out infinite;
}

.shot-dur {
  margin-left: auto;
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}

.shot-prompt {
  margin: 0 0 0.5rem;
  font-size: 0.8rem;
  line-height: 1.45;
  color: var(--color-text);
  min-height: 46px;
}

.preflight-box {
  margin-bottom: 0.55rem;
  padding: 0.55rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
}

.preflight-box.blocked {
  border-color: color-mix(in srgb, var(--color-error) 60%, var(--color-border));
}

.preflight-box.warning {
  border-color: color-mix(in srgb, #f59e0b 60%, var(--color-border));
}

.preflight-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: center;
  font-size: 0.76rem;
}

.preflight-head strong {
  color: var(--color-text);
}

.preflight-head span,
.preflight-box p {
  color: var(--color-text-secondary);
}

.preflight-box p {
  margin: 0.35rem 0 0.45rem;
  font-size: 0.74rem;
  line-height: 1.45;
}

.revision-box {
  margin-bottom: 0.55rem;
  padding: 0.55rem;
  border: 1px solid color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-success) 8%, var(--color-bg-secondary));
}

.revision-head,
.revision-actions {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: center;
}

.revision-head {
  font-size: 0.76rem;
}

.revision-head span {
  color: var(--color-text-secondary);
}

.revision-actions {
  justify-content: flex-start;
  margin-top: 0.45rem;
}

.revision-detail {
  margin-top: 0.5rem;
  display: grid;
  gap: 0.45rem;
}

.revision-detail dl {
  margin: 0;
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 0.25rem 0.5rem;
  font-size: 0.72rem;
}

.revision-detail dt {
  color: var(--color-text-secondary);
}

.revision-detail dd {
  margin: 0;
  color: var(--color-text);
  word-break: break-word;
}

.review-box {
  margin-top: 0.55rem;
  padding: 0.55rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
}

.review-box.ready {
  border-color: color-mix(in srgb, var(--color-success) 55%, var(--color-border));
}

.review-box.warning {
  border-color: color-mix(in srgb, #f59e0b 58%, var(--color-border));
}

.review-box.blocked {
  border-color: color-mix(in srgb, var(--color-error) 58%, var(--color-border));
}

.review-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.76rem;
}

.review-head strong {
  color: var(--color-text);
}

.review-head span,
.review-box p {
  color: var(--color-text-secondary);
}

.review-box p {
  margin: 0.35rem 0 0;
  font-size: 0.74rem;
  line-height: 1.45;
}

.review-decision {
  color: var(--color-text) !important;
  font-weight: 700;
}

.review-section {
  margin-top: 0.45rem;
}

.review-section span {
  display: block;
  margin-bottom: 0.22rem;
  color: var(--color-text-secondary);
  font-size: 0.7rem;
  font-weight: 700;
}

.review-section ul {
  margin: 0;
  padding-left: 1rem;
  color: var(--color-text-secondary);
  font-size: 0.73rem;
  line-height: 1.45;
}

.review-section li + li {
  margin-top: 0.18rem;
}

.review-regenerate {
  width: 100%;
  margin-top: 0.55rem;
  border: 1px solid color-mix(in srgb, var(--color-error) 58%, var(--color-border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-error) 12%, var(--color-bg));
  color: var(--color-error);
  height: 32px;
  cursor: pointer;
  font-size: 0.76rem;
  font-weight: 700;
}

.review-regenerate:hover:not(:disabled) {
  transform: translateY(-1px);
  background: color-mix(in srgb, var(--color-error) 18%, var(--color-bg));
}

.review-regenerate:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.shot-thumb img {
  width: 100%;
  aspect-ratio: 16 / 10;
  border-radius: 6px;
  object-fit: cover;
}

.shot-video video {
  width: 100%;
  aspect-ratio: 16 / 10;
  border-radius: 6px;
  object-fit: cover;
  background: #000;
}

.thumb-skeleton {
  width: 100%;
  aspect-ratio: 16 / 10;
  border-radius: 6px;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.18), rgba(148, 163, 184, 0.28), rgba(148, 163, 184, 0.18));
  background-size: 200% 100%;
  animation: progress-stripe 1.1s linear infinite;
}

.shot-error {
  margin-top: 0.45rem;
  font-size: 0.75rem;
  color: var(--color-error);
}

.production-error {
  margin: 0.5rem 0 0.75rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid color-mix(in srgb, var(--color-error) 45%, var(--color-border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-error) 10%, var(--color-bg-secondary));
}

.shot-actions {
  margin-top: 0.45rem;
  display: flex;
  justify-content: flex-end;
  gap: 0.35rem;
}

.shot-action-btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg);
  color: var(--color-text);
  border-radius: var(--radius-sm);
  height: 30px;
  padding: 0 0.65rem;
  font-size: 0.74rem;
  cursor: pointer;
}

.shot-action-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
}

.shot-action-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.shot-action-link {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.empty {
  color: var(--color-text-secondary);
  text-align: center;
  font-size: 0.86rem;
  padding: 1.2rem 0.4rem;
}

@media (max-width: 900px) {
  .problem-main {
    grid-template-columns: 76px minmax(0, 1fr) 58px;
  }

  .primary-action,
  .detail-toggle {
    grid-column: span 3;
    width: 100%;
  }

  .problem-copy p {
    white-space: normal;
  }
}
</style>
