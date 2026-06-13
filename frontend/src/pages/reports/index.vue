<template>
  <div class="reports-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Reports</p>
        <h1>用量报表</h1>
        <p class="page-subtitle">查看任务用量汇总与积分流水明细。</p>
      </div>
    </header>

    <section class="stats-grid" aria-label="用量汇总">
      <article class="stat-card">
        <span class="stat-label">任务总数</span>
        <strong class="stat-value">{{ summary.total_tasks }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">成功率</span>
        <strong class="stat-value">{{ successRate }}%</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">总消耗积分</span>
        <strong class="stat-value">{{ summary.total_credits_spent }}</strong>
      </article>
    </section>

    <section class="history-section">
      <div class="section-header">
        <h2>积分流水</h2>
      </div>

      <div v-if="historyLoading" class="state-block">加载中...</div>
      <div v-else-if="history.length === 0" class="state-block">暂无记录</div>
      <table v-else class="history-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>变动</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in history" :key="item.id">
            <td>{{ formatTime(item.created_at) }}</td>
            <td>{{ item.type }}</td>
            <td :class="item.amount > 0 ? 'amount-positive' : 'amount-negative'">
              {{ item.amount > 0 ? '+' : '' }}{{ item.amount }}
            </td>
            <td>{{ item.note || '-' }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="totalPages > 1" class="pagination">
        <button :disabled="currentPage <= 1" @click="changePage(currentPage - 1)">上一页</button>
        <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
        <button :disabled="currentPage >= totalPages" @click="changePage(currentPage + 1)">下一页</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { reportsApi } from '@/api/reports'

interface UsageSummary {
  total_tasks: number
  success_count: number
  total_credits_spent: number
}

interface CreditRecord {
  id: string
  created_at: string
  type: string
  amount: number
  note?: string
}

const summary = ref<UsageSummary>({
  total_tasks: 0,
  success_count: 0,
  total_credits_spent: 0,
})

const history = ref<CreditRecord[]>([])
const historyLoading = ref(false)
const currentPage = ref(1)
const totalPages = ref(1)
const pageSize = 20

const successRate = computed(() => {
  if (summary.value.total_tasks === 0) return 0
  return ((summary.value.success_count / summary.value.total_tasks) * 100).toFixed(1)
})

onMounted(async () => {
  await Promise.all([fetchSummary(), fetchHistory(1)])
})

async function fetchSummary() {
  try {
    const { data } = await reportsApi.getSummary()
    summary.value = data
  } catch {
    // keep defaults
  }
}

async function fetchHistory(page: number) {
  historyLoading.value = true
  try {
    const { data } = await reportsApi.getCreditsHistory(page, pageSize)
    history.value = data.items || data.results || []
    totalPages.value = data.total_pages || Math.ceil((data.total || 0) / pageSize) || 1
    currentPage.value = page
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

function changePage(page: number) {
  if (page < 1 || page > totalPages.value) return
  fetchHistory(page)
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
.reports-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-xl);
}

.page-header {
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-md);
  margin-bottom: var(--space-xl);
}

.stat-card {
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--color-primary) 5%, var(--color-bg)), var(--color-bg));
}

.stat-label {
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.stat-value {
  display: block;
  margin-top: var(--space-sm);
  font-size: 2rem;
  line-height: 1.1;
}

.history-section {
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.section-header {
  margin-bottom: var(--space-lg);
}

.section-header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.history-table {
  width: 100%;
  border-collapse: collapse;
}

.history-table th,
.history-table td {
  padding: var(--space-sm) var(--space-md);
  text-align: left;
  border-bottom: 1px solid var(--color-border);
  font-size: 0.875rem;
}

.history-table th {
  color: var(--color-text-secondary);
  font-weight: 600;
}

.amount-positive {
  color: #059669;
  font-weight: 600;
}

.amount-negative {
  color: var(--color-error);
  font-weight: 600;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  margin-top: var(--space-lg);
}

.pagination button {
  padding: var(--space-xs) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  cursor: pointer;
  font-size: 0.875rem;
}

.pagination button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.state-block {
  padding: var(--space-xl);
  text-align: center;
  color: var(--color-text-secondary);
}

@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .reports-page {
    padding: var(--space-md);
  }

  .history-table th,
  .history-table td {
    padding: var(--space-xs) var(--space-sm);
    font-size: 0.75rem;
  }
}
</style>
