<template>
  <section class="timeline-shell">
    <header class="timeline-header">
      <div>
        <p class="eyebrow">Agent 工作流</p>
        <h1>{{ goal || 'Agent Run' }}</h1>
        <p>{{ runScopeText }} · {{ statusText }}</p>
      </div>
      <button type="button" @click="$emit('refresh')">刷新</button>
    </header>

    <div ref="scroller" class="timeline">
      <section v-if="currentStage" class="workflow-summary" :class="{ blocked: gateBlocked }">
        <div>
          <span>当前阶段</span>
          <strong>{{ currentStageTitle }}</strong>
        </div>
        <p v-if="stageReason">{{ stageReason }}</p>
      </section>

      <div v-if="visibleEvents.length" class="stream">
        <EventItem v-for="event in visibleEvents" :key="event.id" :event="event" />
        <div v-if="showTypingRow" class="typing-row">
          <span class="cursor"></span>
          <strong>{{ activeLane }} 正在执行</strong>
          <em>{{ activeHint }}</em>
        </div>
      </div>
      <div v-else class="empty">
        <strong>等待服务端事件</strong>
        <span>如果这里一直为空，需要检查 SSE 连接或后端事件写入。</span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { AgentEvent, AgentRunSnapshot, AgentRunSnapshotStreamItem } from '@/api/director'
import EventItem from './EventItem.vue'

export type TimelineEvent = (Partial<AgentRunSnapshotStreamItem> & Partial<AgentEvent>) & {
  id: string
  text?: string
  level?: string
  time?: string | null
  title?: string
  detail?: string
  created_at?: string
  node_id?: string
  meta?: Record<string, unknown>
  data?: Record<string, unknown>
  visibility?: string
  event_kind?: string
  summary?: string
  reason?: string
}

const props = defineProps<{
  events: TimelineEvent[]
  goal: string
  status: string
  snapshot: AgentRunSnapshot | null
}>()

defineEmits<{ refresh: [] }>()

const scroller = ref<HTMLElement | null>(null)
const terminalStatuses = new Set(['completed', 'done', 'failed', 'blocked', 'cancelled', 'answered'])
const runningStatuses = new Set(['created', 'queued', 'running', 'dispatching', 'verifying', 'writing_back', 'provider_waiting'])

const currentPhase = computed(() => props.snapshot?.run.current_phase || '')
const currentStage = computed(() => {
  const flow = props.snapshot?.flow || []
  return flow.find((stage) => ['running', 'blocked', 'pending'].includes(stage.status)) || flow[flow.length - 1] || null
})
const providerWaiting = computed(() => props.status === 'provider_waiting' || props.snapshot?.run.final_decision === 'provider_waiting')
const gateBlocked = computed(() => !providerWaiting.value && (currentStage.value?.gate?.allowed === false || currentStage.value?.status === 'blocked' || props.status === 'blocked'))
const currentStageTitle = computed(() => stageLabel(String(currentStage.value?.title || currentPhase.value || '')))
const stageReason = computed(() => {
  const reason = currentStage.value?.gate?.reason || String((currentStage.value as any)?.summary || '')
  return isEvidenceText(reason) ? '' : stageLabel(reason)
})
const visibleEvents = computed(() => buildMainEvents(props.events))
const latestEvent = computed(() => visibleEvents.value[visibleEvents.value.length - 1] || null)
const runScopeText = computed(() => {
  const project = props.snapshot?.project?.name || props.snapshot?.run.project_id || ''
  return project ? `项目：${project}` : `${visibleEvents.value.length} 条主线事件`
})

const eventStatus = computed(() => {
  const event = latestEvent.value
  if (!event) return ''
  if (event.event_type === 'error' || event.status === 'failed') return 'failed'
  if (event.event_type === 'risk' || event.status === 'blocked') return 'blocked'
  return String(event.status || '')
})

const showTypingRow = computed(() => runningStatuses.has(props.status) && !terminalStatuses.has(eventStatus.value))

const statusText = computed(() => {
  const labels: Record<string, string> = {
    completed: '已完成，可继续追问',
    done: '已完成',
    failed: '失败',
    blocked: '阻断',
    cancelled: '已取消',
    deferred: '已暂存',
    answered: '已答复',
    running: '运行中',
    dispatching: '派发中',
    provider_waiting: '等待 provider 恢复',
    queued: '排队中',
    created: '已创建',
    loading: '加载中',
  }
  return labels[props.status] || props.status || '加载中'
})

