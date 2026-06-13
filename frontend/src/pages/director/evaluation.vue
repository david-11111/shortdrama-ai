<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getEvaluationStandard } from '@/api/director'
import { getProjectLogs } from '@/api/workbench'

const standard = ref<any>(null)
const projectId = ref('')
const logs = ref<any[]>([])
const loading = ref(false)

onMounted(async () => {
  const { data } = await getEvaluationStandard()
  standard.value = data
})

async function loadLogs() {
  if (!projectId.value.trim()) return
  loading.value = true
  try {
    const { data } = await getProjectLogs(projectId.value.trim())
    logs.value = data?.logs || data || []
  } finally {
    loading.value = false
  }
}

function summarize(log: any): string {
  return log?.event || log?.type || log?.stage_text || 'unknown'
}
</script>

<template>
  <div class="evaluation-page">
    <header class="header">
      <div>
        <p class="kicker">Director Evaluation</p>
        <h1>闭环评测</h1>
      </div>
    </header>

    <div class="layout">
      <section class="card">
        <h2>评测标准</h2>
        <pre v-if="standard">{{ JSON.stringify(standard, null, 2) }}</pre>
        <div v-else class="empty">加载中...</div>
      </section>

      <section class="card">
        <h2>生成链路日志</h2>
        <div class="query-row">
          <input v-model.trim="projectId" placeholder="输入 project_id" @keyup.enter="loadLogs" />
          <button type="button" class="btn" :disabled="loading" @click="loadLogs">
            {{ loading ? '查询中...' : '查询' }}
          </button>
        </div>

        <div v-if="!logs.length" class="empty">输入项目 ID 查询日志</div>
        <div v-else class="log-list">
          <article v-for="(log, i) in logs" :key="i" class="log-item">
            <time>{{ log.timestamp || log.created_at || '-' }}</time>
            <strong>{{ summarize(log) }}</strong>
            <pre v-if="log.detail || log.payload">{{ JSON.stringify(log.detail || log.payload, null, 2) }}</pre>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.evaluation-page {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.25rem;
}

.header h1 {
  margin: 0;
  font-size: 1.7rem;
}

.kicker {
  margin: 0 0 4px;
  font-size: 0.75rem;
  color: var(--color-primary);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.layout {
  margin-top: 0.95rem;
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 1rem;
}

.card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  padding: 0.9rem;
  box-shadow: var(--shadow-card);
}

.card h2 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
}

pre {
  margin: 0;
  white-space: pre-wrap;
  max-height: 62vh;
  overflow: auto;
  font-size: 12px;
  color: var(--color-text-secondary);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  padding: 0.65rem;
}

.query-row {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.7rem;
}

.query-row input {
  flex: 1;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  padding: 0 0.65rem;
  height: 34px;
}

.query-row input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.btn {
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 0 0.8rem;
  cursor: pointer;
  background: var(--color-bg-secondary);
  color: var(--color-text);
}

.btn:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-primary) 60%, var(--color-border));
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.log-list {
  display: grid;
  gap: 0.6rem;
}

.log-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  padding: 0.6rem;
}

.log-item time {
  display: block;
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}

.log-item strong {
  display: block;
  margin-top: 0.2rem;
  font-size: 0.85rem;
  color: var(--color-text);
}

.log-item pre {
  margin-top: 0.45rem;
}

.empty {
  color: var(--color-text-secondary);
  text-align: center;
  font-size: 0.84rem;
  padding: 1.2rem 0.2rem;
}

@media (max-width: 980px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
