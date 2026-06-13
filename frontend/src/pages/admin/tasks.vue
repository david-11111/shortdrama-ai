<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Tasks</p>
        <h1>任务监控</h1>
      </div>
    </header>

    <section class="stats-grid">
      <article v-for="item in stats" :key="item.task_type" class="stat-card">
        <span class="stat-label">{{ item.task_type }}</span>
        <strong class="stat-value">{{ successRate(item) }}%</strong>
        <span class="stat-note">平均 {{ item.avg_duration_seconds ?? 0 }}s / 活跃 {{ item.active }}</span>
      </article>
    </section>

    <section class="toolbar">
      <select v-model="status" class="input" @change="applyFilters">
        <option value="">全部状态</option>
        <option value="queued">queued</option>
        <option value="running">running</option>
        <option value="done">done</option>
        <option value="failed">failed</option>
        <option value="dead_letter">dead_letter</option>
      </select>
      <select v-model="taskType" class="input" @change="applyFilters">
        <option value="">全部类型</option>
        <option value="video_gen">video_gen</option>
        <option value="image_gen">image_gen</option>
        <option value="text_gen">text_gen</option>
        <option value="tts">tts</option>
      </select>
      <input v-model.trim="userId" class="input" type="number" min="1" placeholder="用户 ID" @keyup.enter="applyFilters" />
      <button class="btn-primary" type="button" @click="applyFilters">查询</button>
    </section>

    <div v-if="errorMessage" class="feedback error">{{ errorMessage }}</div>

    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户</th>
            <th>类型</th>
            <th>状态</th>
            <th>进度</th>
            <th>耗时</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="7" class="state-cell">加载中...</td>
          </tr>
          <tr v-else-if="tasks.length === 0">
            <td colspan="7" class="state-cell">暂无数据</td>
          </tr>
          <tr v-for="task in tasks" :key="task.task_id">
            <td>
              <div class="cell-main">{{ shortId(task.task_id) }}</div>
              <div class="cell-sub">{{ task.retry_count ? `重试 ${task.retry_count}` : task.stage_text || '-' }}</div>
            </td>
            <td>{{ task.user_email }}</td>
            <td>{{ task.task_type }}</td>
            <td>
              <span class="status-badge" :class="`status-${task.status}`">{{ task.status }}</span>
            </td>
            <td>
              <div class="progress-bar">
                <div class="progress-fill" :style="{ width: `${task.progress}%` }"></div>
              </div>
              <span class="cell-sub">{{ task.progress }}%</span>
            </td>
            <td>{{ duration(task) }}</td>
            <td>{{ formatTime(task.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pagination">
      <button class="btn-secondary" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button class="btn-secondary" type="button" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { adminApi, type AdminTaskRow, type AdminTaskStat } from '@/api/admin'

const tasks = ref<AdminTaskRow[]>([])
const stats = ref<AdminTaskStat[]>([])
const loading = ref(false)
const errorMessage = ref('')
const page = ref(1)
const total = ref(0)
const pageSize = 20
const status = ref('')
const taskType = ref('')
const userId = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

onMounted(async () => {
  await Promise.all([loadTasks(), loadStats()])
})

async function loadTasks() {
  loading.value = true
  errorMessage.value = ''

  try {
    const { data } = await adminApi.tasks({
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined,
      task_type: taskType.value || undefined,
      user_id: userId.value ? Number(userId.value) : undefined,
    })
    tasks.value = data.tasks
    total.value = data.total
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载任务失败'
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const { data } = await adminApi.taskStats()
    stats.value = data.stats
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载统计失败'
  }
}

function applyFilters() {
  page.value = 1
  void loadTasks()
}

function goPage(nextPage: number) {
  page.value = nextPage
  void loadTasks()
}

function successRate(item: AdminTaskStat) {
  if (!item.total) return 0
  return Math.round((item.succeeded / item.total) * 100)
}

function shortId(value: string) {
  return `${value.slice(0, 8)}...`
}

function duration(task: AdminTaskRow) {
  if (!task.started_at) return '-'
  const start = new Date(task.started_at).getTime()
  const end = task.completed_at ? new Date(task.completed_at).getTime() : Date.now()
  return `${Math.max(0, Math.round((end - start) / 1000))}s`
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.page-header {
  margin-bottom: 20px;
}

.page-kicker {
  margin: 0 0 8px;
  color: #3156d3;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

h1 {
  margin: 0;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  padding: 20px;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
}

.stat-label,
.stat-note,
.cell-sub {
  color: #64748b;
}

.stat-value {
  display: block;
  margin: 8px 0;
  font-size: 1.6rem;
}

.toolbar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.input {
  padding: 10px 12px;
  border: 1px solid #dbe2f0;
  border-radius: 12px;
  background: #fff;
}

.btn-primary,
.btn-secondary {
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid transparent;
  cursor: pointer;
}

.btn-primary {
  background: #3156d3;
  color: #fff;
}

.btn-secondary {
  background: #fff;
  border-color: #dbe2f0;
  color: #475569;
}

.feedback.error {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fef3f2;
  color: #b42318;
}

.table-wrap {
  overflow-x: auto;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
}

.table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 14px 16px;
  border-bottom: 1px solid #e5e7eb;
  text-align: left;
  vertical-align: top;
}

.table tbody tr:last-child td {
  border-bottom: none;
}

.cell-main {
  font-weight: 600;
}

.progress-bar {
  width: 120px;
  height: 6px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
  margin-bottom: 6px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3156d3, #6183ff);
}

.status-badge {
  display: inline-flex;
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

.state-cell {
  text-align: center;
  color: #64748b;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

@media (max-width: 960px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
