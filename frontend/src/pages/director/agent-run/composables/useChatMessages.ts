import { computed, ref } from 'vue'
import type { AgentEvent, AgentRunSnapshot, AgentRunSnapshotStreamItem } from '@/api/director'

export type ChatMessageRole = 'user' | 'assistant' | 'system'
export type ChatMessageType = 'text' | 'step_card' | 'media_card' | 'progress' | 'error'

export interface ChatMessage {
  id: string
  role: ChatMessageRole
  type: ChatMessageType
  content: string
  streaming: boolean
  streamId?: string
  actor?: string
  timestamp: string
  stepTitle?: string
  stepDetail?: string
  stepStatus?: 'running' | 'done' | 'error'
  stepItems?: Array<{ label: string; status: 'done' | 'running' | 'pending' }>
  mediaUrls?: string[]
  mediaType?: 'image' | 'video'
  progress?: number
  progressTotal?: number
  progressLabel?: string
}

interface LlmStreamEvent {
  type: string
  stream_id: string
  run_id: string
  actor?: string
  content?: string
  index?: number
  full_text?: string
  phase?: string
}

export function useChatMessages(runId: () => string) {
  const messages = ref<ChatMessage[]>([])
  const isStreaming = computed(() => messages.value.some((m) => m.streaming))

  function handleLlmStreamStart(event: LlmStreamEvent) {
    if (event.run_id !== runId()) return
    const existing = messages.value.find((m) => m.streamId === event.stream_id)
    if (existing) return
    messages.value = [
      ...messages.value,
      {
        id: `stream-${event.stream_id}`,
        role: 'assistant',
        type: 'text',
        content: '',
        streaming: true,
        streamId: event.stream_id,
        actor: event.actor || 'deepseek',
        timestamp: new Date().toISOString(),
      },
    ]
  }

  function handleLlmChunk(event: LlmStreamEvent) {
    if (event.run_id !== runId()) return
    const msg = messages.value.find((m) => m.streamId === event.stream_id)
    if (msg) {
      msg.content += event.content || ''
    }
  }

  function handleLlmStreamEnd(event: LlmStreamEvent) {
    if (event.run_id !== runId()) return
    const msg = messages.value.find((m) => m.streamId === event.stream_id)
    if (msg) {
      msg.streaming = false
      if (event.full_text) msg.content = event.full_text
    }
  }

  function handleExecutionEvent(event: AgentEvent) {
    if (event.run_id !== runId()) return
    if (String((event as any).visibility || '').toLowerCase() === 'debug' && String((event as any).phase || '').toLowerCase() !== 'llm_planner') return

    const mapped = mapEventToMessage(event)
    if (!mapped) return

    const existing = messages.value.find((m) => m.id === mapped.id)
    if (existing) return
    messages.value = [...messages.value, mapped]
  }

  function addUserMessage(text: string) {
    messages.value = [
      ...messages.value,
      {
        id: `user-${Date.now()}`,
        role: 'user',
        type: 'text',
        content: text,
        streaming: false,
        timestamp: new Date().toISOString(),
      },
    ]
  }

  function addAssistantMessage(text: string, id = `assistant-${Date.now()}`) {
    const content = String(text || '').trim()
    if (!content) return
    if (messages.value.some((m) => m.role === 'assistant' && m.content === content)) return
    messages.value = [
      ...messages.value,
      {
        id,
        role: 'assistant',
        type: 'text',
        content,
        streaming: false,
        actor: 'deepseek',
        timestamp: new Date().toISOString(),
      },
    ]
  }

  function assistantMessageCount() {
    return messages.value.filter((m) => m.role === 'assistant').length
  }

  function loadFromSnapshot(snapshot: AgentRunSnapshot | null) {
    if (!snapshot) return
    // Don't load from snapshot while actively streaming — it would duplicate the message
    if (isStreaming.value) return

    const stream = (snapshot.stream || []) as Array<AgentRunSnapshotStreamItem & Record<string, any>>
    const loaded: ChatMessage[] = []
    const seenIds = new Set<string>()

    for (const event of stream) {
      if (String(event.visibility || '').toLowerCase() === 'debug' && String((event as any).phase || '').toLowerCase() !== 'llm_planner') continue
      const mapped = mapEventToMessage(event as any)
      if (!mapped) continue
      if (seenIds.has(mapped.id)) continue
      seenIds.add(mapped.id)
      loaded.push(mapped)
    }
    for (const mapped of mapSnapshotOutputsToMessages(snapshot)) {
      if (seenIds.has(mapped.id)) continue
      seenIds.add(mapped.id)
      loaded.push(mapped)
    }

    const merged = [...loaded]
    for (const msg of messages.value) {
      if (merged.find((m) => m.id === msg.id) || hasEquivalentMessage(merged, msg)) continue
      if (msg.streaming || msg.role === 'user' || msg.role === 'assistant') {
        merged.push(msg)
      }
    }
    messages.value = merged.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
  }

  function clear() {
    messages.value = []
  }

  return {
    messages,
    isStreaming,
    handleLlmStreamStart,
    handleLlmChunk,
    handleLlmStreamEnd,
    handleExecutionEvent,
    addUserMessage,
    addAssistantMessage,
    assistantMessageCount,
    loadFromSnapshot,
    clear,
  }
}

