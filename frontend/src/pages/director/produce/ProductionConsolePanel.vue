<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { applyShotSafeRewrite, listShotPromptRevisions, listShotRows, rollbackShotSafeRewrite } from '@/api/workbench'
import type { ChatMessage, MediaCandidate, MediaReview, ProjectBrain, ProjectWorkspace, PromptRevisionPayload, RefImageItem, Shot } from '@/composables/useDirectorSession'
import { deriveShotProductionState } from './productionState'

type ConsoleKind = 'all' | 'workspace' | 'brain' | 'text' | 'refs' | 'shots' | 'reviews' | 'locks'

interface ConsoleEntry {
  id: string
  kind: Exclude<ConsoleKind, 'all'>
  time: number
  title: string
  summary: string
  detail?: string
  image?: string
  video?: string
  shot?: Shot
}

const session = inject<any>('session')
const activeKind = ref<ConsoleKind>('all')
const opened = ref<ConsoleEntry | null>(null)
const applyingRewrite = ref(false)
const rollingBackRewrite = ref(false)
const loadingRevisions = ref(false)
const applyMessage = ref('')

const messages = computed<ChatMessage[]>(() => Array.isArray(session?.chatMessages?.value) ? session.chatMessages.value : [])
const refs = computed<RefImageItem[]>(() => Array.isArray(session?.refImages?.value) ? session.refImages.value : [])
const shots = computed<Shot[]>(() => Array.isArray(session?.shots?.value) ? session.shots.value : [])
const workspace = computed<ProjectWorkspace | null>(() => session?.projectWorkspace?.value || null)
const projectBrain = computed<ProjectBrain | null>(() => session?.projectBrain?.value || null)
const locks = computed(() => session?.anchorLocks?.value || {})

const lockRows = computed(() => [
  { key: 'lock_character', label: '角色', value: Boolean(locks.value.lock_character), note: '控制人物脸、发型、身形、身份连续' },
  { key: 'lock_scene', label: '场景', value: Boolean(locks.value.lock_scene), note: '控制门店、柜台、空间关系连续' },
  { key: 'lock_costume', label: '服装', value: Boolean(locks.value.lock_costume), note: '控制服装、妆造、职业身份连续' },
  { key: 'lock_prop', label: '道具', value: Boolean(locks.value.lock_prop), note: '控制黄金、电子秤、报价单等道具连续' },
])

