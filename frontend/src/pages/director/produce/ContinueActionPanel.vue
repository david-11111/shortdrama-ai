<script setup lang="ts">
import { computed, inject, onUnmounted, ref } from 'vue'
import { continueProjectBrain, getProjectBrain, getProjectWorkspace, listShotRows } from '@/api/workbench'
import type { Shot } from '@/composables/useDirectorSession'
import { useWebSocket } from '@/composables/useWebSocket'
import { deriveProjectProductionState, deriveShotProductionState } from './productionState'

type QueueTone = 'danger' | 'warning' | 'active' | 'ready' | 'idle'

interface QueueRow {
  key: string
  title: string
  action: string
  tone: QueueTone
  shots: Shot[]
}

const session = inject<any>('session')
const continuing = ref(false)
const continueMessage = ref('')
const subscribedTaskIds = new Set<string>()
const { connect, on, off, subscribe, unsubscribe } = useWebSocket()

const shots = computed<Shot[]>(() => Array.isArray(session?.shots?.value) ? session.shots.value : [])
const projectBrain = computed(() => session?.projectBrain?.value || null)
const refs = computed(() => Array.isArray(session?.refImages?.value) ? session.refImages.value : [])
const locks = computed(() => session?.anchorLocks?.value || {})
const activeTaskCount = computed(() => Number(session?.activeTaskCount?.value || 0))
const shotStateRows = computed(() => shots.value.map((shot) => ({ shot, state: deriveShotProductionState(shot) })))
const projectState = computed(() => deriveProjectProductionState(shots.value))

const queues = computed<QueueRow[]>(() => [
  {
    key: 'safe_rewrite',
    title: '待安全改写',
    action: '应用安全改写 / 收紧提示词',
    tone: 'danger',
    shots: shotsByAction('needs_rewrite', 'blocked'),
  },
  {
    key: 'missing_assets',
    title: '待补资产',
    action: '补角色、场景、道具或风格参考',
    tone: 'warning',
    shots: shotsByAction('needs_assets'),
  },
  {
    key: 'keyframe',
    title: '待出关键帧',
    action: '生成或选择关键帧',
    tone: 'active',
    shots: shotsByAction('can_generate_image'),
  },
  {
    key: 'review',
    title: '待审片/重生',
    action: '复核审片结论并重生问题素材',
    tone: 'warning',
    shots: [...shotsByAction('needs_image_review', 'needs_video_review'), ...shots.value.filter((shot) => Boolean(shot.last_error))],
  },
  {
    key: 'video_edit',
    title: '待出视频/剪辑',
    action: '图生视频或送入成片台',
    tone: 'ready',
    shots: shotsByAction('can_generate_video', 'can_edit'),
  },
])

const stuckQueue = computed(() => queues.value.find((queue) => queue.shots.length > 0))
const brainActionLabel = computed(() => projectBrain.value?.next_action_label || projectBrain.value?.next_action || '继续推进')
const canContinueBrain = computed(() => Boolean(session?.projectId?.value && projectBrain.value?.can_continue && !continuing.value))
const isOpenFinalCutAction = computed(() => projectBrain.value?.next_action === 'open_final_cut')
const finalCutTarget = computed(() => session?.projectId?.value ? `/director/final-cut/${session.projectId.value}` : '/director/final-cut')

const runningShots = computed(() => shots.value.filter((shot) => isGenerating(shot.status)))
const failedShots = computed(() => shots.value.filter((shot) => shot.status === 'error' || Boolean(shot.last_error)).slice(0, 3))
const completedShots = computed(() => shots.value.filter((shot) => shot.selected_video || shot.status === 'video_done' || shot.selected_image || shot.status === 'image_done').slice(-3).reverse())

const taskProgressText = computed(() => {
  if (runningShots.value.length) return `分镜 ${formatShotList(runningShots.value)} 正在生成`
  if (activeTaskCount.value > 0) return '任务已提交，等待后台回写分镜状态'
  if (failedShots.value.length) return `最近失败：${formatShotList(failedShots.value)}`
  if (completedShots.value.length) return `最近完成：${formatShotList(completedShots.value)}`
  return '暂无后台任务'
})