function mapEventToMessage(event: any): ChatMessage | null {
  const meta = (event.meta && typeof event.meta === 'object') ? event.meta : {}
  const eventType = String(event.event_type || '')
  const phase = String(event.phase || event.node_id || '')
  const actor = String(event.actor || meta.actor || event.source || '').toLowerCase()
  const title = String(event.title || event.text || '').trim()
  const detail = String(event.detail || meta.detail || '').trim()
  const summary = String(event.summary || meta.summary || '').trim()
  const answer = String(meta.answer || event.answer || '').trim()
  const status = String(event.status || '')
  const text = [eventType, phase, actor, title, detail, summary, answer].join(' ').toLowerCase()
  const timestamp = event.created_at || event.time || new Date().toISOString()
  const id = String(event.id || `evt-${Date.now()}-${Math.random()}`)

  if (phase === 'llm_planner') {
    return {
      id,
      role: 'system',
      type: 'step_card',
      content: '',
      streaming: false,
      actor: 'deepseek',
      timestamp,
      stepTitle: 'DeepSeek 中控判断',
      stepDetail: detail || summary || answer || title,
      stepStatus: status === 'failed' ? 'error' : 'done',
    }
  }

  if (eventType === 'human_input' || phase === 'human_instruction' || actor === 'user') {
    return {
      id,
      role: 'user',
      type: 'text',
      content: detail || summary || String(meta.instruction || '').trim() || title,
      streaming: false,
      timestamp,
    }
  }

  if (phase === 'human_response' || containsAny(text, ['deepseek 先答复', 'deepseek 回复'])) {
    return {
      id,
      role: 'assistant',
      type: 'text',
      content: answer || detail || summary || title,
      streaming: false,
      actor: 'deepseek',
      timestamp,
    }
  }

  if (phase === 'dispatch_instruction' || containsAny(text, ['确定执行计划', '执行计划'])) {
    return {
      id,
      role: 'system',
      type: 'step_card',
      content: '',
      streaming: false,
      actor: actor || 'deepseek',
      timestamp,
      stepTitle: '执行计划',
      stepDetail: detail || summary || '已根据当前项目状态选择下一步生产动作。',
      stepStatus: 'done',
    }
  }

  if (phase === 'executor_dispatch' || containsAny(text, ['派发关键帧', '派发视频', '派发生产'])) {
    return {
      id,
      role: 'system',
      type: 'step_card',
      content: '',
      streaming: false,
      actor: 'executor',
      timestamp,
      stepTitle: extractDispatchTitle(text),
      stepDetail: detail || summary || '',
      stepStatus: status === 'done' || status === 'completed' ? 'done' : 'running',
    }
  }

  if (containsAny(text, ['写回', 'writeback_selected_image', 'writeback_selected_video', '关键帧已写回', '视频片段已写回'])) {
    const mediaType = containsAny(text, ['video', '视频']) ? 'video' : 'image'
    return {
      id,
      role: 'system',
      type: 'media_card',
      content: detail || summary || (mediaType === 'image' ? '关键帧已写回' : '视频片段已写回'),
      streaming: false,
      actor: mediaType === 'image' ? 'seedream' : actor || 'joy-echo',
      timestamp,
      mediaType,
    }
  }

  if (eventType === 'error' || eventType === 'risk' || status === 'failed' || status === 'blocked') {
    return {
      id,
      role: 'system',
      type: 'error',
      content: detail || summary || title || '执行遇到错误',
      streaming: false,
      actor: actor || 'executor',
      timestamp,
    }
  }

  if (containsAny(text, ['provider_waiting', 'saturated', 'backpressure'])) {
    return {
      id,
      role: 'system',
      type: 'progress',
      content: detail || summary || 'Provider 暂时繁忙，等待恢复中...',
      streaming: false,
      actor: actor || 'joy-echo',
      timestamp,
      progressLabel: '等待 Provider 恢复',
    }
  }

  return null
}