const entries = computed<ConsoleEntry[]>(() => {
  const rows: ConsoleEntry[] = []

  if (workspace.value) {
    const files = Array.isArray(workspace.value.files) ? workspace.value.files : []
    const readyFiles = files.filter((item) => item.exists).length
    rows.push({
      id: `workspace-${workspace.value.project_id || 'current'}`,
      kind: 'workspace',
      time: -10_000,
      title: workspace.value.ready ? '已读取主角工作区' : '主角工作区未完整',
      summary: `${workspace.value.workspace_version || '-'} · ${readyFiles}/${files.length || 0} 个项目文件就绪`,
      detail: buildWorkspaceDetail(workspace.value),
    })
  }

  if (projectBrain.value) {
    rows.push({
      id: `brain-${projectBrain.value.project_id || 'current'}-${projectBrain.value.analyzed_at || ''}`,
      kind: 'brain',
      time: -9_000,
      title: '项目理解完成',
      summary: `${projectBrain.value.phase || '-'} · ${projectBrain.value.next_action_label || projectBrain.value.next_action || '-'}`,
      detail: buildBrainDetail(projectBrain.value),
    })
  }

  messages.value.forEach((msg, index) => {
    const text = String(msg.content || '').trim()
    if (!text) return
    rows.push({
      id: `text-${msg.timestamp || index}-${index}`,
      kind: 'text',
      time: Number(msg.timestamp || index),
      title: msg.role === 'user' ? '用户输入' : msg.role === 'assistant' ? '导演回复' : '系统事件',
      summary: compact(text, 96),
      detail: text,
    })
  })

  refs.value.forEach((item, index) => {
    rows.push({
      id: `ref-${item.id || item.asset_id || item.url || index}`,
      kind: 'refs',
      time: index + 10_000,
      title: item.pending ? '参考图生成中' : '参考图入库',
      summary: `${viewLabel(item.view)} · ${item.lineage_role || 'reference'}${item.pending ? ` · ${item.progress || 0}%` : ''}`,
      detail: [
        `视图：${viewLabel(item.view)}`,
        `资产：${item.asset_id || item.id || '未记录'}`,
        `来源：${item.lineage_role || 'reference'}`,
        item.error ? `错误：${item.error}` : '',
      ].filter(Boolean).join('\n'),
      image: item.url,
    })
  })

  shots.value.forEach((shot) => {
    const preflight = shot.director_preflight
    if (preflight?.risk_count) {
      rows.push({
        id: `preflight-${shot.index}`,
        kind: 'shots',
        time: shot.index + 19_000,
        title: `审查 #${shot.index} · ${riskLabel(preflight.risk_level)}`,
        summary: preflight.risks.map((item) => item.title).join(' / '),
        detail: buildPreflightDetail(shot),
        shot,
      })
    }
    rows.push({
      id: `shot-${shot.index}`,
      kind: 'shots',
      time: shot.index + 20_000,
      title: `分镜 #${shot.index}`,
      summary: `${statusLabel(shot.status)} · ${compact(shot.prompt, 80)}`,
      detail: buildShotDetail(shot),
      image: shot.selected_image || undefined,
      shot,
    })
    reviewEntries(shot).forEach((entry, index) => {
      rows.push({
        id: `review-${shot.index}-${entry.kind}-${index}`,
        kind: 'reviews',
        time: shot.index + 21_000 + index,
        title: `审片 #${shot.index} · ${reviewLabel(entry.review.status)}`,
        summary: `${entry.kind === 'video' ? '视频' : '图片'}候选 ${entry.index + 1} · ${entry.review.score || 0} 分 · ${reviewDecision(entry.review, entry.kind)}`,
        detail: buildReviewDetail(entry.kind, entry.url, entry.review),
        image: entry.kind === 'image' ? entry.url : undefined,
        video: entry.kind === 'video' ? entry.url : undefined,
        shot,
      })
    })
  })

  lockRows.value.forEach((lock, index) => {
    rows.push({
      id: `lock-${lock.key}`,
      kind: 'locks',
      time: index + 30_000,
      title: `${lock.label}${lock.value ? '已锁定' : '可切换'}`,
      summary: lock.note,
      detail: `${lock.label}锁：${lock.value ? '开启' : '关闭'}\n${lock.note}`,
    })
  })

  return rows.sort((a, b) => a.time - b.time)
})

const filteredEntries = computed(() => {
  if (activeKind.value === 'all') return entries.value
  return entries.value.filter((item) => item.kind === activeKind.value)
})

const counters = computed(() => ({
  all: entries.value.length,
  workspace: entries.value.filter((item) => item.kind === 'workspace').length,
  brain: entries.value.filter((item) => item.kind === 'brain').length,
  text: entries.value.filter((item) => item.kind === 'text').length,
  refs: entries.value.filter((item) => item.kind === 'refs').length,
  shots: entries.value.filter((item) => item.kind === 'shots').length,
  reviews: entries.value.filter((item) => item.kind === 'reviews').length,
  locks: entries.value.filter((item) => item.kind === 'locks').length,
}))

function buildWorkspaceDetail(item: ProjectWorkspace) {
  const files = Array.isArray(item.files) ? item.files : []
  const bootstrap = item.bootstrap || {}
  return [
    `Project: ${item.project_id}`,
    `Workspace: ${item.workspace_root || '-'}`,
    `Version: ${item.workspace_version || '-'}`,
    `Ready: ${item.ready ? 'yes' : 'no'}`,
    '',
    'Files:',
    ...(files.length ? files.map((file) => `- ${file.exists ? 'ok' : 'missing'} ${file.path} (${file.size || 0} bytes)`) : ['- no manifest']),
    '',
    'PROJECT.md:',
    compactBlock(bootstrap['PROJECT.md'] || '', 1600) || '-',
    '',
    'memory/decisions.md:',
    compactBlock(bootstrap['memory/decisions.md'] || '', 800) || '-',
    '',
    'memory/failures.md:',
    compactBlock(bootstrap['memory/failures.md'] || '', 800) || '-',
    '',
    'memory/constraints.md:',
    compactBlock(bootstrap['memory/constraints.md'] || '', 1000) || '-',
  ].join('\n')
}