const activeHint = computed(() => latestEvent.value?.title || latestEvent.value?.event_type || '等待下一条事件')
const activeLane = computed(() => {
  const last = latestEvent.value
  if (!last) return 'Agent'
  const actor = String(last.actor || '').toLowerCase()
  if (actor === 'deepseek') return 'DeepSeek'
  if (actor === 'executor') return '执行器'
  if (actor === 'seedream') return 'Seedream'
  if (actor === 'joy-echo' || actor === 'joy_echo' || actor === 'joyai-echo' || actor === 'joyai_echo') return 'Joy-Echo'
  if (actor === 'ltx2.3' || actor === 'ltx') return 'LTX 2.3'
  if (actor === 'seedance') return 'Seedance'
  if (actor === 'state_machine') return '状态机'
  return 'Agent'
})

watch(
  () => visibleEvents.value.length,
  async () => {
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  },
)

function buildMainEvents(events: TimelineEvent[]) {
  const rows: TimelineEvent[] = []
  const selectedImageRows: TimelineEvent[] = []
  const selectedVideoRows: TimelineEvent[] = []
  const seenKeys = new Set<string>()
  const latestHumanTime = Math.max(
    0,
    ...events
      .filter((event) => String(event.event_type || '') === 'human_input' || String(event.actor || '').toLowerCase() === 'user')
      .map((event) => eventTime(event)),
  )

  for (const event of events) {
    if (isSelectedImageWriteback(event)) {
      if (!latestHumanTime || eventTime(event) >= latestHumanTime) selectedImageRows.push(event)
      continue
    }
    if (isSelectedVideoWriteback(event)) {
      if (!latestHumanTime || eventTime(event) >= latestHumanTime) selectedVideoRows.push(event)
      continue
    }
    const normalized = normalizeMainEvent(event)
    if (!normalized) continue
    const key = mainEventKey(normalized)
    if (seenKeys.has(key)) continue
    seenKeys.add(key)
    rows.push(normalized)
  }

  if (selectedImageRows.length) rows.push(writebackSummary(selectedImageRows, 'image'))
  if (selectedVideoRows.length) rows.push(writebackSummary(selectedVideoRows, 'video'))

  return rows.sort(compareEvents)
}

function normalizeMainEvent(event: TimelineEvent): TimelineEvent | null {
  const type = String(event.event_type || '')
  const kind = String(event.event_kind || '')
  const phase = String(event.phase || event.node_id || '')
  const actor = String(event.actor || event.source || '')
  const title = clean(event.title || event.text || '')
  const detail = clean(event.detail || '')
  const summary = clean(event.summary || metaValue(event, 'summary') || metaValue(event, 'message') || '')
  const reason = clean(event.reason || metaValue(event, 'reason') || '')
  const text = eventSearchText(event)

  if (isProviderWaitingEvent(event)) {
    return publicEvent(event, {
      actor: actor || 'ltx2.3',
      event_type: 'progress',
      title: 'LTX 2.3 暂时繁忙',
      detail: providerWaitingDetail(summary || detail || reason || title),
      status: 'provider_waiting',
    })
  }

  if (type === 'human_input') {
    return publicEvent(event, {
      actor: 'user',
      event_type: 'human_input',
      title: '你发出指令',
      detail: readableDetail(detail || summary),
    })
  }

  if (phase === 'human_instruction') {
    const instruction = readableDetail(detail)
    return publicEvent(event, {
      actor: 'user',
      event_type: 'human_input',
      title: '你发出指令',
      detail: instruction || readableDetail(summary),
    })
  }

  if (type === 'error' || type === 'risk' || String(event.status || '') === 'blocked' || String(event.status || '') === 'failed') {
    return publicEvent(event, {
      actor: actor || 'executor',
      title: type === 'risk' || event.status === 'blocked' ? '执行被状态机阻断' : '执行遇到错误',
      detail: readableDetail(summary || detail || reason || title),
    })
  }

  if (phase === 'human_response' || containsAny(text, ['human_response', 'deepseek 先答复人工输入'])) {
    return publicEvent(event, {
      actor: 'deepseek',
      event_type: 'tool_result',
      title: 'DeepSeek 回复',
      detail: readableDetail(summary || detail),
    })
  }

  if (phase === 'llm_planner') {
    return publicEvent(event, {
      actor: 'deepseek',
      event_type: type || 'decision',
      title: 'DeepSeek 中控判断',
      detail: readableDetail(summary || detail || reason || metaValue(event, 'reply')),
    })
  }

  if (containsAny(text, ['create agent run', '创建 agent run'])) {
    return publicEvent(event, {
      actor: 'deepseek',
      title: '创建 Agent Run',
      detail: '',
    })
  }

  if (phase === 'dispatch_instruction' || containsAny(text, ['dispatch_instruction', '发布执行指令'])) {
    return publicEvent(event, {
      actor: 'deepseek',
      title: '发布执行指令 / 下一步判断',
      detail: productionPlanDetail(summary || detail || reason),
    })
  }

  if (phase === 'executor_dispatch' || (kind === 'dispatch' && actor.toLowerCase() === 'executor')) {
    return publicEvent(event, {
      actor: 'executor',
      title: dispatchTitle(summary || detail),
      detail: dispatchDetail(summary || detail || reason),
    })
  }

  if (isTaskDispatch(event, 'keyframe')) {
    return publicEvent(event, {
      actor: 'executor',
      title: '已派发关键帧生成',
      detail: dispatchDetail(summary || detail),
    })
  }

  if (isTaskDispatch(event, 'video')) {
    return publicEvent(event, {
      actor: 'executor',
      title: '已派发视频生成',
      detail: dispatchDetail(summary || detail),
    })
  }

  if (kind === 'recovery') {
    return publicEvent(event, {
      actor: 'executor',
      title: '后续动作已暂存',
      detail: readableDetail(summary || detail || reason),
    })
  }

  return publicEvent(event, {
    actor: publicActor(event, actor, phase),
    event_type: type || kind || 'trace',
    title: title && !isEvidenceText(title) ? title : stageLabel(phase || type || kind),
    detail: readableDetail(summary || detail || reason || metaValue(event, 'output') || metaValue(event, 'decision')),
  })
}

