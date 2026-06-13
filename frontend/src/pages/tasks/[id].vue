<template>
  <div class="task-detail-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Task Detail</p>
        <h1>任务详情</h1>
        <p class="page-subtitle">查看单个任务的进度、结果和失败原因。</p>
      </div>
      <router-link to="/tasks" class="btn-back">返回任务列表</router-link>
    </header>

    <section v-if="loading" class="state-card">加载中...</section>
    <section v-else-if="errorMessage" class="state-card error-state">{{ errorMessage }}</section>
    <section v-else-if="task" class="detail-card">
      <div class="detail-top">
        <div>
          <div class="task-type">{{ task.task_type }}</div>
          <div class="task-id">{{ task.task_id }}</div>
        </div>
        <span class="task-status" :class="`status-${task.status}`">{{ task.status }}</span>
      </div>

      <div class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">创建时间</span>
          <span class="meta-value">{{ formatTime(task.created_at) }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">开始时间</span>
          <span class="meta-value">{{ task.started_at ? formatTime(task.started_at) : '未开始' }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">完成时间</span>
          <span class="meta-value">{{ task.completed_at ? formatTime(task.completed_at) : '进行中' }}</span>
        </div>
      </div>

      <section class="progress-panel">
        <div class="progress-head">
          <span>当前进度</span>
          <strong>{{ task.progress }}%</strong>
        </div>
        <div class="progress-bar" aria-hidden="true">
          <div class="progress-fill" :style="{ width: `${task.progress}%` }"></div>
        </div>
        <p class="stage-text">{{ task.stage_text || stageFallback }}</p>
      </section>

      <section v-if="resultUrls.length > 0" class="result-panel">
        <h2>任务结果</h2>
        <div class="result-list">
          <a
            v-for="url in resultUrls"
            :key="url"
            :href="url"
            class="result-link"
            target="_blank"
            rel="noreferrer"
          >
            {{ url }}
          </a>
        </div>
      </section>

      <section v-if="task.error_message || task.status === 'failed' || task.status === 'dead_letter'" class="error-panel">
        <h2>失败信息</h2>
        <p>{{ task.error_message || '任务执行失败' }}</p>
        <p class="refund-text">退还积分: {{ refundedLabel }}</p>
      </section>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { tasksApi } from '@/api/tasks'
import { useWebSocket } from '@/composables/useWebSocket'
import type { Task } from '@/types/api'

interface TaskUpdateMessage {
  type: string
  task_id: string
  status: Task['status']
  progress?: number
  stage_text?: string | null
  result?: Record<string, unknown> | null
  error?: string
  credits_refunded?: number
}

const route = useRoute()
const { connect, disconnect, on, subscribe } = useWebSocket()

const task = ref<Task | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const creditsRefunded = ref<number | null>(null)

const taskId = computed(() => String(route.params.id ?? ''))

const stageFallback = computed(() => {
  if (!task.value) return ''
  if (task.value.status === 'queued') return '任务已进入队列，等待处理'
  if (task.value.status === 'done') return '任务已完成'
  if (task.value.status === 'failed' || task.value.status === 'dead_letter') return '任务已失败'
  return '任务执行中'
})

const resultUrls = computed(() => {
  const result = task.value?.result
  if (!result) return []

  const values: string[] = []
  const directCandidates = ['url', 'video_url', 'image_url']

  for (const key of directCandidates) {
    const value = result[key]
    if (typeof value === 'string' && value) values.push(value)
  }

  const assets = result.assets
  if (Array.isArray(assets)) {
    assets.forEach((item) => {
      if (typeof item === 'string') values.push(item)
      if (item && typeof item === 'object' && typeof (item as Record<string, unknown>).url === 'string') {
        values.push((item as Record<string, string>).url)
      }
    })
  }

  return Array.from(new Set(values))
})

const refundedLabel = computed(() => {
  if (creditsRefunded.value === null) return '待确认'
  return String(creditsRefunded.value)
})

async function fetchTask() {
  loading.value = true
  errorMessage.value = ''

  try {
    const { data } = await tasksApi.get(taskId.value)
    task.value = data
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载任务详情失败'
  } finally {
    loading.value = false
  }
}

function handleTaskUpdate(message: TaskUpdateMessage) {
  if (!task.value || message.task_id !== task.value.task_id) return

  task.value = {
    ...task.value,
    status: message.status,
    progress: message.progress ?? task.value.progress,
    stage_text: message.stage_text ?? task.value.stage_text,
  }
}

function handleTaskComplete(message: TaskUpdateMessage) {
  if (!task.value || message.task_id !== task.value.task_id) return

  task.value = {
    ...task.value,
    status: 'done',
    progress: 100,
    result: message.result ?? task.value.result,
    completed_at: new Date().toISOString(),
  }
}

function handleTaskFailed(message: TaskUpdateMessage) {
  if (!task.value || message.task_id !== task.value.task_id) return

  task.value = {
    ...task.value,
    status: 'failed',
    error_message: message.error ?? task.value.error_message ?? '任务执行失败',
    completed_at: new Date().toISOString(),
  }
  creditsRefunded.value = message.credits_refunded ?? creditsRefunded.value
}

onMounted(async () => {
  await fetchTask()

  connect()
  on('task_update', handleTaskUpdate)
  on('task_complete', handleTaskComplete)
  on('task_failed', handleTaskFailed)

  if (taskId.value) subscribe([taskId.value])
})

onUnmounted(() => {
  disconnect()
})

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.task-detail-page {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-xl);
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-lg);
  align-items: flex-start;
  margin-bottom: var(--space-lg);
}

