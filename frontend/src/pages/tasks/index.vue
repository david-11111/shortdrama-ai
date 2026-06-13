<template>
  <div class="tasks-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Live Queue</p>
        <h1>任务列表</h1>
        <p class="page-subtitle">按状态筛选任务，并实时查看执行中的进度变化。</p>
      </div>

      <div class="header-actions">
        <router-link to="/tasks/submit-video" class="btn-back">生成视频</router-link>
        <router-link to="/tasks/submit-image" class="btn-back">生成图片</router-link>
        <router-link to="/" class="btn-back">返回仪表盘</router-link>
      </div>
    </header>

    <div v-if="toastMessage" class="toast" role="status">{{ toastMessage }}</div>

    <section class="filters" aria-label="任务筛选">
      <button
        v-for="statusOption in statuses"
        :key="statusOption.value ?? 'all'"
        class="filter-btn"
        :class="{ active: currentStatus === statusOption.value }"
        type="button"
        @click="filterByStatus(statusOption.value)"
      >
        {{ statusOption.label }}
      </button>
    </section>

    <div v-if="tasksStore.loading" class="state-block">加载中...</div>
    <div v-else-if="tasksStore.tasks.length === 0" class="state-block">暂无任务</div>
    <div v-else class="task-list">
      <article v-for="task in tasksStore.tasks" :key="task.task_id" class="task-card">
        <div class="task-card-header">
          <div>
            <div class="task-type">{{ task.task_type }}</div>
            <div class="task-id">{{ task.task_id }}</div>
          </div>
          <span class="task-status" :class="`status-${task.status}`">{{ task.status }}</span>
        </div>

        <div class="task-card-body">
          <div v-if="task.status === 'running' || task.status === 'queued'" class="progress-section">
            <div class="progress-bar" aria-hidden="true">
              <div class="progress-fill" :style="{ width: `${task.progress}%` }"></div>
            </div>
            <span>{{ task.stage_text || `${task.progress}%` }}</span>
          </div>

          <div v-if="task.error_message" class="error-msg">{{ task.error_message }}</div>

          <div class="task-meta">
            <span>创建: {{ formatTime(task.created_at) }}</span>
            <span v-if="task.completed_at">完成: {{ formatTime(task.completed_at) }}</span>
          </div>
        </div>

        <div v-if="task.status === 'queued' || task.status === 'pending'" class="task-card-actions">
          <button class="btn-cancel" type="button" :disabled="cancelingId === task.task_id" @click="cancelTask(task.task_id)">
            {{ cancelingId === task.task_id ? '取消中...' : '取消任务' }}
          </button>
          <router-link :to="`/tasks/${task.task_id}`" class="btn-detail">查看详情</router-link>
        </div>

        <div v-else class="task-card-actions">
          <router-link :to="`/tasks/${task.task_id}`" class="btn-detail">查看详情</router-link>
        </div>
      </article>
    </div>

    <div v-if="tasksStore.total > pageSize" class="pagination">
      <button type="button" :disabled="page <= 1 || tasksStore.loading" @click="goPage(page - 1)">上一页</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button type="button" :disabled="page >= totalPages || tasksStore.loading" @click="goPage(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { tasksApi } from '@/api/tasks'
import { useWebSocket } from '@/composables/useWebSocket'
import { useTasksStore } from '@/stores/tasks'

type TaskStatusFilter = 'queued' | 'running' | 'done' | 'failed' | undefined

interface TaskUpdateMessage {
  type: string
  task_id: string
  status: 'pending' | 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  progress: number
  stage_text?: string | null
  result?: Record<string, unknown> | null
  error?: string
}

const tasksStore = useTasksStore()
const { connected, connect, disconnect, on, subscribe, unsubscribe } = useWebSocket()

const page = ref(1)
const pageSize = 20
const currentStatus = ref<TaskStatusFilter>(undefined)
const cancelingId = ref<string | null>(null)
const toastMessage = ref('')

let toastTimer: ReturnType<typeof setTimeout> | null = null
let subscribedTaskIds = new Set<string>()

const totalPages = computed(() => Math.max(1, Math.ceil(tasksStore.total / pageSize)))

const statuses: Array<{ label: string; value: TaskStatusFilter }> = [
  { label: '全部', value: undefined },
  { label: '排队中', value: 'queued' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'done' },
  { label: '失败', value: 'failed' },
]

function handleTaskUpdate(msg: TaskUpdateMessage) {
  tasksStore.updateTaskFromWs(msg.task_id, {
    status: msg.status,
    progress: msg.progress,
    stage_text: msg.stage_text ?? null,
  })
  syncTaskSubscriptions()
}

function handleTaskComplete(msg: TaskUpdateMessage) {
  tasksStore.updateTaskFromWs(msg.task_id, {
    status: 'done',
    progress: 100,
    result: msg.result ?? null,
    completed_at: new Date().toISOString(),
  })
  syncTaskSubscriptions()
}

function handleTaskFailed(msg: TaskUpdateMessage) {
  tasksStore.updateTaskFromWs(msg.task_id, {
    status: 'failed',
    error_message: msg.error ?? '任务执行失败',
  })
  syncTaskSubscriptions()
}

