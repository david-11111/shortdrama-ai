/**
 * 轻量 toast 插件 — 无第三方依赖。
 *
 * 安装后：
 * - Composition API: `const toast = useToast()`，调用 `toast.success('...')`
 * - 选项式 API：`this.$toast.error('...')`
 * - 对外从 api/client.ts 的错误拦截器接收 AxiosError，统一展示 `detail` 字段
 *
 * 替代各页面散落的 alert()。所有页面共用一个挂载在 body 的容器。
 */
import { reactive, createApp, h, defineComponent, type App } from 'vue'
import { setErrorToastHandler } from '@/api/errorToast'

export type ToastLevel = 'info' | 'success' | 'warning' | 'error'

interface ToastItem {
  id: number
  level: ToastLevel
  message: string
}

interface ToastState {
  items: ToastItem[]
}

const state = reactive<ToastState>({ items: [] })
let nextId = 1

function push(level: ToastLevel, message: string, durationMs = 3500): number {
  const id = nextId++
  state.items.push({ id, level, message })
  if (durationMs > 0) {
    setTimeout(() => dismiss(id), durationMs)
  }
  return id
}

function dismiss(id: number): void {
  const idx = state.items.findIndex((t) => t.id === id)
  if (idx >= 0) state.items.splice(idx, 1)
}

export const toast = {
  info: (m: string, d?: number) => push('info', m, d),
  success: (m: string, d?: number) => push('success', m, d),
  warning: (m: string, d?: number) => push('warning', m, d),
  error: (m: string, d?: number) => push('error', m, d),
  dismiss,
}

export function useToast() {
  return toast
}

const ToastContainer = defineComponent({
  name: 'ToastContainer',
  setup() {
    return () =>
      h(
        'div',
        { class: 'toast-container', role: 'status', 'aria-live': 'polite' },
        state.items.map((item) =>
          h(
            'div',
            {
              key: item.id,
              class: ['toast', `toast--${item.level}`],
              onClick: () => dismiss(item.id),
            },
            item.message
          )
        )
      )
  },
})

const TOAST_STYLE = `
.toast-container {
  position: fixed;
  top: 24px;
  right: 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 9999;
  pointer-events: none;
}
.toast {
  min-width: 240px;
  max-width: 420px;
  padding: 10px 14px;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
  line-height: 1.4;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  cursor: pointer;
  pointer-events: auto;
  word-break: break-word;
}
.toast--info    { background: #3b82f6; }
.toast--success { background: #10b981; }
.toast--warning { background: #f59e0b; }
.toast--error   { background: #ef4444; }
`

function mountContainer(): void {
  if (document.getElementById('toast-container-root')) return
  if (!document.getElementById('toast-style')) {
    const style = document.createElement('style')
    style.id = 'toast-style'
    style.appendChild(document.createTextNode(TOAST_STYLE))
    document.head.appendChild(style)
  }
  const host = document.createElement('div')
  host.id = 'toast-container-root'
  document.body.appendChild(host)
  createApp(ToastContainer).mount(host)
}

export default {
  install(app: App): void {
    mountContainer()
    app.config.globalProperties.$toast = toast
    app.provide('toast', toast)

    // 接管 api/client.ts 的错误展示（message 已由 errorToast 统一计算）
    setErrorToastHandler((_error, message) => {
      toast.error(message)
    })
  },
}

declare module 'vue' {
  interface ComponentCustomProperties {
    $toast: typeof toast
  }
}