.page-kicker {
  margin: 0 0 var(--space-xs);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.page-header h1 {
  margin: 0;
  font-size: 2rem;
}

.page-subtitle {
  margin: var(--space-sm) 0 0;
  color: var(--color-text-secondary);
}

.btn-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text-secondary);
}

.state-card,
.detail-card {
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.error-state {
  color: var(--color-error);
}

.detail-top {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  align-items: flex-start;
  margin-bottom: var(--space-lg);
}

.task-type {
  font-size: 1.25rem;
  font-weight: 700;
}

.task-id {
  margin-top: var(--space-xs);
  color: var(--color-text-secondary);
  font-size: 0.75rem;
  word-break: break-all;
}

.task-status {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
}

.status-done {
  background: #d1fae5;
  color: #065f46;
}

.status-running {
  background: #dbeafe;
  color: #1e40af;
}

.status-queued,
.status-retrying {
  background: #fef3c7;
  color: #92400e;
}

.status-failed,
.status-dead_letter {
  background: #fee2e2;
  color: #991b1b;
}

.status-pending,
.status-cancelled {
  background: #f3f4f6;
  color: #4b5563;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}

.meta-item {
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 60%, var(--color-bg));
}

.meta-label {
  display: block;
  color: var(--color-text-secondary);
  font-size: 0.75rem;
}

.meta-value {
  display: block;
  margin-top: var(--space-xs);
  font-weight: 600;
}

.progress-panel,
.result-panel,
.error-panel {
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 60%, var(--color-bg));
}

.result-panel,
.error-panel {
  margin-top: var(--space-md);
}

.progress-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  margin-bottom: var(--space-sm);
}

.progress-bar {
  height: 8px;
  border-radius: 999px;
  background: var(--color-border);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), var(--color-primary-hover));
  border-radius: inherit;
  transition: width 0.3s ease;
}

.stage-text,
.refund-text {
  margin: var(--space-sm) 0 0;
  color: var(--color-text-secondary);
}

.result-panel h2,
.error-panel h2 {
  margin: 0 0 var(--space-sm);
  font-size: 1rem;
}

.result-list {
  display: grid;
  gap: var(--space-sm);
}

.result-link {
  color: var(--color-primary);
  word-break: break-all;
}

.error-panel p {
  margin: 0;
}

@media (max-width: 720px) {
  .task-detail-page {
    padding: var(--space-md);
  }

  .page-header,
  .detail-top {
    flex-direction: column;
  }

  .btn-back {
    width: 100%;
  }

  .meta-grid {
    grid-template-columns: 1fr;
  }

  .state-card,
  .detail-card {
    padding: var(--space-lg);
  }
}
</style>
