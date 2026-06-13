import { effectScope, onUnmounted, ref, watch, type EffectScope } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { WsMessage } from '@/types/ws'

/**
 * WebSocket 单例 — 全应用共享一条连接。
 *
 * 设计要点：
 * - 单例：多个页面/组件 useWebSocket() 复用同一个 WebSocket
 * - 引用计数：最后一个消费者销毁时断开（可选保留，当前实现保留到 logout）
 * - Token 变化（刷新/登录/登出）联动重连，已订阅的 task_ids 自动恢复
 * - 未连接时的 outbound 消息进队列，连接成功后 flush
 */

type Listener = (msg: any) => void

const connected = ref(false)
const listeners = new Map<string, Set<Listener>>()
const subscriptions = new Set<string>()
const projectSubscriptions = new Set<string>()
const outbound: string[] = []

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
let reconnectAttempts = 0
let manuallyClosed = false
let currentToken: string | null = null
let tokenWatchScope: EffectScope | null = null
const MAX_RECONNECT = 10

function send(payload: string) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(payload)
  } else {
    outbound.push(payload)
  }
}

function flushOutbound() {
  if (ws?.readyState !== WebSocket.OPEN) return
  while (outbound.length > 0) {
    ws.send(outbound.shift() as string)
  }
}

function resubscribe() {
  if (subscriptions.size > 0) {
    const ids = Array.from(subscriptions)
    send(JSON.stringify({ type: 'subscribe', task_ids: ids }))
  }
  if (projectSubscriptions.size > 0) {
    const projectIds = Array.from(projectSubscriptions)
    send(JSON.stringify({ type: 'subscribe_project', project_ids: projectIds }))
  }
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeatTimer = setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }))
    }
  }, 30000)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

function clearReconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  reconnectAttempts = 0
}

function scheduleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT) return
  const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
  reconnectTimer = setTimeout(() => {
    reconnectAttempts++
    connect()
  }, delay)
}

function connect() {
  const authStore = useAuthStore()
  if (!authStore.accessToken) return
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return

  manuallyClosed = false
  currentToken = authStore.accessToken

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${protocol}//${window.location.host}/ws/tasks?token=${currentToken}`

  ws = new WebSocket(url)

  ws.onopen = () => {
    connected.value = true
    reconnectAttempts = 0
    startHeartbeat()
    resubscribe()
    flushOutbound()
  }

  ws.onmessage = (event) => {
    let msg: WsMessage
    try {
      msg = JSON.parse(event.data)
    } catch {
      return
    }
    const typeListeners = listeners.get(msg.type)
    if (typeListeners) {
      typeListeners.forEach((cb) => cb(msg))
    }
  }

  ws.onclose = () => {
    connected.value = false
    stopHeartbeat()
    const authStore = useAuthStore()
    if (!manuallyClosed && authStore.accessToken) {
      scheduleReconnect()
    }
  }

  ws.onerror = () => {
    ws?.close()
  }
}

function subscribe(taskIds: string[]) {
  taskIds.forEach((id) => subscriptions.add(id))
  send(JSON.stringify({ type: 'subscribe', task_ids: taskIds }))
}

function unsubscribe(taskIds: string[]) {
  taskIds.forEach((id) => subscriptions.delete(id))
  send(JSON.stringify({ type: 'unsubscribe', task_ids: taskIds }))
}

function subscribeProject(projectIds: string[]) {
  const ids = projectIds.map((id) => String(id || '').trim()).filter(Boolean)
  ids.forEach((id) => projectSubscriptions.add(id))
  send(JSON.stringify({ type: 'subscribe_project', project_ids: ids }))
}

function unsubscribeProject(projectIds: string[]) {
  const ids = projectIds.map((id) => String(id || '').trim()).filter(Boolean)
  ids.forEach((id) => projectSubscriptions.delete(id))
  send(JSON.stringify({ type: 'unsubscribe_project', project_ids: ids }))
}

function on(type: string, cb: Listener) {
  if (!listeners.has(type)) listeners.set(type, new Set())
  listeners.get(type)!.add(cb)
}

function off(type: string, cb: Listener) {
  listeners.get(type)?.delete(cb)
}

function disconnect() {
  manuallyClosed = true
  clearReconnect()
  stopHeartbeat()
  ws?.close()
  ws = null
  connected.value = false
}

function startTokenWatcher() {
  if (tokenWatchScope) return

  tokenWatchScope = effectScope(true)
  tokenWatchScope.run(() => {
    const authStore = useAuthStore()
    let reconnectDebounce: ReturnType<typeof setTimeout> | null = null
    watch(
      () => authStore.accessToken,
      (token) => {
        if (token === currentToken) return
        if (!token) {
          disconnect()
          return
        }
        if (reconnectDebounce) clearTimeout(reconnectDebounce)
        reconnectDebounce = setTimeout(() => {
          clearReconnect()
          stopHeartbeat()
          if (ws) {
            manuallyClosed = true
            ws.close()
            ws = null
          }
          manuallyClosed = false
          connect()
        }, 300)
      }
    )
  })
}

/**
 * 组件调用入口。单例内部实现，组件只看到接口。
 * 注意：subscribe/unsubscribe 的清理仍由调用方负责（组件 onUnmounted 调 unsubscribe）。
 */
export function useWebSocket() {
  startTokenWatcher()

  // 组件销毁时不自动 disconnect（其他页面可能还在用），只清自己注册的 listener 需由调用方 off()
  onUnmounted(() => {
    // no-op — 单例，别断其他页面的连接
  })

  return {
    connected,
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    subscribeProject,
    unsubscribeProject,
    on,
    off,
  }
}

/** 外部手动断开（例如 logout 流程已经由 watcher 处理，但提供显式入口） */
export function closeWebSocket() {
  disconnect()
}
