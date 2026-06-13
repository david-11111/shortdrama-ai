import { computed, ref } from 'vue'
import { getAgentRunSnapshot, type AgentRunSnapshot } from '@/api/director'

const SNAPSHOT_LIMITS = {
  event_limit: 300,
  task_limit: 300,
  artifact_limit: 120,
  evidence_item_limit: 80,
  stream_limit: 200,
}

export function useAgentRunSnapshot() {
  const snapshot = ref<AgentRunSnapshot | null>(null)
  const loading = ref(false)
  const error = ref('')

  const run = computed(() => snapshot.value?.run ?? null)
  const projectId = computed(() => snapshot.value?.run.project_id || '')
  const nodes = computed(() => snapshot.value?.nodes ?? [])
  const artifacts = computed(() => snapshot.value?.artifacts ?? [])
  const budget = computed(() => snapshot.value?.budget ?? null)

  async function load(runId: string) {
    if (!runId) return
    loading.value = true
    error.value = ''
    try {
      const { data } = await getAgentRunSnapshot(runId, SNAPSHOT_LIMITS)
      snapshot.value = data
    } catch (err: any) {
      error.value = err?.response?.data?.detail || err?.message || '加载 Agent Run 失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    snapshot,
    loading,
    error,
    run,
    projectId,
    nodes,
    artifacts,
    budget,
    load,
  }
}