function buildBrainDetail(item: ProjectBrain) {
  const missing = Array.isArray(item.missing) ? item.missing : []
  const risks = Array.isArray(item.risks) ? item.risks : []
  const files = Array.isArray(item.read_files) ? item.read_files : []
  return [
    `Project: ${item.project_id}`,
    `Brain: ${item.brain_version || '-'}`,
    `Analyzed: ${item.analyzed_at || '-'}`,
    `Phase: ${item.phase || '-'}`,
    `Next: ${item.next_action_label || item.next_action || '-'}`,
    `Can continue: ${item.can_continue ? 'yes' : 'no'}`,
    '',
    'Summary:',
    item.summary || '-',
    '',
    'Missing:',
    ...(missing.length ? missing.map((row) => `- ${row.code}: ${row.label}`) : ['- none']),
    '',
    'Risks:',
    ...(risks.length ? risks.map((row) => `- ${row.severity} ${row.code}: ${row.reason || row.title}`) : ['- none']),
    '',
    'Read files:',
    ...(files.length ? files.map((file) => `- ${file.exists ? 'ok' : 'missing'} ${file.path} (${file.size || 0} bytes)`) : ['- no manifest']),
    '',
    'Signals:',
    JSON.stringify(item.signals || {}, null, 2),
  ].join('\n')
}

function compactBlock(text: string, limit: number) {
  const clean = String(text || '').trim()
  if (clean.length <= limit) return clean
  return `${clean.slice(0, limit)}\n...`
}

