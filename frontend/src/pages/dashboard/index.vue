<template>
  <div class="dashboard">
    <header class="dashboard-header">
      <div>
        <p class="page-kicker">Overview</p>
        <h1>Dashboard</h1>
        <p class="page-subtitle">查看当前账户状态、额度消耗以及最近任务动态。</p>
      </div>

      <div class="user-panel">
        <div class="user-copy">
          <strong>{{ authStore.user?.display_name || authStore.user?.email }}</strong>
          <span>{{ authStore.user?.email }}</span>
        </div>
        <span class="tier-badge">{{ authStore.user?.tier || 'free' }}</span>
        <router-link v-if="authStore.user?.is_admin" to="/admin" class="btn-text">管理后台</router-link>
        <router-link to="/settings" class="btn-text">设置</router-link>
        <button class="btn-text" type="button" @click="handleLogout">退出</button>
      </div>
    </header>

    <section class="stats-grid" aria-label="账户概览">
      <article class="stat-card">
        <span class="stat-label">积分余额</span>
        <strong class="stat-value">{{ credits.balance }}</strong>
        <span class="stat-note">累计收入 {{ credits.lifetime_earned }}</span>
      </article>

      <article class="stat-card">
        <span class="stat-label">进行中任务</span>
        <strong class="stat-value">{{ runningCount }}</strong>
        <span class="stat-note">含排队与执行中任务</span>
      </article>

      <article class="stat-card">
        <span class="stat-label">已完成任务</span>
        <strong class="stat-value">{{ completedCount }}</strong>
        <span class="stat-note">累计已结束的成功任务</span>
      </article>
    </section>

    <section class="quick-actions">
      <router-link to="/director" class="action-btn">导演链路</router-link>
      <router-link to="/director/flow" class="action-btn">导演制作流</router-link>
      <router-link to="/director/insight" class="action-btn">导演诊断流</router-link>
      <router-link to="/tasks/submit-video" class="action-btn">生成视频</router-link>
      <router-link to="/tasks/submit-image" class="action-btn">生成图片</router-link>
      <router-link to="/tasks/submit-tts" class="action-btn">语音合成</router-link>
      <router-link to="/recharge" class="action-btn action-btn--recharge">充值积分</router-link>
    </section>

    <section class="recent-tasks">
      <div class="section-header">
        <div>
          <h2>最近任务</h2>
          <p>最新 5 条任务执行状态。</p>
        </div>
        <router-link to="/tasks" class="view-all">查看全部</router-link>
      </div>

      <div v-if="tasksStore.loading" class="state-block">加载中...</div>
      <div v-else-if="tasksStore.tasks.length === 0" class="state-block">暂无任务</div>
      <div v-else class="task-list">
        <article v-for="task in recentTasks" :key="task.task_id" class="task-item">
          <div class="task-top">
            <span class="task-type">{{ task.task_type }}</span>
            <span class="task-status" :class="`status-${task.status}`">{{ task.status }}</span>
          </div>

          <div v-if="task.status === 'running' || task.status === 'queued'" class="task-progress">
            <div class="progress-bar" aria-hidden="true">
              <div class="progress-fill" :style="{ width: `${task.progress}%` }"></div>
            </div>
            <span class="progress-text">{{ task.stage_text || `${task.progress}%` }}</span>
          </div>

          <p v-if="task.error_message" class="task-error">{{ task.error_message }}</p>
          <time class="task-time" :datetime="task.created_at">{{ formatTime(task.created_at) }}</time>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useTasksStore } from '@/stores/tasks'

interface CreditsSummary {
  balance: number
  lifetime_earned: number
  lifetime_spent: number
}

const router = useRouter()
const authStore = useAuthStore()
const tasksStore = useTasksStore()

const credits = ref<CreditsSummary>({
  balance: 0,
  lifetime_earned: 0,
  lifetime_spent: 0,
})

const recentTasks = computed(() => tasksStore.tasks.slice(0, 5))
const runningCount = computed(() => tasksStore.tasks.filter((task) => task.status === 'running' || task.status === 'queued').length)
const completedCount = computed(() => tasksStore.tasks.filter((task) => task.status === 'done').length)

onMounted(async () => {
  await tasksStore.fetchTasks({ page: 1 })

  try {
    const { data } = await client.get<CreditsSummary>('/credits')
    credits.value = data
  } catch {
    // Ignore credits request failures and keep dashboard usable.
  }
})

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
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
.dashboard {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-xl);
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-lg);
  align-items: flex-start;
  margin-bottom: var(--space-xl);
}

.page-kicker {
  margin: 0 0 var(--space-xs);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dashboard-header h1 {
  margin: 0;
  font-size: 2rem;
}

.page-subtitle {
  margin: var(--space-sm) 0 0;
  color: var(--color-text-secondary);
}

.user-panel {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.user-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.user-copy span {
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.tier-badge {
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 15%, transparent);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.btn-text {
  border: none;
  background: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 0.875rem;
}

.btn-text:hover {
  color: var(--color-error);
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

.stat-note {
  display: block;
  margin-top: var(--space-sm);
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.recent-tasks {
  padding: var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-md);
  margin-bottom: var(--space-xl);
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 56px;
  padding: var(--space-md);
  border: 1px solid color-mix(in srgb, var(--color-primary) 20%, var(--color-border));
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary) 12%, var(--color-bg)), var(--color-bg));
  color: var(--color-text);
  font-weight: 600;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}

.section-header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.section-header p {
  margin: 6px 0 0;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.view-all {
  color: var(--color-primary);
  font-size: 0.875rem;
  font-weight: 600;
}

.task-list {
  display: grid;
  gap: var(--space-md);
}

.task-item {
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 50%, var(--color-bg));
}

.task-top {
  display: flex;
  justify-content: space-between;
  gap: var(--space-sm);
  align-items: center;
}

.task-type {
  font-weight: 600;
}

.task-status {
  padding: 4px 8px;
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

.status-queued {
  background: #fef3c7;
  color: #92400e;
}

.status-failed {
  background: #fee2e2;
  color: #991b1b;
}

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

.task-progress {
  margin-top: var(--space-sm);
}

.progress-bar {
  height: 6px;
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

.progress-text {
  display: inline-block;
  margin-top: var(--space-xs);
  color: var(--color-text-secondary);
  font-size: 0.75rem;
}

.task-error {
  margin: var(--space-sm) 0 0;
  color: var(--color-error);
  font-size: 0.875rem;
}

.task-time {
  display: inline-block;
  margin-top: var(--space-sm);
  color: var(--color-text-secondary);
  font-size: 0.75rem;
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

  .quick-actions {
    grid-template-columns: 1fr;
  }

  .dashboard-header {
    flex-direction: column;
  }

  .user-panel {
    width: 100%;
    justify-content: space-between;
    flex-wrap: wrap;
  }
}

@media (max-width: 640px) {
  .dashboard {
    padding: var(--space-md);
  }

  .section-header,
  .task-top {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
