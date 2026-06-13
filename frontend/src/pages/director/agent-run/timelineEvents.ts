import type { AgentEvent, AgentRunSnapshotStreamItem } from '@/api/director'

export type AgentRunTimelineEvent = (Partial<AgentRunSnapshotStreamItem> & Partial<AgentEvent>) & {
  id: string
  time?: string | null
  created_at?: string
  text?: string
  level?: string
  title?: string
  detail?: string
  node_id?: string
  visibility?: string
  event_kind?: string
  summary?: string
  reason?: string
}

export function mergeAgentRunTimelineEvents(
  snapshotEvents: Array<Partial<AgentRunSnapshotStreamItem> & { id?: string }> = [],
  liveEvents: Array<Partial<AgentEvent> & { id?: string }> = [],
): AgentRunTimelineEvent[] {
  const seen = new Set<string>()
  const rows: AgentRunTimelineEvent[] = []

  for (const event of [...snapshotEvents, ...liveEvents]) {
    const id = String(event.id || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    rows.push({ ...(event as AgentRunTimelineEvent), id })
  }

  return rows.sort((a, b) => eventTime(a) - eventTime(b) || a.id.localeCompare(b.id))
}

export function buildAgentRunTimelineEvents(events: AgentRunTimelineEvent[] = []): AgentRunTimelineEvent[] {
  const seen = new Set<string>()
  const rows: AgentRunTimelineEvent[] = []

  for (const event of events) {
    const id = String(event.id || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    rows.push(normalizeTimelineEvent({ ...event, id }))
  }

  return rows.sort((a, b) => eventTime(a) - eventTime(b) || a.id.localeCompare(b.id))
}

function normalizeTimelineEvent(event: AgentRunTimelineEvent): AgentRunTimelineEvent {
  const phase = clean(event.phase || event.node_id)
  const type = clean(event.event_type || event.type || event.level)
  const actor = actorForEvent(event)
  const title = readableTitle(event, phase, type)
  const detail = readableDetail(event)
  const status = readableStatus(event)

  return {
    ...event,
    actor,
    event_type: type || event.event_type || 'trace',
    title,
    detail: detail && detail !== title ? detail : '',
    status,
    meta: {
      raw_event: event,
      source_event_id: event.id,
    },
  }
}

function readableTitle(event: AgentRunTimelineEvent, phase: string, type: string) {
  const explicit = clean(event.title || event.text)
  if (explicit && !looksLikeEvidence(explicit)) return explicit

  if (isProviderWaitingEvent(event)) return 'Provider 等待恢复'
  if (type === 'error') return '执行遇到错误'
  if (type === 'risk' || clean(event.status) === 'blocked') return phaseLabel(phase) || '执行被状态机阻断'

  return phaseLabel(phase) || eventTypeLabel(type) || '执行链事件'
}

function readableDetail(event: AgentRunTimelineEvent) {
  const meta = eventMeta(event)
  const agentEvent = objectValue(meta.agent_event)
  const planner = objectValue(meta.planner)
  const rawValues = [
    event.detail,
    event.summary,
    event.reason,
    agentEvent.summary,
    agentEvent.reason,
    meta.answer,
    planner.reply,
    meta.output,
    meta.decision,
    meta.message,
    event.text,
  ]

  for (const value of rawValues) {
    const readable = readableSentence(value)
    if (readable) return readable
  }
  return ''
}

function readableSentence(value: unknown) {
  const text = clean(value)
  if (!text || isJsonLike(text)) return ''

  const pieces = text
    .split(/[；;。]/)
    .map((piece) => piece.trim())
    .filter(Boolean)
    .filter((piece) => !looksLikeEvidence(piece))

  if (pieces.length) return pieces.join('。')
  return looksLikeEvidence(text) ? '' : text
}

function actorForEvent(event: AgentRunTimelineEvent) {
  const raw = clean(event.actor || event.source).toLowerCase()
  if (raw) {
    if (raw === 'brain') return 'deepseek'
    if (raw === 'api') return phaseMatches(event, ['human_instruction', 'human_response']) ? 'user' : 'agent'
    return raw
  }
  if (phaseMatches(event, ['human_instruction'])) return 'user'
  if (phaseMatches(event, ['llm_planner', 'human_response'])) return 'deepseek'
  if (phaseMatches(event, ['state_machine_gate'])) return 'state_machine'
  if (phaseMatches(event, ['executor_dispatch'])) return 'executor'
  return 'agent'
}

function readableStatus(event: AgentRunTimelineEvent) {
  if (isProviderWaitingEvent(event)) return 'provider_waiting'
  const status = clean(event.status)
  if (status) return status
  const type = clean(event.event_type || event.type)
  if (type === 'error') return 'failed'
  if (type === 'risk') return 'blocked'
  return status
}

function phaseMatches(event: AgentRunTimelineEvent, phases: string[]) {
  const phase = clean(event.phase || event.node_id)
  return phases.includes(phase)
}

function phaseLabel(phase: string) {
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
  }
  return labels[phase] || phase
}

function eventTypeLabel(type: string) {
  const labels: Record<string, string> = {
    trace: '链路追踪',
    decision: '决策检查',
    tool_call: '工具调用',
    tool_result: '工具结果',
    risk: '风险检查',
    error: '错误',
    progress: '执行进度',
    artifact: '产物写回',
  }
  return labels[type] || type
}

function isProviderWaitingEvent(event: AgentRunTimelineEvent) {
  return /provider_waiting|provider deferred|saturated|backpressure|too many requests|429|rate limit/i.test(
    [
      event.event_type,
      event.phase,
      event.status,
      event.title,
      event.detail,
      event.summary,
      event.reason,
      JSON.stringify(event.meta || event.data || {}),
    ].join(' '),
  )
}

function eventMeta(event: AgentRunTimelineEvent) {
  return (event.meta || event.data || {}) as Record<string, unknown>
}

function objectValue(value: unknown) {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function clean(value: unknown) {
  return String(value || '').trim()
}

function isJsonLike(value: string) {
  return (value.startsWith('{') && value.endsWith('}')) || (value.startsWith('[') && value.endsWith(']'))
}

function looksLikeEvidence(value: string) {
  return /\b(files|consumed|covered|partial|missing|total|phase|provider|task_id|artifact_id|next_action|can_continue|mode|prompt|shot_index|field|acquire_key)=/i.test(value)
    || /\bvideo_task_failures\b/i.test(value)
}

function eventTime(event: AgentRunTimelineEvent): number {
  const value = event.time || event.created_at || ''
  const parsed = new Date(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}
