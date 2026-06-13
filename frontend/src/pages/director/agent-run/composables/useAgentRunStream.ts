import { computed, onUnmounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { AgentEvent } from '@/api/director'

const MAX_EVENTS = 500

export interface LlmStreamEvent {
  type: string
  stream_id: string
  run_id: string
  actor?: string
  content?: string
  index?: number
  full_text?: string
  phase?: string
}

export type LlmStreamHandler = (event: LlmStreamEvent) => void

export function useAgentRunStream() {
  const events = ref<AgentEvent[]>([])
  const connected = ref(false)
  const error = ref('')
  const status = ref('')
  let source: EventSource | null = null

  let onLlmStreamStart: LlmStreamHandler | null = null
  let onLlmChunk: LlmStreamHandler | null = null
  let onLlmStreamEnd: LlmStreamHandler | null = null

  const eventCount = computed(() => events.value.length)

  function stop() {
    source?.close()
    source = null
    connected.value = false
  }

  function start(runId: string) {
    stop()
    events.value = []
    error.value = ''
    status.value = ''

    const token = useAuthStore().accessToken
    if (!runId || !token) {
      error.value = 'Missing run id or access token'
      return
    }

    const url = `/api/agent-runs/${encodeURIComponent(runId)}/stream?token=${encodeURIComponent(token)}`
    source = new EventSource(url)

    source.addEventListener('open', () => {
      connected.value = true
      error.value = ''
    })

    source.addEventListener('execution_event', (message) => {
      const event = parseEvent(message)
      if (!event?.id) return
      const existing = new Set(events.value.map((item) => item.id))
      if (existing.has(event.id)) return
      events.value = [...events.value, event].slice(-MAX_EVENTS)
    })

    source.addEventListener('llm_stream_start', (message) => {
      const payload = parseJson(message) as LlmStreamEvent
      if (payload && onLlmStreamStart) onLlmStreamStart(payload)
    })

    source.addEventListener('llm_chunk', (message) => {
      const payload = parseJson(message) as LlmStreamEvent
      if (payload && onLlmChunk) onLlmChunk(payload)
    })

    source.addEventListener('llm_stream_end', (message) => {
      const payload = parseJson(message) as LlmStreamEvent
      if (payload && onLlmStreamEnd) onLlmStreamEnd(payload)
    })

    source.addEventListener('stream_ready', (message) => {
      const payload = parseJson(message)
      status.value = String(payload?.status || '')
    })

    source.addEventListener('heartbeat', (message) => {
      const payload = parseJson(message)
      status.value = String(payload?.status || status.value || '')
    })

    source.addEventListener('stream_done', (message) => {
      const payload = parseJson(message)
      status.value = String(payload?.status || status.value || '')
      stop()
    })

    source.onerror = () => {
      connected.value = false
      error.value = 'Agent stream disconnected; retrying...'
    }
  }

  function clear() {
    events.value = []
  }

  function setLlmHandlers(handlers: {
    onStart?: LlmStreamHandler
    onChunk?: LlmStreamHandler
    onEnd?: LlmStreamHandler
  }) {
    onLlmStreamStart = handlers.onStart || null
    onLlmChunk = handlers.onChunk || null
    onLlmStreamEnd = handlers.onEnd || null
  }

  onUnmounted(stop)

  return {
    events,
    eventCount,
    connected,
    error,
    status,
    start,
    stop,
    clear,
    setLlmHandlers,
  }
}

function parseEvent(message: Event): AgentEvent | null {
  const payload = parseJson(message)
  if (!payload || typeof payload !== 'object') return null
  return payload as AgentEvent
}

function parseJson(message: Event): any {
  try {
    return JSON.parse((message as MessageEvent).data)
  } catch {
    return null
  }
}
