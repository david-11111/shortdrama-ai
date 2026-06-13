<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Overview</p>
        <h1>后台总览</h1>
      </div>
    </header>

    <div v-if="loading" class="state-block">加载中...</div>
    <div v-else-if="errorMessage" class="state-block error-state">{{ errorMessage }}</div>
    <template v-else-if="overview">
      <section class="stats-grid">
        <article class="stat-card">
          <span class="stat-label">用户总数</span>
          <strong class="stat-value">{{ overview.users.total_users }}</strong>
          <span class="stat-note">今日新增 {{ overview.users.new_today }}</span>
        </article>
        <article class="stat-card">
          <span class="stat-label">活跃任务</span>
          <strong class="stat-value">{{ overview.tasks.active_tasks }}</strong>
          <span class="stat-note">今日完成 {{ overview.tasks.completed_today }}</span>
        </article>
        <article class="stat-card">
          <span class="stat-label">今日收入</span>
          <strong class="stat-value">{{ overview.revenue_today }}</strong>
          <span class="stat-note">单位：credits</span>
        </article>
        <article class="stat-card">
          <span class="stat-label">死信数</span>
          <strong class="stat-value">{{ overview.dead_letter_count }}</strong>
          <span class="stat-note">待人工介入</span>
        </article>
      </section>

      <section class="detail-grid">
        <article class="panel">
          <h2>用户概况</h2>
          <div class="metric-list">
            <div class="metric-row">
              <span>活跃用户</span>
              <strong>{{ overview.users.active_users }}</strong>
            </div>
            <div class="metric-row">
              <span>今日新增</span>
              <strong>{{ overview.users.new_today }}</strong>
            </div>
          </div>
        </article>

        <article class="panel">
          <h2>任务概况</h2>
          <div class="metric-list">
            <div class="metric-row">
              <span>今日完成</span>
              <strong>{{ overview.tasks.completed_today }}</strong>
            </div>
            <div class="metric-row">
              <span>今日失败</span>
              <strong>{{ overview.tasks.failed_today }}</strong>
            </div>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { adminApi, type AdminOverviewResponse } from '@/api/admin'

const overview = ref<AdminOverviewResponse | null>(null)
const loading = ref(true)
const errorMessage = ref('')

onMounted(async () => {
  try {
    const { data } = await adminApi.overview()
    overview.value = data
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载总览失败'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page-header {
  margin-bottom: 24px;
}

.page-kicker {
  margin: 0 0 8px;
  color: #3156d3;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 2rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card,
.panel {
  padding: 20px;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
}

.stat-label,
.stat-note {
  color: #64748b;
}

.stat-value {
  display: block;
  margin: 10px 0 6px;
  font-size: 2rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.panel h2 {
  margin: 0 0 16px;
  font-size: 1.1rem;
}

.metric-list {
  display: grid;
  gap: 14px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e5e7eb;
}

.metric-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.state-block {
  padding: 24px;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
  color: #64748b;
}

.error-state {
  color: #b42318;
}

@media (max-width: 960px) {
  .stats-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