function publicEvent(event: TimelineEvent, patch: Partial<TimelineEvent>): TimelineEvent {
  return {
    ...event,
    ...patch,
    id: String(event.id),
    meta: {
      raw_event: event,
      source_event_id: event.id,
    },
  }
}

function writebackSummary(rows: TimelineEvent[], kind: 'image' | 'video'): TimelineEvent {
  const latest = rows[rows.length - 1]
  const shotIndexes = Array.from(new Set(rows.map((row) => extractShotIndex(row)).filter(Boolean))).join('、')
  const isImage = kind === 'image'
  return publicEvent(latest, {
    id: `main-${kind}-writeback-${rows.length}-${latest.id}`,
    actor: isImage ? 'seedream' : 'ltx2.3',
    event_type: 'writeback_summary',
    title: isImage ? '关键帧已写回' : '视频片段已写回',
    detail: shotIndexes
      ? `已完成 ${rows.length} 个写回，镜头：${shotIndexes}。成果区可展开查看。`
      : `已完成 ${rows.length} 个写回，成果区可展开查看。`,
  })
}

function mainEventKey(event: TimelineEvent) {
  if (event.event_type === 'human_input') return `human:${event.detail || event.summary || event.title}`
  return `${event.actor}:${event.event_type}:${event.phase}:${event.title}:${event.detail}`
}

function isTaskDispatch(event: TimelineEvent, target: 'keyframe' | 'video') {
  const text = eventSearchText(event)
  if (target === 'keyframe') {
    return containsAny(text, ['keyframe generation tasks dispatching', '派发 keyframe 任务', '派发关键帧任务', 'generate_keyframes'])
  }
  return containsAny(text, ['video generation tasks dispatching', '派发 video 任务', '派发视频任务', 'generate_videos'])
}

function isSelectedImageWriteback(event: TimelineEvent) {
  const text = eventSearchText(event)
  return containsAny(text, ['selected_image', 'writeback_selected_image', '写回分镜'])
}

function isSelectedVideoWriteback(event: TimelineEvent) {
  const text = eventSearchText(event)
  return containsAny(text, ['selected_video', 'writeback_selected_video'])
}

function dispatchTitle(value: string) {
  const text = value.toLowerCase()
  if (containsAny(text, ['keyframe', '关键帧', '出图', 'seedream'])) return '已派发关键帧生成'
  if (containsAny(text, ['final_edit', 'plan_final_edit', '剪辑', '成片', '导出', 'export'])) return '已派发剪辑成片'
  if (containsAny(text, ['video', '视频', 'ltx', 'seedance', 'kling'])) return '已派发视频生成'
  if (containsAny(text, ['diagnostic', '诊断'])) return '执行诊断建议'
  return '已派发生产任务'
}

