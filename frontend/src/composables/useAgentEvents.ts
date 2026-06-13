import { ref, computed, onUnmounted } from 'vue'
import { useWebSocket } from './useWebSocket'
import { getAgentEvents, getAgentRunEvents, type AgentEvent } from '@/api/director'

const MAX_EVENTS = 200

export interface AgentEventFilter {
  event_type?: string
  run_id?: string
  task_id?: string
}

/**
 * Agent 事件实时订阅 composable。
 *
 * 通过 WebSocket 订阅项目事件，后端 Redis channel 为 `project:{project_id}:events`，
 * 同时提供 loadHistory() 拉取历史记录。
 *
 * 用法：
 *   const { events, filtered, subscribe, unsubscribe, loadHistory } = useAgentEvents()
 *   subscribe(projectId)
 *   const running = filtered({ event_type: 'step_start' })
 */
export function useAgentEvents() {
  const events = ref<AgentEvent[]>([])
  const filter = ref<AgentEventFilter>({})
  const loading = ref(false)

  const ws = useWebSocket()
  let subscribedProjectId: string | null = null
  let subscribedRunId: string | null = null

  const filtered = computed(() => {
    const f = filter.value
    return events.value.filter((e) => {
      if (f.event_type && e.event_type !== f.event_type) return false
      if (f.run_id && e.run_id !== f.run_id) return false
      if (f.task_id && e.task_id !== f.task_id) return false
      return true
    })
  })

  function setFilter(f: AgentEventFilter) {
    filter.value = f
  }

  function clearFilter() {
    filter.value = {}
  }

  function pushEvent(event: AgentEvent) {
    events.value.push(event)
    if (events.value.length > MAX_EVENTS) {
      events.value = events.value.slice(-MAX_EVENTS)
    }
  }

  function handleWsMessage(msg: any) {
    if (msg.project_id && subscribedProjectId && String(msg.project_id) !== subscribedProjectId) {
      return
    }
    if (subscribedRunId && String(msg.run_id || '') !== subscribedRunId) {
      return
    }
    const event: AgentEvent = {
      id: msg.id || `${msg.run_id}-${Date.now()}`,
      type: msg.type || 'execution_event',
      event_type: msg.event_type,
      run_id: msg.run_id ?? null,
      project_id: msg.project_id,
      task_id: msg.task_id ?? null,
      step_id: msg.step_id ?? null,
      user_id: msg.user_id ?? null,
      source: msg.source,
      phase: msg.phase,
      title: msg.title,
      detail: msg.detail,
      status: msg.status,
      progress: msg.progress ?? null,
      meta: msg.meta ?? msg.data ?? {},
      data: msg.data ?? msg.meta ?? {},
      created_at: msg.created_at || new Date().toISOString(),
    }
    pushEvent(event)
  }

  function subscribe(projectId: string, options?: { run_id?: string }) {
    subscribedProjectId = String(projectId)
    subscribedRunId = options?.run_id ? String(options.run_id) : null
    ws.connect()
    ws.subscribeProject([subscribedProjectId])
    ws.on('execution_event', handleWsMessage)
    ws.on('agent_event', handleWsMessage)
  }

  function unsubscribe() {
    if (subscribedProjectId) {
      ws.unsubscribeProject([subscribedProjectId])
    }
    ws.off('execution_event', handleWsMessage)
    ws.off('agent_event', handleWsMessage)
    subscribedProjectId = null
    subscribedRunId = null
  }

  async function loadHistory(projectId: string, options?: { limit?: number; run_id?: string }) {
    loading.value = true
    try {
      const { data } = options?.run_id
        ? await getAgentRunEvents(options.run_id, { limit: options?.limit ?? MAX_EVENTS })
        : await getAgentEvents(projectId, { limit: options?.limit ?? MAX_EVENTS })
      events.value = data.events
    } finally {
      loading.value = false
    }
  }

  function clear() {
    events.value = []
  }

  onUnmounted(unsubscribe)

  return {
    events,
    filtered,
    filter,
    loading,
    subscribe,
    unsubscribe,
    loadHistory,
    setFilter,
    clearFilter,
    clear,
  }
}
