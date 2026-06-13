import { ref, onUnmounted } from 'vue'
import client from '@/api/client'
import type { Task } from '@/types/api'

const POLL_INTERVAL = 2000
const POLL_TIMEOUT = 10 * 60 * 1000

const TERMINAL_STATUSES = new Set(['done', 'failed', 'cancelled', 'dead_letter'])

/**
 * 轮询单个任务状态直到终态。
 *
 * 用法：
 *   const { status, progress, stageText, result, error, isPolling, start, stop } = useTaskPoller()
 *   start(taskId)
 */
export function useTaskPoller() {
  const status = ref('')
  const progress = ref(0)
  const stageText = ref('')
  const result = ref<any>(null)
  const error = ref('')
  const isPolling = ref(false)

  let timer: ReturnType<typeof setTimeout> | null = null
  let timeoutTimer: ReturnType<typeof setTimeout> | null = null
  let currentTaskId: string | null = null

  async function poll() {
    if (!currentTaskId || !isPolling.value) return
    try {
      const { data } = await client.get<Task>(`/tasks/${currentTaskId}`, { silent: true })
      status.value = data.status
      progress.value = data.progress
      stageText.value = data.stage_text ?? ''
      result.value = data.result ?? null
      error.value = data.error_message ?? ''

      if (TERMINAL_STATUSES.has(data.status)) {
        stop()
        return
      }
    } catch {
      // Network blip — keep polling, don't surface transient errors
    }
    if (isPolling.value) {
      timer = setTimeout(poll, POLL_INTERVAL)
    }
  }

  function start(taskId: string) {
    stop()
    currentTaskId = taskId
    status.value = ''
    progress.value = 0
    stageText.value = ''
    result.value = null
    error.value = ''
    isPolling.value = true

    poll()

    timeoutTimer = setTimeout(() => {
      if (isPolling.value) stop()
    }, POLL_TIMEOUT)
  }

  function stop() {
    isPolling.value = false
    currentTaskId = null
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    if (timeoutTimer) {
      clearTimeout(timeoutTimer)
      timeoutTimer = null
    }
  }

  onUnmounted(stop)

  return { status, progress, stageText, result, error, isPolling, start, stop }
}