function latestPromptRevision(shot?: Shot | null) {
  const payload = shot?.prompt_revision
  if (payload?.latest && !payload.latest.rolled_back_at) return payload.latest
  const items = Array.isArray(payload?.items) ? payload.items : []
  return items.find((item) => !item.rolled_back_at) || null
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

function revisionSourceLabel(source = '') {
  const map: Record<string, string> = {
    director_preflight: 'director_preflight',
  }
  return map[source] || source || 'unknown'
}

function formatTime(value = '') {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function buildRevisionDetail(payload?: PromptRevisionPayload) {
  const items = Array.isArray(payload?.items) ? payload.items : []
  if (!items.length) return 'No prompt rewrite revisions.'
  return items.map((item, index) => [
    `Revision ${index + 1}: ${item.revision_id || '-'}`,
    `Source: ${revisionSourceLabel(item.source)}`,
    `Created: ${formatTime(item.created_at)}`,
    `Applied: ${formatTime(item.applied_at || item.created_at)}`,
    item.rolled_back_at ? `Rolled back: ${formatTime(item.rolled_back_at)}` : 'Status: active',
    '',
    'Original prompt:',
    item.original_prompt || '-',
    '',
    'Rewritten prompt:',
    item.rewritten_prompt || '-',
  ].join('\n')).join('\n\n---\n\n')
}

function updateShotInSession(idx: number, patch: Partial<Shot>) {
  session.shots.value = (session.shots.value || []).map((item: Shot) => {
    if (Number(item.index) !== Number(idx)) return item
    return { ...item, ...patch }
  })
}

function compact(text: string, limit: number) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  if (clean.length <= limit) return clean
  return `${clean.slice(0, limit - 1)}...`
}

function viewLabel(view = '') {
  if (view.startsWith('shot_')) return `分镜 #${view.slice(5)}`
  const map: Record<string, string> = {
    front: '正脸',
    side: '侧脸',
    expression_smile: '微笑表情',
    full_body: '全身',
  }
  return map[view] || view || '参考图'
}

function statusLabel(status = '') {
  const map: Record<string, string> = {
    draft: '草稿',
    ready: '就绪',
    generating_image: '出图中',
    image_done: '图片完成',
    generating_video: '视频中',
    video_done: '视频完成',
    error: '失败',
  }
  return map[status] || status || '未开始'
}

function mediaUrl(item: any): string {
  if (typeof item === 'string') return item.trim()
  if (!item || typeof item !== 'object') return ''
  return String(item.url || item.video_url || item.image_url || '').trim()
}

function normalizeCandidate(item: string | MediaCandidate): MediaCandidate | null {
  const url = mediaUrl(item)
  if (!url) return null
  return typeof item === 'string' ? { url } : { ...item, url }
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

function reviewEntries(shot: Shot): Array<{ kind: 'image' | 'video'; index: number; url: string; review: MediaReview }> {
  const rows: Array<{ kind: 'image' | 'video'; index: number; url: string; review: MediaReview }> = []
  ;(shot.image_candidates || []).forEach((item, index) => {
    const candidate = normalizeCandidate(item)
    const review = reviewOf(candidate)
    if (candidate?.url && review) rows.push({ kind: 'image', index, url: candidate.url, review })
  })
  ;(shot.video_variants || []).forEach((item, index) => {
    const candidate = normalizeCandidate(item)
    const review = reviewOf(candidate)
    if (candidate?.url && review) rows.push({ kind: 'video', index, url: candidate.url, review })
  })
  return rows
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

function reviewDecision(review: MediaReview, kind: 'image' | 'video') {
  if (review.status === 'usable') return kind === 'image' ? '可继续生成视频' : '可进入成片链路'
  if (review.status === 'cuttable') return '可剪辑，建议进入成片台精修'
  if (review.status === 'needs_review') return '人工确认后继续'
  if (review.status === 'regenerate') return kind === 'image' ? '建议重生关键帧' : '建议重生视频'
  return '等待制片判断'
}

function buildReviewDetail(kind: 'image' | 'video', url: string, review: MediaReview) {
  return [
    `类型：${kind === 'video' ? '视频' : '图片'}`,
    `结论：${reviewLabel(review.status)}`,
    `评分：${review.score || 0}`,
    `决策：${reviewDecision(review, kind)}`,
    `素材：${url}`,
    '',
    '审片备注：',
    ...(review.notes?.length ? review.notes.map((item, index) => `${index + 1}. ${item}`) : ['无']),
    '',
    '建议动作：',
    ...(review.actions?.length ? review.actions.map((item, index) => `${index + 1}. ${item}`) : ['无']),
  ].join('\n')
}

function buildShotDetail(shot: Shot) {
  const revision = latestPromptRevision(shot)
  const production = shot.production_state || deriveShotProductionState(shot)
  const refsLine = [
    ['角色', shot.character_refs],
    ['场景', shot.scene_refs],
    ['道具', shot.prop_refs],
    ['服装', shot.costume_refs],
    ['风格', shot.style_refs],
  ]
    .map(([label, value]) => `${label}：${Array.isArray(value) && value.length ? value.length : 0}`)
    .join(' / ')
  return [
    `状态：${statusLabel(shot.status)}`,
    shot.director_preflight ? `导演审查：${riskLabel(shot.director_preflight.risk_level)}，${shot.director_preflight.risk_count} 个风险` : '',
    `时长：${shot.duration || 0}s`,
    `资产绑定：${refsLine}`,
    shot.last_error ? `错误：${shot.last_error}` : '',
    '',
    `Production state: ${production.next_action} / ${production.phase}`,
    `Next reason: ${production.reason}`,
    '',
    shot.prompt,
    revision ? ['', 'Rewrite version detail:', buildRevisionDetail(shot.prompt_revision)].join('\n') : '',
  ].filter((line) => line !== '').join('\n')
}

function buildPreflightDetail(shot: Shot) {
  const preflight = shot.director_preflight
  if (!preflight) return ''
  const risks = preflight.risks.map((item, index) => {
    return `${index + 1}. ${item.title}\n   ${item.reason}`
  }).join('\n')
  const suggestions = preflight.suggestions.map((item, index) => `${index + 1}. ${item}`).join('\n')
  return [
    `分镜 #${shot.index}`,
    `审查结果：${riskLabel(preflight.risk_level)}`,
    `可生成图片：${preflight.can_generate_image ? '是' : '否'}`,
    `可生成视频：${preflight.can_generate_video ? '是' : '否'}`,
    `缺失资产：${preflight.missing_refs.length ? preflight.missing_refs.join(', ') : '无'}`,
    '',
    '风险：',
    risks || '无',
    '',
    '建议：',
    suggestions || '无',
    '',
    '安全改写：',
    preflight.safe_prompt || shot.prompt,
    latestPromptRevision(shot) ? ['', 'Rewrite version detail:', buildRevisionDetail(shot.prompt_revision)].join('\n') : '',
  ].join('\n')
}

function riskLabel(level = '') {
  const map: Record<string, string> = {
    ready: '可生成',
    warning: '需补强',
    blocked: '高风险',
  }
  return map[level] || level || '待审查'
}

function setKind(kind: ConsoleKind) {
  activeKind.value = kind
}

function openEntry(entry: ConsoleEntry) {
  opened.value = entry
  applyMessage.value = ''
}

function closeEntry() {
  opened.value = null
}

function toggleLock(key: string) {
  if (!session?.anchorLocks?.value) return
  session.anchorLocks.value[key] = !session.anchorLocks.value[key]
}

const canApplyRewrite = computed(() => {
  const shot = opened.value?.shot
  const safePrompt = String(shot?.director_preflight?.safe_prompt || '').trim()
  return Boolean(session?.projectId?.value && shot?.index && safePrompt && safePrompt !== String(shot.prompt || '').trim())
})

const canViewRevisions = computed(() => Boolean(opened.value?.shot?.index && session?.projectId?.value))

const canRollbackRewrite = computed(() => {
  const shot = opened.value?.shot
  return Boolean(shot?.index && latestPromptRevision(shot))
})

async function applySafeRewrite() {
  const shot = opened.value?.shot
  if (!session?.projectId?.value || !shot?.index) return
  applyingRewrite.value = true
  applyMessage.value = ''
  try {
    const { data } = await applyShotSafeRewrite(session.projectId.value, Number(shot.index))
    if (data?.prompt) {
      updateShotInSession(Number(shot.index), {
        prompt: data.prompt,
        director_preflight: data.director_preflight || undefined,
        prompt_revision: normalizePromptRevisionPayload({ latest: data.prompt_revision, items: data.prompt_revision ? [data.prompt_revision] : [] }),
      })
    }
    await reloadShots()
    refreshOpenedShot(Number(shot.index))
    applyMessage.value = '已应用安全改写，并重新刷新分镜审查。'
  } catch (error: any) {
    applyMessage.value = error?.response?.data?.detail || error?.message || '应用失败'
  } finally {
    applyingRewrite.value = false
  }
}

async function viewPromptRevisions() {
  const shot = opened.value?.shot
  if (!session?.projectId?.value || !shot?.index) return
  loadingRevisions.value = true
  applyMessage.value = ''
  try {
    const { data } = await listShotPromptRevisions(session.projectId.value, Number(shot.index))
    const promptRevision = normalizePromptRevisionPayload(data)
    updateShotInSession(Number(shot.index), { prompt_revision: promptRevision })
    if (!opened.value) return
    opened.value = {
      ...opened.value,
      shot: { ...shot, prompt_revision: promptRevision },
      detail: buildRevisionDetail(promptRevision),
    }
  } catch (error: any) {
    applyMessage.value = error?.response?.data?.detail || error?.message || 'Failed to load revisions'
  } finally {
    loadingRevisions.value = false
  }
}

async function rollbackSafeRewrite() {
  const shot = opened.value?.shot
  const revision = latestPromptRevision(shot)
  if (!session?.projectId?.value || !shot?.index || !revision) return
  rollingBackRewrite.value = true
  applyMessage.value = ''
  try {
    await rollbackShotSafeRewrite(session.projectId.value, Number(shot.index), { revision_id: revision.revision_id })
    await reloadShots()
    refreshOpenedShot(Number(shot.index))
    applyMessage.value = 'Safe rewrite rolled back and preflight refreshed.'
  } catch (error: any) {
    applyMessage.value = error?.response?.data?.detail?.message || error?.response?.data?.detail || error?.message || 'Rollback failed'
  } finally {
    rollingBackRewrite.value = false
  }
}

function refreshOpenedShot(idx: number) {
  if (!opened.value?.shot) return
  const fresh = (session.shots.value || []).find((item: Shot) => Number(item.index) === Number(idx))
  if (!fresh) return
  opened.value = {
    ...opened.value,
    shot: fresh,
    detail: opened.value.id.startsWith('preflight-') ? buildPreflightDetail(fresh) : buildShotDetail(fresh),
  }
}

async function reloadShots() {
  if (!session?.projectId?.value) return
  const { data } = await listShotRows(session.projectId.value)
  const rows = data?.items || data?.rows || data || []
  if (!Array.isArray(rows)) return
  session.shots.value = rows.map((r: any) => ({
    index: Number(r.shot_index || r.index || 0),
    prompt: r.prompt || '',
    duration: Number(r.duration || 5),
    status: r.status || 'draft',
    image_candidates: r.image_candidates || [],
    video_variants: r.video_variants || [],
    selected_image: r.selected_image || null,
    selected_video: r.selected_video || null,
    character_refs: r.character_refs_json || r.character_refs || [],
    scene_refs: r.scene_refs_json || r.scene_refs || [],
    prop_refs: r.prop_refs_json || r.prop_refs || [],
    costume_refs: r.costume_refs_json || r.costume_refs || [],
    style_refs: r.style_refs_json || r.style_refs || [],
    last_error: r.last_error || '',
    prompt_revision: r.prompt_revision ? normalizePromptRevisionPayload(r.prompt_revision) : undefined,
    director_preflight: r.director_preflight || undefined,
  })).map((shot: Shot) => ({ ...shot, production_state: deriveShotProductionState(shot) }))
}
</script>

<template>
  <section class="console-panel">
    <div class="console-head">
      <div>
        <p class="eyebrow">Production CLI</p>
        <h3>制片流式终端</h3>
      </div>
      <div class="console-tabs" role="tablist" aria-label="制片流类型">
        <button :class="{ active: activeKind === 'all' }" type="button" @click="setKind('all')">全部 {{ counters.all }}</button>
        <button :class="{ active: activeKind === 'workspace' }" type="button" @click="setKind('workspace')">工作区 {{ counters.workspace }}</button>
        <button :class="{ active: activeKind === 'brain' }" type="button" @click="setKind('brain')">大脑 {{ counters.brain }}</button>
        <button :class="{ active: activeKind === 'text' }" type="button" @click="setKind('text')">文字 {{ counters.text }}</button>
        <button :class="{ active: activeKind === 'refs' }" type="button" @click="setKind('refs')">参考图 {{ counters.refs }}</button>
        <button :class="{ active: activeKind === 'shots' }" type="button" @click="setKind('shots')">分镜 {{ counters.shots }}</button>
        <button :class="{ active: activeKind === 'reviews' }" type="button" @click="setKind('reviews')">审片员 {{ counters.reviews }}</button>
        <button :class="{ active: activeKind === 'locks' }" type="button" @click="setKind('locks')">锁定 {{ counters.locks }}</button>
      </div>
    </div>

    <div class="console-body">
      <div v-if="!filteredEntries.length" class="console-empty">
        等待项目事件。输入需求后，这里会持续出现文字流、参考图流、分镜流和锁定流。
      </div>
      <button
        v-for="entry in filteredEntries"
        :key="entry.id"
        class="console-line"
        :class="entry.kind"
        type="button"
        @click="openEntry(entry)"
      >
        <span class="prompt-mark">&gt;</span>
        <span class="kind">{{ entry.kind }}</span>
        <strong>{{ entry.title }}</strong>
        <span>{{ entry.summary }}</span>
        <img v-if="entry.image" :src="entry.image" alt="" />
      </button>
    </div>

    <div class="lock-strip">
      <button
        v-for="lock in lockRows"
        :key="lock.key"
        class="lock-chip"
        :class="{ active: lock.value }"
        type="button"
        @click="toggleLock(lock.key)"
      >
        <span>{{ lock.label }}</span>
        <strong>{{ lock.value ? '锁定' : '切换' }}</strong>
      </button>
    </div>

    <div v-if="opened" class="viewer-backdrop" @click.self="closeEntry">
      <article class="viewer">
        <header>
          <div>
            <p class="eyebrow">{{ opened.kind }}</p>
            <h3>{{ opened.title }}</h3>
          </div>
          <div class="viewer-actions">
            <button v-if="canApplyRewrite" type="button" :disabled="applyingRewrite" @click="applySafeRewrite">
              {{ applyingRewrite ? '应用中...' : '应用安全改写' }}
            </button>
            <button v-if="canViewRevisions" type="button" :disabled="loadingRevisions" @click="viewPromptRevisions">
              {{ loadingRevisions ? 'Loading...' : '查看版本' }}
            </button>
            <button v-if="canRollbackRewrite" type="button" :disabled="rollingBackRewrite" @click="rollbackSafeRewrite">
              {{ rollingBackRewrite ? 'Rolling back...' : '回滚' }}
            </button>
            <button type="button" @click="closeEntry">关闭</button>
          </div>
        </header>
        <img v-if="opened.image" class="viewer-image" :src="opened.image" :alt="opened.title" />
        <video v-if="opened.video" class="viewer-video" :src="opened.video" controls preload="metadata"></video>
        <p v-if="applyMessage" class="apply-message">{{ applyMessage }}</p>
        <pre>{{ opened.detail || opened.summary }}</pre>
      </article>
    </div>
  </section>
</template>

<style scoped>
.console-panel {
  margin-bottom: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: #07100d;
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.console-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  padding: 0.85rem 1rem;
  border-bottom: 1px solid color-mix(in srgb, var(--color-border) 72%, #22c55e);
}

.eyebrow {
  margin: 0 0 0.2rem;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6ee7b7;
}

.console-head h3 {
  margin: 0;
  color: #ecfdf5;
  font-size: 1rem;
}

.console-tabs {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.console-tabs button,
.viewer header button {
  border: 1px solid rgba(110, 231, 183, 0.28);
  background: rgba(6, 78, 59, 0.34);
  color: #d1fae5;
  border-radius: var(--radius-sm);
  height: 30px;
  padding: 0 0.55rem;
  cursor: pointer;
}

.viewer-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.viewer-actions button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.apply-message {
  margin: 0.75rem 1rem 0;
  padding: 0.55rem 0.65rem;
  border: 1px solid rgba(110, 231, 183, 0.28);
  border-radius: var(--radius-sm);
  color: #d1fae5;
  background: rgba(6, 78, 59, 0.28);
  font-size: 0.8rem;
}

.console-tabs button.active {
  border-color: #6ee7b7;
  background: rgba(16, 185, 129, 0.22);
}

.console-body {
  max-height: 360px;
  overflow: auto;
  padding: 0.5rem;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.console-empty {
  padding: 1rem;
  color: #a7f3d0;
  font-size: 0.82rem;
}

.console-line {
  width: 100%;
  min-height: 42px;
  display: grid;
  grid-template-columns: 18px 56px minmax(80px, 120px) 1fr 38px;
  gap: 0.5rem;
  align-items: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: #d1fae5;
  text-align: left;
  padding: 0.35rem 0.45rem;
  cursor: pointer;
}

.console-line:hover {
  background: rgba(16, 185, 129, 0.12);
}

.prompt-mark {
  color: #34d399;
}

.kind {
  color: #a7f3d0;
  font-size: 0.72rem;
  text-transform: uppercase;
}

.console-line strong {
  color: #ecfdf5;
  font-size: 0.78rem;
}

.console-line span:last-of-type {
  color: #c7f9df;
  font-size: 0.76rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.console-line img {
  width: 34px;
  height: 34px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(110, 231, 183, 0.3);
}

.lock-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem;
  padding: 0.75rem 1rem 1rem;
}

.lock-chip {
  min-height: 46px;
  border: 1px solid rgba(110, 231, 183, 0.24);
  border-radius: var(--radius-sm);
  background: rgba(15, 23, 42, 0.75);
  color: #d1fae5;
  cursor: pointer;
}

.lock-chip.active {
  border-color: #6ee7b7;
  background: rgba(5, 150, 105, 0.24);
}

.lock-chip span,
.lock-chip strong {
  display: block;
}

.lock-chip span {
  font-size: 0.72rem;
  color: #a7f3d0;
}

.lock-chip strong {
  margin-top: 0.15rem;
  font-size: 0.84rem;
}

.viewer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(2, 6, 23, 0.72);
  display: grid;
  place-items: center;
  padding: 1rem;
}

.viewer {
  width: min(760px, 100%);
  max-height: min(760px, 92vh);
  overflow: auto;
  border: 1px solid rgba(110, 231, 183, 0.32);
  border-radius: var(--radius-lg);
  background: #07100d;
  color: #d1fae5;
  box-shadow: var(--shadow-card);
}

.viewer header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  border-bottom: 1px solid rgba(110, 231, 183, 0.2);
}

.viewer h3 {
  margin: 0;
  color: #ecfdf5;
}

.viewer-image {
  display: block;
  width: min(100%, 520px);
  max-height: 420px;
  object-fit: contain;
  margin: 1rem auto 0;
  border-radius: var(--radius-md);
}

.viewer-video {
  display: block;
  width: min(100%, 620px);
  max-height: 420px;
  object-fit: contain;
  margin: 1rem auto 0;
  border-radius: var(--radius-md);
  background: #000;
}

.viewer pre {
  margin: 0;
  padding: 1rem;
  color: #d1fae5;
  white-space: pre-wrap;
  line-height: 1.55;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.82rem;
}

@media (max-width: 900px) {
  .console-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .console-line {
    grid-template-columns: 18px 48px 1fr 34px;
  }

  .console-line strong {
    display: none;
  }

  .lock-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
