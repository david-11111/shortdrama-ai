import { ref } from 'vue'

/**
 * 幂等按钮 / 幂等动作 composable。
 *
 * 场景：批量生成按钮狂点、收藏、点赞等希望只执行一次的用户动作。
 *
 * 用法：
 *   const { pending, run } = useIdempotent()
 *   <button :disabled="pending" @click="run(() => api.startBatch(...))">生成</button>
 *
 * 特点：
 * - 进行中再次 run 直接复用同一个 Promise，不会重复发起
 * - 结束后自动释放，可再次点击
 * - 与 client.ts 的 dedupeKey 互补：这里防 UI 层重复触发，dedupeKey 防 HTTP 层并发
 */
export function useIdempotent<T = unknown>() {
  const pending = ref(false)
  let current: Promise<T> | null = null

  async function run(task: () => Promise<T>): Promise<T> {
    if (current) return current
    pending.value = true
    current = task().finally(() => {
      pending.value = false
      current = null
    })
    return current
  }

  return { pending, run }
}
