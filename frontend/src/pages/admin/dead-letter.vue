<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Dead Letter</p>
        <h1>死信队列</h1>
      </div>
    </header>

    <section class="toolbar">
      <label class="toggle">
        <input v-model="resolved" type="checkbox" @change="applyFilters" />
        <span>显示已解决</span>
      </label>
    </section>

    <div v-if="errorMessage" class="feedback error">{{ errorMessage }}</div>

    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>任务类型</th>
            <th>用户</th>
            <th>错误信息</th>
            <th>死亡时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="5" class="state-cell">加载中...</td>
          </tr>
          <tr v-else-if="items.length === 0">
            <td colspan="5" class="state-cell">暂无数据</td>
          </tr>
          <tr v-for="item in items" :key="item.id">
            <td>{{ item.task_type }}</td>
            <td>{{ item.user_email }}</td>
            <td>
              <div class="cell-main">{{ formatError(item.error_history) }}</div>
              <div class="cell-sub">原任务 {{ shortId(item.original_task_id) }}</div>
            </td>
            <td>{{ formatTime(item.dead_at) }}</td>
            <td>
              <div class="actions">
                <button class="btn-primary" type="button" :disabled="actingId === item.id" @click="retryItem(item.id)">
                  重试
                </button>
                <button class="btn-secondary" type="button" :disabled="actingId === item.id" @click="resolveItem(item.id)">
                  标记解决
                </button>
              </div>
            </td>
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
import { adminApi, type DeadLetterItem } from '@/api/admin'

const items = ref<DeadLetterItem[]>([])
const loading = ref(false)
const errorMessage = ref('')
const actingId = ref<number | null>(null)
const resolved = ref(false)
const page = ref(1)
const total = ref(0)
const pageSize = 20

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

onMounted(() => {
  void loadItems()
})

async function loadItems() {
  loading.value = true
  errorMessage.value = ''

  try {
    const { data } = await adminApi.deadLetter({
      resolved: resolved.value,
      page: page.value,
      page_size: pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载死信队列失败'
  } finally {
    loading.value = false
  }
}

async function retryItem(itemId: number) {
  const confirmed = window.confirm('确定要重试该死信任务吗？')
  if (!confirmed) return

  actingId.value = itemId
  try {
    await adminApi.retryDeadLetter(itemId)
    await loadItems()
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '重试失败'
  } finally {
    actingId.value = null
  }
}

async function resolveItem(itemId: number) {
  actingId.value = itemId
  try {
    await adminApi.resolveDeadLetter(itemId)
    await loadItems()
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '标记解决失败'
  } finally {
    actingId.value = null
  }
}

function applyFilters() {
  page.value = 1
  void loadItems()
}

function goPage(nextPage: number) {
  page.value = nextPage
  void loadItems()
}

function formatError(value: unknown) {
  if (typeof value === 'string') return value
  if (Array.isArray(value) && value.length > 0) return String(value[value.length - 1])
  return JSON.stringify(value)
}

function shortId(value: string) {
  return `${value.slice(0, 8)}...`
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

.toolbar {
  margin-bottom: 16px;
}

.toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
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
  min-width: 920px;
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

.cell-sub {
  margin-top: 4px;
  color: #64748b;
  font-size: 0.875rem;
}

.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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
</style>