function isProviderWaitingEvent(event: TimelineEvent) {
  const text = eventSearchText(event)
  return containsAny(text, ['provider_waiting', 'provider deferred', 'saturated', 'backpressure', 'too many requests', '429', 'rate limit'])
}

function providerWaitingDetail(value: string) {
  const text = String(value || '')
  const shot = text.match(/shot[_\s-]?index[=:]\s*(\d+)/i)
  if (shot?.[1]) return `第 ${shot[1]} 镜视频等待 provider 恢复后重试。`
  return '视频 provider 暂时繁忙，已进入等待恢复状态；不会把它当作最终失败。'
}

function dispatchDetail(value: string) {
  const text = String(value || '')
  const queued = text.match(/\bqueued=(\d+)/i) || text.match(/queued\s+(\d+)/i)
  const credits = text.match(/\bcredits=(\d+)/i)
  if (queued?.[1] && credits?.[1]) return `已派发 ${queued[1]} 个任务，预计消耗 ${credits[1]} 积分。`
  if (queued?.[1]) return `已派发 ${queued[1]} 个任务。`
  return readableDetail(text)
}

function productionPlanDetail(value: string) {
  const text = readableDetail(value)
  if (!text) return '已根据当前项目状态选择下一步生产动作。'
  return text
    .replace(/\bnext_action=([a-z_]+)/i, (_, action) => `下一步：${actionLabel(action)}`)
    .replace(/\bcan_continue=True\b/i, '可以继续执行')
    .replace(/\bmode=([a-z_]+)/i, (_, mode) => `模式：${mode}`)
}

function actionLabel(action: string) {
  const labels: Record<string, string> = {
    generate_story_plan: '生成剧本/分镜',
    plan_visual_assets: '规划参考图',
    generate_keyframes: '生成关键帧',
    generate_videos: '生成视频',
    plan_final_edit: '剪辑成片',
  }
  return labels[action] || action
}

