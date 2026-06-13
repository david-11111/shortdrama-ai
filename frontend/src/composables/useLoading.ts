import { ref } from 'vue'

/**
 * 通用 loading 状态管理。
 */
export function useLoading() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    loading.value = true
    error.value = null
    try {
      return await fn()
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || 'Unknown error'
      return undefined
    } finally {
      loading.value = false
    }
  }

  return { loading, error, run }
}
