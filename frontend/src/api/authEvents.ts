/**
 * Auth 事件总线 — 解耦 api/client 与路由/UI。
 *
 * 刷新 Token 失败后 client.ts 调 emitAuthExpired()；
 * main.ts 在启动时注册一个 listener，负责 router.push('/login')。
 */
type AuthExpiredListener = () => void

const listeners = new Set<AuthExpiredListener>()

export function onAuthExpired(listener: AuthExpiredListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function emitAuthExpired(): void {
  listeners.forEach((fn) => {
    try {
      fn()
    } catch {
      // ignore listener failure
    }
  })
}