const readyStats = computed(() => {
  const imageReady = shots.value.filter((shot) => Boolean(shot.selected_image)).length
  const videoReady = shots.value.filter((shot) => Boolean(shot.selected_video)).length
  const refsReady = refs.value.filter((item: any) => !item.pending && item.url).length
  const cuttable = shotStateRows.value.filter((item) => item.state.next_action === 'can_edit' || item.state.next_action === 'done').length
  return [
    { label: '关键帧', value: imageReady },
    { label: '视频', value: videoReady },
    { label: '参考资产', value: refsReady },
    { label: '可剪辑', value: cuttable },
  ]
})

const lockRows = computed(() => [
  { key: 'lock_character', label: '人物', active: Boolean(locks.value.lock_character), toggle: true },
  { key: 'lock_scene', label: '场景', active: Boolean(locks.value.lock_scene), toggle: true },
  { key: 'lock_costume', label: '服装', active: Boolean(locks.value.lock_costume), toggle: true },
  { key: 'lock_prop', label: '道具', active: Boolean(locks.value.lock_prop), toggle: true },
  { key: 'style', label: '风格', active: shots.value.some((shot) => shot.style_refs?.length), toggle: false },
])

function shotsByAction(...actions: string[]) {
  return shotStateRows.value
    .filter((item) => actions.includes(item.state.next_action))
    .map((item) => ({ ...item.shot, production_state: item.state }))
}

function isGenerating(status = '') {
  return status.includes('generating') || status.includes('running')
}

function formatShotList(items: Shot[]) {
  return items.slice(0, 3).map((shot) => `#${shot.index}`).join('、') || '-'
}

