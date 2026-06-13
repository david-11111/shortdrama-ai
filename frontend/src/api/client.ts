/**
 * Axios 实例 — 统一的 HTTP 客户端。
 *
 * 功能:
 * - 自动附加 Authorization header
 * - JWT exp 预检：Token 快过期时在请求前先刷新，避免一次 401 往返
 * - Token 过期自动刷新（401 拦截）—— 刷新失败立即登出，防递归
 * - 请求去重（通过 dedupeKey 合并同一业务动作的重复请求）
 * - 全局错误 toast（可按请求 silent 关闭）
 * - 支持 AbortController（按调用传 signal）
 */
import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { useAuthStore } from '@/stores/auth'
import { emitAuthExpired } from './authEvents'
import { creditLimitRedirectUrl, isCreditLimitError, showErrorToast } from './errorToast'
import { tokenExpiringSoon } from '@/utils/jwt'

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 唯一键；同 key 的并发请求会被合并成一次 */
    dedupeKey?: string
    /** 请求期间禁止触发全局错误 toast（由调用方自己处理错误） */
    silent?: boolean
    /** 跳过 Authorization 注入（登录 / 刷新 Token 调用时用） */
    skipAuth?: boolean
  }
  export interface InternalAxiosRequestConfig {
    _retry?: boolean
    dedupeKey?: string
    silent?: boolean
    skipAuth?: boolean
  }
}

/** exp 预刷阈值：剩余不到 N 秒就先刷 */
const REFRESH_AHEAD_SECONDS = 45

const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// ---------- 请求去重 ----------
const inflight = new Map<string, Promise<AxiosResponse<any>>>()

// ---------- 刷新队列 ----------
let isRefreshing = false
let pendingRequests: Array<(token: string | null) => void> = []

function flushPending(token: string | null) {
  const queue = pendingRequests
  pendingRequests = []
  queue.forEach((cb) => cb(token))
}

async function handleAuthExpired(authStore: ReturnType<typeof useAuthStore>) {
  flushPending(null)
  await authStore.logout({ remote: false })
  emitAuthExpired()
}

async function ensureFreshToken(authStore: ReturnType<typeof useAuthStore>): Promise<string | null> {
  if (!authStore.accessToken) return null
  if (!tokenExpiringSoon(authStore.accessToken, REFRESH_AHEAD_SECONDS)) {
    return authStore.accessToken
  }
  if (isRefreshing) {
    return new Promise<string | null>((resolve) => {
      pendingRequests.push((token) => resolve(token))
    })
  }
  isRefreshing = true
  try {
    const token = await authStore.refreshToken()
    flushPending(token)
    return token
  } catch {
    await handleAuthExpired(authStore)
    return null
  } finally {
    isRefreshing = false
  }
}

// ---------- 请求拦截：预检 + 注入 ----------
client.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  if (config.skipAuth) return config
  const authStore = useAuthStore()
  const token = await ensureFreshToken(authStore)
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ---------- 响应拦截：401 刷新 + 错误 toast ----------
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as InternalAxiosRequestConfig | undefined
    const authStore = useAuthStore()

    if (error.response?.status === 401 && originalRequest && !originalRequest.skipAuth) {
      // 已经重试过仍 401 ⇒ 刷新后的 Token 也无效，立即登出，防止死循环
      if (originalRequest._retry) {
        await handleAuthExpired(authStore)
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingRequests.push((token) => {
            if (!token) {
              reject(error)
              return
            }
            originalRequest._retry = true
            originalRequest.headers = originalRequest.headers ?? {}
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(client(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const newToken = await authStore.refreshToken()
        flushPending(newToken)
        originalRequest.headers = originalRequest.headers ?? {}
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return await client(originalRequest)
      } catch (refreshErr) {
        await handleAuthExpired(authStore)
        return Promise.reject(refreshErr)
      } finally {
        isRefreshing = false
      }
    }

    if (!originalRequest?.silent) {
      showErrorToast(error)
      if (isCreditLimitError(error) && typeof window !== 'undefined') {
        const target = creditLimitRedirectUrl(error)
        const current = `${window.location.pathname}${window.location.search}`
        if (!current.startsWith('/recharge')) {
          window.setTimeout(() => {
            window.location.assign(target)
          }, 300)
        }
      }
    }
    return Promise.reject(error)
  }
)

/**
 * 带去重的请求封装。相同 dedupeKey 的并发调用共享同一个 Promise，结束后清理。
 * 调用方式同 axios，但多支持 config.dedupeKey。
 */
export function request<T = any>(config: AxiosRequestConfig): Promise<AxiosResponse<T>> {
  const key = config.dedupeKey
  if (!key) {
    return client.request<T>(config)
  }
  const existing = inflight.get(key) as Promise<AxiosResponse<T>> | undefined
  if (existing) return existing

  const promise = client.request<T>(config).finally(() => {
    inflight.delete(key)
  })
  inflight.set(key, promise)
  return promise
}

/**
 * 可取消请求工厂。返回 [promise, abort] — 组件 onUnmounted 时 abort() 避免 setState on unmounted。
 *
 * const [req, abort] = cancellable({ url: '/tasks' })
 * onUnmounted(() => abort())
 */
export function cancellable<T = any>(
  config: AxiosRequestConfig
): [Promise<AxiosResponse<T>>, () => void] {
  const controller = new AbortController()
  const promise = client.request<T>({ ...config, signal: controller.signal })
  return [promise, () => controller.abort()]
}

export default client
