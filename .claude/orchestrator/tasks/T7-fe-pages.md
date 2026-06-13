# T7 指令 — fe-pages 终端

## 你的身份

你是 `fe-pages` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

先读取 `D:/20240313整理文件/Desktop/saas/.claude/team/fe-pages.md` 了解你的权限边界。

## 前置条件

T5（fe-core）已完成，前端框架已就绪：
- `frontend/src/api/auth.ts` — 认证 API（register, login, refresh, me）
- `frontend/src/api/tasks.ts` — 任务 API（list, get, cancel, submitVideos, submitImages）
- `frontend/src/stores/auth.ts` — 认证状态（login, register, logout, isAuthenticated, user）
- `frontend/src/stores/tasks.ts` — 任务状态（fetchTasks, updateTaskFromWs）
- `frontend/src/composables/useWebSocket.ts` — WebSocket（connect, subscribe, on）
- `frontend/src/composables/useLoading.ts` — loading 状态（loading, error, run）
- `frontend/src/router/index.ts` — 路由守卫已配置
- `frontend/src/styles/variables.css` — CSS 变量主题
- `frontend/src/types/api.ts` — TypeScript 类型

## 任务目标

实现 4 个核心页面：登录、注册、仪表盘、任务列表。替换现有占位文件。

## 分支

```bash
git checkout -b fe/phase2-pages
```

## 需要创建/修改的文件

### 1. `frontend/src/pages/login/index.vue`

登录页面：

```vue
<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>登录</h1>
      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label for="email">邮箱</label>
          <input
            id="email"
            v-model="email"
            type="email"
            placeholder="your@email.com"
            required
            autocomplete="email"
          />
        </div>
        <div class="form-group">
          <label for="password">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            placeholder="至少8位"
            required
            autocomplete="current-password"
          />
        </div>
        <p v-if="error" class="error-text">{{ error }}</p>
        <button type="submit" class="btn-primary" :disabled="loading">
          {{ loading ? '登录中...' : '登录' }}
        </button>
      </form>
      <p class="auth-link">
        没有账号？<router-link to="/register">注册</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useLoading } from '@/composables/useLoading'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { loading, error, run } = useLoading()

const email = ref('')
const password = ref('')

async function handleLogin() {
  await run(async () => {
    await authStore.login(email.value, password.value)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  })
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-secondary);
}

.auth-card {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-xl);
  width: 100%;
  max-width: 400px;
}

.auth-card h1 {
  margin-bottom: var(--space-lg);
  font-size: 1.5rem;
}

.form-group {
  margin-bottom: var(--space-md);
}

.form-group label {
  display: block;
  margin-bottom: var(--space-xs);
  font-size: 0.875rem;
  color: var(--color-text-secondary);
}

.form-group input {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 1rem;
  background: var(--color-bg);
  color: var(--color-text);
}

.form-group input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.btn-primary {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: var(--radius-md);
  font-size: 1rem;
  cursor: pointer;
  margin-top: var(--space-md);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-text {
  color: var(--color-error);
  font-size: 0.875rem;
  margin-top: var(--space-sm);
}

.auth-link {
  text-align: center;
  margin-top: var(--space-lg);
  font-size: 0.875rem;
  color: var(--color-text-secondary);
}
</style>
```

### 2. `frontend/src/pages/register/index.vue`

注册页面（结构与登录类似）：