function locateShot(shot?: Shot) {
  if (!shot?.index) return
  const id = `shot-${shot.index}`
  window.location.hash = id
  requestAnimationFrame(() => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

function locateQueue(queue: QueueRow) {
  locateShot(queue.shots[0])
}

function toggleLock(row: { key: string; toggle: boolean }) {
  if (!row.toggle || !session?.anchorLocks?.value) return
  session.anchorLocks.value[row.key] = !session.anchorLocks.value[row.key]
}

function appendEvent(event: Record<string, any>) {
  session?.pushExecutionEvent?.({
    project_id: session?.projectId?.value,
    ...event,
  })
}

function updateTaskEvent(message: any) {
  const taskId = String(message?.task_id || '')
  if (!taskId || !subscribedTaskIds.has(taskId)) return

  if (message.type === 'task_update') {
    session?.upsertExecutionEvent?.(
      (event: any) => event.task_id === taskId && event.source === 'worker',
      {
        phase: 'worker_progress',
        title: `后台任务 ${message.status || 'running'}`,
        detail: message.stage_text || '后台任务正在执行',
        status: message.status === 'queued' ? 'pending' : 'running',
        progress: Number(message.progress || 0),
        tone: 'active',
        meta: { raw: message },
      },
      {
        project_id: session?.projectId?.value,
        task_id: taskId,
        source: 'worker',
        phase: 'worker_progress',
        title: '后台任务执行中',
        detail: message.stage_text || '后台任务正在执行',
        status: 'running',
        progress: Number(message.progress || 0),
        tone: 'active',
      },
    )
    return
  }

  if (message.type === 'task_complete') {
    session?.upsertExecutionEvent?.(
      (event: any) => event.task_id === taskId && event.source === 'worker',
      {
        phase: 'worker_complete',
        title: '后台任务完成',
        detail: summarizeTaskResult(message.result),
        status: 'done',
        progress: 100,
        tone: 'success',
        meta: { result: message.result },
      },
      {
        project_id: session?.projectId?.value,
        task_id: taskId,
        source: 'worker',
        phase: 'worker_complete',
        title: '后台任务完成',
        detail: summarizeTaskResult(message.result),
        status: 'done',
        progress: 100,
        tone: 'success',
      },
    )
    void refreshProjectState().then(() => {
      appendEvent({
        source: 'ledger',
        phase: 'writeback_refresh',
        title: '执行结果已回读',
        detail: '已刷新 workspace / brain / shots，下一轮大脑可接着上一次继续。',
        status: 'done',
        tone: 'success',
      })
    })
    unsubscribe([taskId])
    subscribedTaskIds.delete(taskId)
    session?.endTask?.()
    return
  }

  if (message.type === 'task_failed') {
    session?.upsertExecutionEvent?.(
      (event: any) => event.task_id === taskId && event.source === 'worker',
      {
        phase: 'worker_failed',
        title: '后台任务失败',
        detail: message.error || '任务失败',
        status: 'failed',
        tone: 'error',
        meta: { raw: message },
      },
      {
        project_id: session?.projectId?.value,
        task_id: taskId,
        source: 'worker',
        phase: 'worker_failed',
        title: '后台任务失败',
        detail: message.error || '任务失败',
        status: 'failed',
        tone: 'error',
      },
    )
    unsubscribe([taskId])
    subscribedTaskIds.delete(taskId)
    session?.endTask?.()
  }
}

function summarizeTaskResult(result: any) {
  if (!result || typeof result !== 'object') return '任务已完成，等待回写刷新。'
  const url = result.url || result.video_url || result.image_url || result.preview_url || result.final_url
  const parts = [
    result.export_kind ? `类型 ${result.export_kind}` : '',
    result.clip_count ? `片段 ${result.clip_count}` : '',
    result.duration_sec ? `时长 ${result.duration_sec}s` : '',
    url ? `产物 ${String(url).slice(0, 80)}` : '',
  ].filter(Boolean)
  return parts.length ? parts.join('；') : '任务已完成，等待回写刷新。'
}

function watchTaskIds(ids: string[]) {
  const next = ids.map((id) => String(id || '')).filter(Boolean)
  if (!next.length) return
  connect()
  subscribe(next)
  next.forEach((id) => {
    if (!subscribedTaskIds.has(id)) {
      subscribedTaskIds.add(id)
      session?.beginTask?.()
      appendEvent({
        task_id: id,
        source: 'queue',
        phase: 'task_subscribed',
        title: '已订阅后台任务',
        detail: `task_id=${id}`,
        status: 'pending',
        progress: 0,
        tone: 'info',
      })
    }
  })
}

function normalizeShotRows(rows: any[]): Shot[] {
  return rows.map((r: any) => ({
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
    prompt_revision: r.prompt_revision || undefined,
    director_preflight: r.director_preflight || undefined,
  })).map((shot: Shot) => ({ ...shot, production_state: deriveShotProductionState(shot) }))
}

async function refreshProjectState() {
  if (!session?.projectId?.value) return
  const [workspaceResp, brainResp, shotsResp] = await Promise.all([
    getProjectWorkspace(session.projectId.value),
    getProjectBrain(session.projectId.value),
    listShotRows(session.projectId.value),
  ])
  session.projectWorkspace.value = workspaceResp.data
  session.projectBrain.value = brainResp.data
  const rows = shotsResp.data?.items || shotsResp.data?.rows || shotsResp.data || []
  if (Array.isArray(rows)) session.shots.value = normalizeShotRows(rows)
}

async function continueBrain() {
  if (!session?.projectId?.value || continuing.value) return
  continuing.value = true
  continueMessage.value = ''
  const action = String(projectBrain.value?.next_action || '')
  appendEvent({
    source: 'brain',
    phase: 'continue_start',
    title: '大脑开始继续推进',
    detail: `next_action=${action || '-'}；phase=${projectBrain.value?.phase || '-'}`,
    status: 'running',
    progress: 5,
    tone: 'active',
  })
  try {
    const { data } = await continueProjectBrain(session.projectId.value, { action })
    appendEvent({
      source: 'api',
      phase: 'continue_response',
      title: data?.applied ? '大脑执行指令已返回' : '大脑未执行动作',
      detail: data?.message || `action=${data?.action || action || '-'}`,
      status: data?.applied ? 'done' : 'blocked',
      progress: data?.applied ? 35 : 100,
      tone: data?.applied ? 'success' : 'warning',
      meta: {
        action: data?.action,
        queued_count: data?.queued_count,
        child_task_ids: data?.child_task_ids,
      },
    })
    await refreshProjectState()
    appendEvent({
      source: 'ledger',
      phase: 'state_refreshed',
      title: '已刷新大脑与账本',
      detail: 'workspace / brain / shot_rows 已重新读取。',
      status: 'done',
      progress: 45,
      tone: 'success',
    })
    const writeCount = Array.isArray(data?.writes) ? data.writes.length : 0
    const shotCount = Array.isArray(data?.shot_rows) ? data.shot_rows.length : 0
    const queuedCount = Number(data?.queued_count || 0)
    const clipCount = Number(data?.clip_count || 0)
    const appliedCount = Number(data?.applied_count || 0)
    const plannedReferenceCount = Number(data?.planned_reference_count || 0)
    const boundExistingCount = Number(data?.bound_existing_count || 0)
    const reusedPlannedReferenceCount = Number(data?.reused_planned_reference_count || 0)
    continueMessage.value = data?.applied
      ? data?.action === 'plan_final_edit'
        ? `已规划成片剪辑：${clipCount} 条视频素材已写入剪辑方案。`
        : data?.action === 'plan_visual_assets'
        ? `已规划视觉资产：处理 ${appliedCount} 个动作，复用 ${boundExistingCount} 个已有资产，压缩为 ${plannedReferenceCount} 个主参考，绑定复用 ${reusedPlannedReferenceCount} 次。`
        : queuedCount
        ? `已推进：${data.action}，已派发 ${queuedCount} 个关键帧任务。`
        : `已推进：${data.action}，写入 ${writeCount} 个文件，生成 ${shotCount} 条分镜。`
      : data?.message || '当前动作暂不支持自动执行。'
    session.chatMessages.value.push({ role: 'system', content: continueMessage.value, timestamp: Date.now() })
    watchTaskIds(Array.isArray(data?.child_task_ids) ? data.child_task_ids : [])
  } catch (error: any) {
    continueMessage.value = error?.response?.data?.detail || error?.message || '继续推进失败'
    appendEvent({
      source: 'brain',
      phase: 'continue_failed',
      title: '继续推进失败',
      detail: typeof continueMessage.value === 'string' ? continueMessage.value : JSON.stringify(continueMessage.value),
      status: 'failed',
      progress: 100,
      tone: 'error',
    })
  } finally {
    continuing.value = false
  }
}

on('task_update', updateTaskEvent)
on('task_complete', updateTaskEvent)
on('task_failed', updateTaskEvent)

onUnmounted(() => {
  off('task_update', updateTaskEvent)
  off('task_complete', updateTaskEvent)
  off('task_failed', updateTaskEvent)
  const ids = Array.from(subscribedTaskIds)
  if (ids.length) unsubscribe(ids)
})
</script>

<template>
  <aside class="control-tower" aria-label="生产队列控制塔">
    <header class="tower-head">
      <p class="eyebrow">Production Tower</p>
      <h3>生产队列</h3>
      <p>{{ stuckQueue ? `当前卡在：${stuckQueue.title}` : projectState.summary }}</p>
    </header>

    <section class="continue-card">
      <span>项目大脑</span>
      <strong>{{ brainActionLabel }}</strong>
      <p>{{ projectBrain?.summary || '等待项目大脑读取当前进度。' }}</p>
      <RouterLink v-if="isOpenFinalCutAction" class="continue-link" :to="finalCutTarget">
        进入剪辑台
      </RouterLink>
      <button v-else type="button" :disabled="!canContinueBrain" @click="continueBrain">
        {{ continuing ? '推进中...' : '继续推进' }}
      </button>
      <small v-if="continueMessage">{{ continueMessage }}</small>
    </section>

    <section class="task-card">
      <div class="task-top">
        <span>后台任务</span>
        <strong>{{ activeTaskCount }}</strong>
      </div>
      <p>{{ taskProgressText }}</p>
      <div class="recent-row">
        <button v-for="shot in completedShots" :key="`done-${shot.index}`" type="button" @click="locateShot(shot)">
          完成 #{{ shot.index }}
        </button>
        <button v-for="shot in failedShots" :key="`fail-${shot.index}`" class="failed" type="button" @click="locateShot(shot)">
          失败 #{{ shot.index }}
        </button>
      </div>
    </section>

    <section class="queue-list">
      <button
        v-for="queue in queues"
        :key="queue.key"
        class="queue-row"
        :class="queue.tone"
        type="button"
        @click="locateQueue(queue)"
      >
        <div class="queue-title">
          <span>{{ queue.title }}</span>
          <strong>{{ queue.shots.length }}</strong>
        </div>
        <p>{{ queue.action }}</p>
        <div class="shot-pills">
          <span v-for="shot in queue.shots.slice(0, 3)" :key="shot.index">#{{ shot.index }}</span>
          <span v-if="!queue.shots.length">无</span>
        </div>
      </button>
    </section>

    <section class="ready-strip">
      <div v-for="item in readyStats" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </section>

    <section class="lock-box">
      <div class="lock-head">
        <span>资产锁定</span>
        <small>压缩视图</small>
      </div>
      <div class="lock-grid">
        <button
          v-for="row in lockRows"
          :key="row.key"
          class="lock-chip"
          :class="{ active: row.active, readonly: !row.toggle }"
          type="button"
          @click="toggleLock(row)"
        >
          <span>{{ row.label }}</span>
          <strong>{{ row.active ? '锁' : '开' }}</strong>
        </button>
      </div>
    </section>
  </aside>
</template>

<style scoped>
.control-tower {
  display: grid;
  gap: 0.75rem;
  padding: 0.9rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
}

.tower-head {
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 0.75rem;
}

.eyebrow {
  margin: 0 0 0.2rem;
  color: var(--color-primary);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h3 {
  margin: 0;
  font-size: 1rem;
}

.tower-head p:last-child,
.task-card p,
.queue-row p {
  margin: 0.32rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.74rem;
  line-height: 1.4;
}

.continue-card,
.task-card,
.lock-box {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  padding: 0.7rem;
}

.continue-card {
  display: grid;
  gap: 0.35rem;
  border-color: color-mix(in srgb, var(--color-primary) 42%, var(--color-border));
}

.continue-card span,
.continue-card small {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.continue-card strong {
  color: var(--color-text);
  font-size: 0.95rem;
}

.continue-card p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.74rem;
  line-height: 1.42;
}

.continue-card button,
.continue-link {
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid color-mix(in srgb, var(--color-primary) 58%, var(--color-border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-primary) 18%, var(--color-bg));
  color: var(--color-text);
  font-size: 0.82rem;
  text-decoration: none;
  cursor: pointer;
}

.continue-card button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.task-top,
.queue-title,
.lock-head {
  display: flex;
  justify-content: space-between;
  gap: 0.7rem;
  align-items: center;
}

.task-top span,
.lock-head span {
  color: var(--color-text-secondary);
  font-size: 0.74rem;
}

.task-top strong {
  color: var(--color-text);
  font-size: 1.3rem;
}

.recent-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.55rem;
}

.recent-row button {
  height: 26px;
  border: 1px solid color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-success) 8%, var(--color-bg));
  color: var(--color-success);
  font-size: 0.7rem;
  cursor: pointer;
}