onMounted(async () => {
  await loadTasks()

  const flash = sessionStorage.getItem('tasks_toast')
  if (flash) {
    toastMessage.value = flash
    sessionStorage.removeItem('tasks_toast')
    toastTimer = setTimeout(() => {
      toastMessage.value = ''
      toastTimer = null
    }, 3000)
  }

  connect()
  on('task_update', handleTaskUpdate)
  on('task_complete', handleTaskComplete)
  on('task_failed', handleTaskFailed)

  syncTaskSubscriptions()
})

onUnmounted(() => {
  if (toastTimer) clearTimeout(toastTimer)
  if (subscribedTaskIds.size > 0) {
    unsubscribe([...subscribedTaskIds])
    subscribedTaskIds.clear()
  }
  disconnect()
})

watch(connected, (isConnected) => {
  if (isConnected && subscribedTaskIds.size > 0) {
    subscribe([...subscribedTaskIds])
  }
})

async function loadTasks() {
  await tasksStore.fetchTasks({
    status: currentStatus.value,
    page: page.value,
  })
}

function syncTaskSubscriptions() {
  const nextIds = new Set(
    tasksStore.tasks
    .filter((task) => task.status === 'running' || task.status === 'queued')
    .map((task) => task.task_id),
  )

  const toUnsubscribe = [...subscribedTaskIds].filter((id) => !nextIds.has(id))
  const toSubscribe = [...nextIds].filter((id) => !subscribedTaskIds.has(id))

  if (toUnsubscribe.length > 0) {
    unsubscribe(toUnsubscribe)
  }
  if (toSubscribe.length > 0) {
    subscribe(toSubscribe)
  }

  subscribedTaskIds = nextIds
}

function filterByStatus(status: TaskStatusFilter) {
  currentStatus.value = status
  page.value = 1
  void loadTasks().then(() => {
    syncTaskSubscriptions()
  })
}

function goPage(nextPage: number) {
  page.value = nextPage
  void loadTasks().then(() => {
    syncTaskSubscriptions()
  })
}

async function cancelTask(taskId: string) {
  const confirmed = window.confirm('确定取消该任务吗？')
  if (!confirmed) return

  cancelingId.value = taskId

  try {
    await tasksApi.cancel(taskId)
    await loadTasks()
    syncTaskSubscriptions()
  } finally {
    cancelingId.value = null
  }
}

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
.tasks-page {
  max-width: 1100px;
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

.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  justify-content: flex-end;
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
  color: var(--color-text-secondary);
  background: var(--color-bg);
}

.toast {
  margin-bottom: var(--space-lg);
  padding: var(--space-md);
  border: 1px solid color-mix(in srgb, var(--color-primary) 30%, var(--color-border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-primary) 10%, var(--color-bg));
  color: var(--color-text);
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-lg);
}

.filter-btn {
  padding: var(--space-xs) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-bg);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background-color 0.2s ease;
}

.filter-btn.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 10%, var(--color-bg));
}

.task-list {
  display: grid;
  gap: var(--space-md);
}

.task-card {
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.task-card-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  align-items: flex-start;
  margin-bottom: var(--space-md);
}

.task-type {
  font-weight: 700;
}

.task-id {
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 0.75rem;
  word-break: break-all;
}

.task-status {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
}

.status-done {
  background: #d1fae5;
  color: #065f46;
}

.status-running {
  background: #dbeafe;
  color: #1e40af;
}

.status-queued {
  background: #fef3c7;
  color: #92400e;
}

.status-failed {
  background: #fee2e2;
  color: #991b1b;
}

.status-pending,
.status-cancelled {
  background: #f3f4f6;
  color: #4b5563;
}

.status-retrying {
  background: #fef3c7;
  color: #92400e;
}

.status-dead_letter {
  background: #fee2e2;
  color: #991b1b;
}

.progress-section {
  display: grid;
  gap: var(--space-xs);
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

.progress-section span {
  color: var(--color-text-secondary);
  font-size: 0.75rem;
}

.error-msg {
  color: var(--color-error);
  font-size: 0.875rem;
  margin-bottom: var(--space-sm);
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-md);
  color: var(--color-text-secondary);
  font-size: 0.75rem;
}

.task-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-top: var(--space-md);
}

.btn-cancel {
  padding: 6px 12px;
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-error);
  cursor: pointer;
}

.btn-cancel:hover:not(:disabled) {
  background: #fee2e2;
}

.btn-cancel:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-detail {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  background: var(--color-bg);
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--space-md);
  margin-top: var(--space-lg);
}

.pagination button {
  padding: var(--space-xs) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  cursor: pointer;
}

.pagination button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.state-block {
  padding: var(--space-xl);
  text-align: center;
  color: var(--color-text-secondary);
}

@media (max-width: 720px) {
  .tasks-page {
    padding: var(--space-md);
  }

  .page-header,
  .task-card-header {
    flex-direction: column;
  }

  .header-actions {
    width: 100%;
    justify-content: stretch;
  }

  .btn-back {
    width: 100%;
  }

  .btn-detail {
    width: 100%;
  }
}
</style>