```vue
<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>注册</h1>
      <form @submit.prevent="handleRegister">
        <div class="form-group">
          <label for="displayName">昵称（可选）</label>
          <input id="displayName" v-model="displayName" type="text" placeholder="你的昵称" />
        </div>
        <div class="form-group">
          <label for="email">邮箱</label>
          <input id="email" v-model="email" type="email" placeholder="your@email.com" required autocomplete="email" />
        </div>
        <div class="form-group">
          <label for="password">密码</label>
          <input id="password" v-model="password" type="password" placeholder="至少8位" required minlength="8" autocomplete="new-password" />
        </div>
        <div class="form-group">
          <label for="confirmPassword">确认密码</label>
          <input id="confirmPassword" v-model="confirmPassword" type="password" placeholder="再次输入密码" required autocomplete="new-password" />
        </div>
        <p v-if="error" class="error-text">{{ error }}</p>
        <p v-if="mismatch" class="error-text">两次密码不一致</p>
        <button type="submit" class="btn-primary" :disabled="loading || mismatch">
          {{ loading ? '注册中...' : '注册' }}
        </button>
      </form>
      <p class="auth-link">
        已有账号？<router-link to="/login">登录</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useLoading } from '@/composables/useLoading'

const router = useRouter()
const authStore = useAuthStore()
const { loading, error, run } = useLoading()

const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const displayName = ref('')

const mismatch = computed(() => confirmPassword.value !== '' && password.value !== confirmPassword.value)

async function handleRegister() {
  if (mismatch.value) return
  await run(async () => {
    await authStore.register(email.value, password.value, displayName.value || undefined)
    router.push('/')
  })
}
</script>

<style scoped>
/* 复用 login 页面相同样式 */
.auth-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: var(--color-bg-secondary); }
.auth-card { background: var(--color-bg); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-xl); width: 100%; max-width: 400px; }
.auth-card h1 { margin-bottom: var(--space-lg); font-size: 1.5rem; }
.form-group { margin-bottom: var(--space-md); }
.form-group label { display: block; margin-bottom: var(--space-xs); font-size: 0.875rem; color: var(--color-text-secondary); }
.form-group input { width: 100%; padding: var(--space-sm) var(--space-md); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 1rem; background: var(--color-bg); color: var(--color-text); }
.form-group input:focus { outline: none; border-color: var(--color-primary); }
.btn-primary { width: 100%; padding: var(--space-sm) var(--space-md); background: var(--color-primary); color: white; border: none; border-radius: var(--radius-md); font-size: 1rem; cursor: pointer; margin-top: var(--space-md); }
.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.error-text { color: var(--color-error); font-size: 0.875rem; margin-top: var(--space-sm); }
.auth-link { text-align: center; margin-top: var(--space-lg); font-size: 0.875rem; color: var(--color-text-secondary); }
</style>
```

### 3. `frontend/src/pages/dashboard/index.vue`

仪表盘 — 显示用户信息、积分余额、最近任务：

```vue
<template>
  <div class="dashboard">
    <header class="dashboard-header">
      <h1>Dashboard</h1>
      <div class="user-info">
        <span>{{ authStore.user?.email }}</span>
        <span class="tier-badge">{{ authStore.user?.tier }}</span>
        <button class="btn-text" @click="handleLogout">退出</button>
      </div>
    </header>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">积分余额</div>
        <div class="stat-value">{{ credits.balance }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">进行中任务</div>
        <div class="stat-value">{{ runningCount }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已完成任务</div>
        <div class="stat-value">{{ completedCount }}</div>
      </div>
    </div>

    <section class="recent-tasks">
      <div class="section-header">
        <h2>最近任务</h2>
        <router-link to="/tasks" class="view-all">查看全部</router-link>
      </div>
      <div v-if="tasksStore.loading" class="loading">加载中...</div>
      <div v-else-if="tasksStore.tasks.length === 0" class="empty">暂无任务</div>
      <div v-else class="task-list">
        <div v-for="task in tasksStore.tasks.slice(0, 5)" :key="task.task_id" class="task-item">
          <div class="task-info">
            <span class="task-type">{{ task.task_type }}</span>
            <span class="task-status" :class="'status-' + task.status">{{ task.status }}</span>
          </div>
          <div class="task-progress" v-if="task.status === 'running'">
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: task.progress + '%' }"></div>
            </div>
            <span class="progress-text">{{ task.progress }}%</span>
          </div>
          <div class="task-time">{{ formatTime(task.created_at) }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTasksStore } from '@/stores/tasks'
import client from '@/api/client'

const router = useRouter()
const authStore = useAuthStore()
const tasksStore = useTasksStore()

const credits = ref({ balance: 0, lifetime_earned: 0, lifetime_spent: 0 })

const runningCount = computed(() => tasksStore.tasks.filter(t => t.status === 'running' || t.status === 'queued').length)
const completedCount = computed(() => tasksStore.tasks.filter(t => t.status === 'done').length)

onMounted(async () => {
  await tasksStore.fetchTasks({ page: 1 })
  try {
    const { data } = await client.get('/credits')
    credits.value = data
  } catch { /* ignore */ }
})

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.dashboard { max-width: 1000px; margin: 0 auto; padding: var(--space-xl); }
.dashboard-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-xl); }
.user-info { display: flex; align-items: center; gap: var(--space-md); }
.tier-badge { background: var(--color-primary); color: white; padding: 2px 8px; border-radius: var(--radius-sm); font-size: 0.75rem; text-transform: uppercase; }
.btn-text { background: none; border: none; color: var(--color-text-secondary); cursor: pointer; font-size: 0.875rem; }
.btn-text:hover { color: var(--color-error); }

.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-md); margin-bottom: var(--space-xl); }
.stat-card { background: var(--color-bg); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: var(--space-lg); }
.stat-label { font-size: 0.875rem; color: var(--color-text-secondary); margin-bottom: var(--space-xs); }
.stat-value { font-size: 1.5rem; font-weight: 600; }

.recent-tasks { background: var(--color-bg); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: var(--space-lg); }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-md); }
.section-header h2 { font-size: 1.125rem; }
.view-all { font-size: 0.875rem; }

.task-item { padding: var(--space-sm) 0; border-bottom: 1px solid var(--color-border); }
.task-item:last-child { border-bottom: none; }
.task-info { display: flex; justify-content: space-between; align-items: center; }
.task-type { font-size: 0.875rem; }
.task-status { font-size: 0.75rem; padding: 2px 6px; border-radius: var(--radius-sm); }
.status-done { background: #d1fae5; color: #065f46; }
.status-running { background: #dbeafe; color: #1e40af; }
.status-queued { background: #fef3c7; color: #92400e; }
.status-failed { background: #fee2e2; color: #991b1b; }

.progress-bar { height: 4px; background: var(--color-border); border-radius: 2px; margin-top: var(--space-xs); }
.progress-fill { height: 100%; background: var(--color-primary); border-radius: 2px; transition: width 0.3s; }
.progress-text { font-size: 0.75rem; color: var(--color-text-secondary); }
.task-time { font-size: 0.75rem; color: var(--color-text-secondary); margin-top: 2px; }

.loading, .empty { text-align: center; padding: var(--space-xl); color: var(--color-text-secondary); }
</style>
```