function readableDetail(value: string) {
  const text = clean(value)
  if (!text) return ''
  const readableParts = text
    .split(/[；;。]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .filter((part) => !isEvidenceText(part))
  if (readableParts.length) return readableParts.join('。')
  if (isEvidenceText(text)) return ''
  if (/queue\s+\d+.*(ltx|seedance).*credits?|剩余预算|预算/i.test(text)) return '本次预算不足，部分生产任务没有派发。'
  if (/provider\s+key\s+饱和|saturated|backpressure|too many requests|429|rate limit/i.test(text)) return 'Provider 暂时繁忙，任务已进入等待恢复状态。'
  return stageLabel(text)
}

function clean(value: unknown) {
  return String(value || '').trim()
}

function metaValue(event: TimelineEvent, key: string) {
  const meta = (event.meta || event.data || {}) as Record<string, any>
  const agentEvent = meta.agent_event && typeof meta.agent_event === 'object' ? meta.agent_event : {}
  const planner = meta.planner && typeof meta.planner === 'object' ? meta.planner : {}
  return agentEvent[key] ?? planner[key] ?? meta[key]
}

function eventSearchText(event: TimelineEvent) {
  return [
    event.actor,
    event.event_kind,
    event.event_type,
    event.phase,
    event.source,
    event.title,
    event.text,
    event.detail,
    event.summary,
    event.reason,
    JSON.stringify(event.meta || event.data || {}),
  ].join(' ').toLowerCase()
}

function extractShotIndex(event: TimelineEvent) {
  const meta = (event.meta || event.data || {}) as Record<string, any>
  const raw = meta.raw_event && typeof meta.raw_event === 'object' ? meta.raw_event as Record<string, any> : {}
  const value = meta.shot_index ?? raw.shot_index ?? raw.meta?.shot_index ?? raw.data?.shot_index
  return value === undefined || value === null || value === '' ? '' : String(value)
}

function compareEvents(a: TimelineEvent, b: TimelineEvent) {
  return eventTime(a) - eventTime(b) || String(a.id).localeCompare(String(b.id))
}

function eventTime(event: TimelineEvent) {
  const value = event.time || event.created_at || ''
  const parsed = new Date(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

function containsAny(text: string, values: string[]) {
  return values.some((value) => text.includes(value.toLowerCase()))
}

function publicActor(event: TimelineEvent, actor: string, phase: string) {
  const raw = actor.toLowerCase()
  if (raw === 'brain') return 'deepseek'
  if (raw === 'api' && phase === 'human_response') return 'deepseek'
  if (raw === 'api' && phase === 'human_instruction') return 'user'
  if (raw) return raw
  if (phase === 'llm_planner') return 'deepseek'
  if (phase === 'state_machine_gate') return 'state_machine'
  if (phase === 'executor_dispatch') return 'executor'
  return String(event.source || 'agent')
}

function stageLabel(value: string) {
  const text = String(value || '').trim()
  const labels: Record<string, string> = {
    created: '创建 Agent Run',
    read_context: '读取上下文',
    merge_memory: '合并记忆与账本',
    map_techniques: '映射创作技巧',
    check_continuity: '检查剧情承接',
    cost_guard: '成本与风控',
    delivery_audit: '成片可交付检查',
    dispatch_instruction: '发布执行指令 / 下一步判断',
    writeback_review: '回写与复盘',
    state_machine_gate: '状态机检查',
    human_instruction: '人工指令',
    llm_planner: 'DeepSeek 中控判断',
    human_response: 'DeepSeek 回复',
    executor_dispatch: '执行器派发',
    'Generate keyframes': '生成关键帧',
    generate_keyframes: '生成关键帧',
    'Generate videos': '生成视频',
    generate_videos: '生成视频',
    provider_waiting: '等待 provider 恢复',
    'Keyframe generation tasks dispatching.': '正在派发关键帧生成任务',
    'Video generation tasks dispatching.': '正在派发视频生成任务',
    'Failed video tasks must be resolved before video review.': '视频 provider 暂时繁忙，等待恢复后再确认。',
    dispatching: '派发中',
    running: '运行中',
    completed: '已完成',
    blocked: '已阻断',
    pending: '等待中',
  }
  return labels[text] || text || '等待状态机'
}

function isEvidenceText(value: string) {
  const text = String(value || '')
  return /\b(files|consumed|covered|partial|missing|total|phase|provider|task_id|artifact_id|next_action|can_continue|mode|prompt|shot_index|field|acquire_key)=/i.test(text)
    || /\bvideo_task_failures\b/i.test(text)
    || text.startsWith('{')
    || text.startsWith('[')
}
</script>

<style scoped>
.timeline-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 100%;
  background: #0d1117;
}

.timeline-header {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid #30363d;
  background: rgba(13, 17, 23, 0.96);
  padding: 14px 28px 12px;
}

h1,
p {
  margin: 0;
}

h1 {
  color: #e6edf3;
  font-size: 13px;
  line-height: 1.45;
  font-weight: 500;
}

p {
  margin-top: 3px;
  color: #8b949e;
  font-size: 12px;
}

.eyebrow {
  margin: 0 0 4px;
  color: #58a6ff;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

.timeline-header button {
  align-self: flex-start;
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #161b22;
  color: #e6edf3;
  padding: 8px 12px;
  cursor: pointer;
}

.timeline {
  overflow: auto;
  padding: 18px 30px 42px;
}

.workflow-summary {
  display: grid;
  gap: 6px;
  max-width: 980px;
  margin-bottom: 14px;
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #161b22;
  padding: 10px 14px;
}

.workflow-summary.blocked {
  border-color: rgba(248, 81, 73, 0.55);
}

.workflow-summary div {
  display: grid;
  gap: 2px;
}

.workflow-summary span {
  color: #8b949e;
  font-size: 11px;
}

.workflow-summary strong {
  color: #e6edf3;
  font-size: 13px;
}

.workflow-summary p {
  color: #f0c36a;
  font-size: 11px;
  margin: 0;
  line-height: 1.4;
}

.stream {
  position: relative;
  max-width: 980px;
}

.stream::before {
  content: '';
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 11px;
  width: 1px;
  background: #30363d;
}

.typing-row {
  position: relative;
  display: grid;
  grid-template-columns: 24px auto minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  padding: 12px 0;
}

.cursor {
  z-index: 1;
  width: 22px;
  height: 22px;
  border: 1px solid #58a6ff;
  border-radius: 50%;
  background: #0d1117;
  box-shadow: 0 0 0 4px rgba(88, 166, 255, 0.08);
}

.typing-row strong {
  color: #e6edf3;
  font-size: 13px;
}

.typing-row em {
  color: #8b949e;
  font-size: 11px;
  font-style: normal;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty {
  display: grid;
  gap: 8px;
  justify-items: center;
  margin-top: 80px;
  color: #8b949e;
}

.empty strong {
  color: #e6edf3;
}

@media (max-width: 760px) {
  .timeline-header {
    padding: 16px;
  }

  .timeline {
    padding: 14px 18px 36px;
  }
}
</style>