function extractDispatchTitle(text: string): string {
  if (containsAny(text, ['keyframe', '关键帧', '出图', 'seedream'])) return '已派发关键帧生成'
  if (containsAny(text, ['final_edit', 'plan_final_edit', '剪辑', '成片', '导出', 'export'])) return '已派发剪辑成片'
  if (containsAny(text, ['video', '视频', 'ltx', 'seedance', 'kling'])) return '已派发视频生成'
  return '已派发生产任务'
}

function containsAny(text: string, keywords: string[]): boolean {
  return keywords.some((k) => text.includes(k.toLowerCase()))
}

function hasEquivalentMessage(messages: ChatMessage[], candidate: ChatMessage): boolean {
  const content = normalizeMessageText(candidate.content || candidate.stepDetail || '')
  if (!content) return false
  return messages.some((msg) => {
    if (msg.role !== candidate.role || msg.type !== candidate.type) return false
    return normalizeMessageText(msg.content || msg.stepDetail || '') === content
  })
}

function normalizeMessageText(value: string): string {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function mapSnapshotOutputsToMessages(snapshot: AgentRunSnapshot): ChatMessage[] {
  const outputs = snapshot.outputs
  if (!outputs) return []

  const timestamp = snapshot.run.ended_at || snapshot.run.started_at || new Date().toISOString()
  const messages: ChatMessage[] = []
  const images = Array.isArray(outputs.images) ? outputs.images : []
  const videos = Array.isArray(outputs.videos) ? outputs.videos : []
  const summary = outputs.summary || { image_count: 0, video_count: 0, shot_count: 0 }
  const shots = Array.isArray(outputs.shots) ? outputs.shots : []
  const missingVideos = shots
    .filter((shot) => String(shot.selected_image || '').trim() && !String(shot.selected_video || '').trim())
    .map((shot) => shot.shot_index)
    .filter((value) => value != null && value !== '')
  const reviewBlockers = shots
    .flatMap((shot) => {
      const items: string[] = []
      const imageStatus = String((shot as any).image_review_status || '').trim()
      const videoStatus = String((shot as any).video_review_status || '').trim()
      if (['needs_review', 'regenerate', 'failed', 'fail', 'rejected', 'blocked'].includes(imageStatus)) {
        items.push(imageStatus === 'needs_review' ? `第${shot.shot_index}镜关键帧待确认` : `第${shot.shot_index}镜关键帧未通过`)
      }
      if (['needs_review', 'regenerate', 'failed', 'fail', 'rejected', 'blocked'].includes(videoStatus)) {
        items.push(videoStatus === 'needs_review' ? `第${shot.shot_index}镜视频待确认` : `第${shot.shot_index}镜视频未通过`)
      }
      return items
    })
    .filter(Boolean)

  if (summary.image_count || summary.video_count || summary.shot_count || missingVideos.length) {
    const parts = [
      `参考图/关键帧 ${summary.image_count || images.length || 0} 张`,
      `视频片段 ${summary.video_count || videos.length || 0} 个`,
      `镜头 ${summary.shot_count || shots.length || 0} 个`,
    ]
    if (missingVideos.length) {
      parts.push(`仍缺视频：${missingVideos.map((item) => `第${item}镜`).join('、')}`)
    }
    if (reviewBlockers.length) {
      parts.push(`审查阻塞：${reviewBlockers.slice(0, 6).join('、')}`)
    }
    if (summary.final_video_url) {
      parts.push('成片已生成')
    }
    messages.push({
      id: `outputs-summary-${snapshot.run.run_id}`,
      role: 'system',
      type: 'step_card',
      content: '',
      streaming: false,
      actor: 'executor',
      timestamp,
      stepTitle: '当前结果',
      stepDetail: parts.join('；'),
      stepStatus: reviewBlockers.length ? 'error' : missingVideos.length ? 'running' : 'done',
    })
  }

  const notes = (outputs.director_notes || [])
    .filter((note) => {
      const text = `${note.title || ''}\n${note.content || ''}`
      return text.trim() && !/covered=|missing=|ledger|debug|tool_result|next_action|can_continue|dispatch_ready/i.test(text)
    })
    .slice(0, 3)
  if (notes.length) {
    messages.push({
      id: `director-notes-${snapshot.run.run_id}`,
      role: 'system',
      type: 'step_card',
      content: '',
      streaming: false,
      actor: 'deepseek',
      timestamp,
      stepTitle: '导演建议',
      stepDetail: notes.map((note) => `${note.title || '建议'}：${note.content}`).join('\n'),
      stepStatus: 'done',
    })
  }

  return messages
}