### 4. `frontend/src/pages/tasks/index.vue`

任务列表页 — 带筛选、分页、实时更新：

```vue
<template>
  <div class="tasks-page">
    <header class="page-header">
      <h1>任务列表</h1>
      <router-link to="/" class="btn-back">← 返回</router-link>
    </header>

    <div class="filters">
      <button
        v-for="s in statuses"
        :key="s.value"
        class="filter-btn"
        :class="{ active: currentStatus === s.value }"
        @click="filterByStatus(s.value)"
      >
        {{ s.label }}
      </button>
    </div>

    <div v-if="tasksStore.loading" class="loading">加载中...</div>
    <div v-else-if="tasksStore.tasks.length === 0" class="empty">暂无任务</div>
    <div v-else class="task-list">
      <div v-for="task in tasksStore.tasks" :key="task.task_id" class="task-card">
        <div class="task-card-header">
          <span class="task-type">{{ task.task_type }}</span>
          <span class="task-status" :class="'status-' + task.status">{{ task.status }}</span>
        </div>
        <div class="task-card-body">
          <div v-if="task.status === 'running'" class="progress-section">
            <div class="progress-bar"><div class="progress-fill" :style="{ width: task.progress + '%' }"></div></div>
            <span>{{ task.stage_text || `${task.progress}%` }}</span>
          </div>
          <div v-if="task.error_message" class="error-msg">{{ task.error_message }}</div>
          <div class="task-meta">
            <span>创建: {{ formatTime(task.created_at) }}</span>
            <span v-if="task.completed_at">完成: {{ formatTime(task.completed_at) }}</span>
          </div>
        </div>
        <div class="task-card-actions" v-if="task.status === 'queued' || task.status === 'pending'">
          <button class="btn-cancel" @click="cancelTask(task.task_id)">取消</button>
        </div>
      </div>
    </div>

    <div class="pagination" v-if="tasksStore.total > pageSize">
      <button :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useTasksStore } from '@/stores/tasks'
import { tasksApi } from '@/api/tasks'
import { useWebSocket } from '@/composables/useWebSocket'

const tasksStore = useTasksStore()
const { connect, subscribe, on, disconnect } = useWebSocket()

const page = ref(1)
const pageSize = 20
const currentStatus = ref<string | undefined>(undefined)

const totalPages = computed(() => Math.ceil(tasksStore.total / pageSize))

const statuses = [
  { label: '全部', value: undefined },
  { label: '排队中', value: 'queued' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'done' },
  { label: '失败', value: 'failed' },
]

onMounted(async () => {
  await loadTasks()
  connect()
  on('task_update', (msg) => {
    tasksStore.updateTaskFromWs(msg.task_id, { status: msg.status, progress: msg.progress, stage_text: msg.stage_text })
  })
  on('task_complete', (msg) => {
    tasksStore.updateTaskFromWs(msg.task_id, { status: 'done', progress: 100, result: msg.result })
  })
  on('task_failed', (msg) => {
    tasksStore.updateTaskFromWs(msg.task_id, { status: 'failed', error_message: msg.error })
  })
  // 订阅当前页所有运行中的任务
  const runningIds = tasksStore.tasks.filter(t => t.status === 'running' || t.status === 'queued').map(t => t.task_id)
  if (runningIds.length) subscribe(runningIds)
})

onUnmounted(() => { disconnect() })

async function loadTasks() {
  await tasksStore.fetchTasks({ status: currentStatus.value, page: page.value })
}

function filterByStatus(status: string | undefined) {
  currentStatus.value = status
  page.value = 1
  loadTasks()
}

function goPage(p: number) {
  page.value = p
  loadTasks()
}

async function cancelTask(taskId: string) {
  await tasksApi.cancel(taskId)
  await loadTasks()
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.tasks-page { max-width: 1000px; margin: 0 auto; padding: var(--space-xl); }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-lg); }
.btn-back { font-size: 0.875rem; color: var(--color-text-secondary); }

.filters { display: flex; gap: var(--space-sm); margin-bottom: var(--space-lg); flex-wrap: wrap; }
.filter-btn { padding: var(--space-xs) var(--space-md); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-bg); cursor: pointer; font-size: 0.875rem; color: var(--color-text-secondary); }
.filter-btn.active { border-color: var(--color-primary); color: var(--color-primary); background: #eef2ff; }

.task-card { border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: var(--space-md); margin-bottom: var(--space-sm); }
.task-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-sm); }
.task-type { font-weight: 500; }
.task-status { font-size: 0.75rem; padding: 2px 6px; border-radius: var(--radius-sm); }
.status-done { background: #d1fae5; color: #065f46; }
.status-running { background: #dbeafe; color: #1e40af; }
.status-queued { background: #fef3c7; color: #92400e; }
.status-failed { background: #fee2e2; color: #991b1b; }
.status-cancelled { background: #f3f4f6; color: #6b7280; }

.progress-section { margin-bottom: var(--space-sm); }
.progress-bar { height: 6px; background: var(--color-border); border-radius: 3px; }
.progress-fill { height: 100%; background: var(--color-primary); border-radius: 3px; transition: width 0.3s; }
.progress-section span { font-size: 0.75rem; color: var(--color-text-secondary); }

.error-msg { color: var(--color-error); font-size: 0.875rem; margin-bottom: var(--space-sm); }
.task-meta { font-size: 0.75rem; color: var(--color-text-secondary); display: flex; gap: var(--space-md); }
.task-card-actions { margin-top: var(--space-sm); }
.btn-cancel { padding: 4px 12px; border: 1px solid var(--color-error); color: var(--color-error); background: none; border-radius: var(--radius-sm); cursor: pointer; font-size: 0.75rem; }
.btn-cancel:hover { background: #fee2e2; }

.pagination { display: flex; justify-content: center; align-items: center; gap: var(--space-md); margin-top: var(--space-lg); }
.pagination button { padding: var(--space-xs) var(--space-md); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-bg); cursor: pointer; }
.pagination button:disabled { opacity: 0.5; cursor: not-allowed; }

.loading, .empty { text-align: center; padding: var(--space-xl); color: var(--color-text-secondary); }
</style>
```

## 验收标准

1. `/login` — 能输入邮箱密码登录，成功后跳转仪表盘
2. `/register` — 能注册新账号，密码确认校验，成功后跳转仪表盘
3. `/` (dashboard) — 显示用户信息、积分余额、最近5条任务
4. `/tasks` — 任务列表带状态筛选、分页、实时进度更新
5. 未登录访问 `/` 或 `/tasks` 自动跳转 `/login`
6. 已登录访问 `/login` 自动跳转 `/`
7. 退出按钮清除 token 并跳转登录页
8. 所有页面使用 CSS 变量，支持主题切换
9. TypeScript 无报错

## 完成后

告诉 orchestrator：T7 完成，列出创建/修改的文件清单。