.recent-row .failed {
  border-color: color-mix(in srgb, var(--color-error) 45%, var(--color-border));
  background: color-mix(in srgb, var(--color-error) 8%, var(--color-bg));
  color: var(--color-error);
}

.queue-list {
  display: grid;
  gap: 0.5rem;
}

.queue-row {
  width: 100%;
  min-height: 82px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  text-align: left;
  padding: 0.65rem;
  cursor: pointer;
}

.queue-row:hover {
  border-color: color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
  transform: translateY(-1px);
}

.queue-row.danger {
  border-color: color-mix(in srgb, var(--color-error) 42%, var(--color-border));
}

.queue-row.warning {
  border-color: color-mix(in srgb, var(--color-warning) 44%, var(--color-border));
}

.queue-row.active {
  border-color: color-mix(in srgb, var(--color-primary) 48%, var(--color-border));
}

.queue-row.ready {
  border-color: color-mix(in srgb, var(--color-success) 42%, var(--color-border));
}

.queue-title span {
  font-size: 0.82rem;
  font-weight: 700;
}

.queue-title strong {
  font-size: 1rem;
}

.shot-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
  margin-top: 0.5rem;
}

.shot-pills span {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.12rem 0.42rem;
  color: var(--color-text-secondary);
  font-size: 0.68rem;
}

.ready-strip {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.45rem;
}

.ready-strip div {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  padding: 0.5rem;
}

.ready-strip span,
.lock-head small {
  display: block;
  color: var(--color-text-secondary);
  font-size: 0.68rem;
}

.ready-strip strong {
  display: block;
  margin-top: 0.15rem;
  font-size: 0.94rem;
}

.lock-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.35rem;
  margin-top: 0.55rem;
}

.lock-chip {
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--color-text-secondary);
  padding: 0.4rem 0.2rem;
  cursor: pointer;
}

.lock-chip.active {
  border-color: color-mix(in srgb, var(--color-success) 58%, var(--color-border));
  color: var(--color-success);
}

.lock-chip.readonly {
  cursor: default;
}

.lock-chip span,
.lock-chip strong {
  display: block;
  text-align: center;
}

.lock-chip span {
  font-size: 0.68rem;
}

.lock-chip strong {
  margin-top: 0.12rem;
  font-size: 0.78rem;
}
</style>
