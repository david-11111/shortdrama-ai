import { reactive } from 'vue'

/**
 * 异步 confirm — 替代 window.confirm。
 *
 * 用法：
 *   const ok = await confirm('确定删除这个资产吗？')
 *   if (!ok) return
 *
 *   const ok = await confirm({
 *     title: '撤销 API Key',
 *     message: '此操作不可恢复。',
 *     okText: '撤销',
 *     danger: true,
 *   })
 *
 * 组件依赖 components/common/ConfirmDialog.vue 挂载在页面中（App.vue 全局挂一次）。
 */
export interface ConfirmOptions {
  title?: string
  message: string
  okText?: string
  cancelText?: string
  danger?: boolean
}

export interface ConfirmItem extends ConfirmOptions {
  id: number
  resolve: (ok: boolean) => void
}

export const confirmQueue = reactive<ConfirmItem[]>([])
let nextId = 1

export function confirm(arg: string | ConfirmOptions): Promise<boolean> {
  const opts: ConfirmOptions = typeof arg === 'string' ? { message: arg } : arg
  return new Promise<boolean>((resolvePromise) => {
    const id = nextId++
    const item: ConfirmItem = {
      id,
      ...opts,
      resolve: (ok) => {
        const idx = confirmQueue.findIndex((c) => c.id === id)
        if (idx >= 0) confirmQueue.splice(idx, 1)
        resolvePromise(ok)
      },
    }
    confirmQueue.push(item)
  })
}

export function useConfirm() {
  return confirm
}
