# T5 指令 — fe-core 终端

## 你的身份

你是 `fe-core` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

先读取 `D:/20240313整理文件/Desktop/saas/.claude/team/fe-core.md` 了解你的权限边界。

## 前置条件

后端 Phase 1 已完成，API 端点已就绪：
- `POST /api/auth/register` — 注册（T4 正在实现）
- `POST /api/auth/login` — 登录
- `POST /api/auth/refresh` — 刷新 Token
- `GET /api/auth/me` — 当前用户
- `GET /api/tasks` — 任务列表
- `GET /api/tasks/{id}` — 任务详情
- `POST /api/batch/generate-videos` — 提交视频生成
- `POST /api/batch/generate-images` — 提交图片生成
- `WS /ws/tasks` — 实时任务进度

## 任务目标

搭建前端项目脚手架，实现核心基础设施：HTTP 客户端、路由框架、状态管理、通用组件、WebSocket 客户端。为 fe-pages 终端提供开发基础。

## 技术选型

- 框架：Vue 3 + Composition API
- 构建：Vite
- 语言：TypeScript
- 状态管理：Pinia
- 路由：Vue Router
- HTTP：Axios
- UI 基础：自建组件（不引入重型 UI 库，保持轻量）
- 样式：CSS Variables 主题系统

## 分支

```bash
git checkout -b fe-core/phase2-scaffold
```

## 需要创建的文件

### 1. 项目初始化

```
frontend/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── .eslintrc.cjs
└── src/
    └── main.ts
```

**`package.json`** 核心依赖：

```json
{
  "name": "saas-frontend",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.2.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vue-tsc": "^2.1.0"
  }
}
```

**`vite.config.ts`**：

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
```

### 2. `frontend/src/types/` — 类型定义

**`frontend/src/types/api.ts`**：

```typescript
// 与后端 app/schemas/ 对齐的类型定义

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface User {
  id: number
  user_id: string
  email: string
  display_name: string | null
  tier: 'free' | 'pro' | 'enterprise'
  status: string
  created_at: string
}

export interface Task {
  task_id: string
  task_type: string
  status: 'pending' | 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  progress: number
  stage_text: string | null
  result: Record<string, any> | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface TaskListResponse {
  tasks: Task[]
  total: number
  page: number
  page_size: number
}

export interface BatchSubmitResponse {
  parent_task_id: string
  child_task_ids: string[]
  status: string
  total_credits_reserved: number
}

export interface ApiKey {
  key_id: string
  name: string
  created_at: string
  api_key?: string  // 仅创建时返回
}
```

**`frontend/src/types/ws.ts`**：

```typescript
// WebSocket 消息类型

export interface WsTaskUpdate {
  type: 'task_update'
  task_id: string
  status: string
  progress: number
  stage_text: string
}

export interface WsTaskComplete {
  type: 'task_complete'
  task_id: string
  result: Record<string, any>
}

export interface WsTaskFailed {
  type: 'task_failed'
  task_id: string
  error: string
  credits_refunded?: number
}

export type WsMessage = WsTaskUpdate | WsTaskComplete | WsTaskFailed | { type: 'pong' }
```

### 3. `frontend/src/api/` — HTTP 客户端

**`frontend/src/api/client.ts`**：

```typescript
/**
 * Axios 实例 — 统一的 HTTP 客户端。
 *
 * 功能:
 * - 自动附加 Authorization header
 * - Token 过期自动刷新（401 拦截）
 * - 统一错误处理
 */
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/auth'

const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：附加 token
client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const authStore = useAuthStore()
  if (authStore.accessToken) {
    config.headers.Authorization = `Bearer ${authStore.accessToken}`
  }
  return config
})

// 响应拦截：处理 401 自动刷新
let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    const authStore = useAuthStore()

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(client(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const newToken = await authStore.refreshToken()
        pendingRequests.forEach((cb) => cb(newToken))
        pendingRequests = []
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return client(originalRequest)
      } catch {
        authStore.logout()
        window.location.href = '/login'
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

export default client
```

**`frontend/src/api/auth.ts`**：

```typescript
import client from './client'
import type { TokenResponse, User } from '@/types/api'

export const authApi = {
  register(email: string, password: string, displayName?: string) {
    return client.post<TokenResponse>('/auth/register', { email, password, display_name: displayName })
  },

  login(email: string, password: string) {
    return client.post<TokenResponse>('/auth/login', { email, password })
  },

  refresh(refreshToken: string) {
    return client.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken })
  },

  me() {
    return client.get<User>('/auth/me')
  },
}
```

**`frontend/src/api/tasks.ts`**：

```typescript
import client from './client'
import type { TaskListResponse, Task, BatchSubmitResponse } from '@/types/api'

export const tasksApi = {
  list(params?: { status?: string; page?: number; page_size?: number }) {
    return client.get<TaskListResponse>('/tasks', { params })
  },

  get(taskId: string) {
    return client.get<Task>(`/tasks/${taskId}`)
  },

  cancel(taskId: string) {
    return client.post(`/tasks/${taskId}/cancel`)
  },

  submitVideos(items: any[]) {
    return client.post<BatchSubmitResponse>('/batch/generate-videos', { items })
  },

  submitImages(items: any[]) {
    return client.post<BatchSubmitResponse>('/batch/generate-images', { items })
  },
}
```

### 4. `frontend/src/stores/` — 状态管理

**`frontend/src/stores/auth.ts`**：

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User } from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(localStorage.getItem('access_token'))
  const _refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const user = ref<User | null>(null)

  const isAuthenticated = computed(() => !!accessToken.value)

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    _refreshToken.value = refresh
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  function logout() {
    accessToken.value = null
    _refreshToken.value = null
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  async function login(email: string, password: string) {
    const { data } = await authApi.login(email, password)
    setTokens(data.access_token, data.refresh_token)
    await fetchUser()
  }

  async function register(email: string, password: string, displayName?: string) {
    const { data } = await authApi.register(email, password, displayName)
    setTokens(data.access_token, data.refresh_token)
    await fetchUser()
  }

  async function refreshToken(): Promise<string> {
    if (!_refreshToken.value) throw new Error('No refresh token')
    const { data } = await authApi.refresh(_refreshToken.value)
    setTokens(data.access_token, data.refresh_token)
    return data.access_token
  }

  async function fetchUser() {
    const { data } = await authApi.me()
    user.value = data
  }

  return { accessToken, user, isAuthenticated, login, register, logout, refreshToken, fetchUser, setTokens }
})
```

**`frontend/src/stores/tasks.ts`**：

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { tasksApi } from '@/api/tasks'
import type { Task } from '@/types/api'

export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<Task[]>([])
  const total = ref(0)
  const loading = ref(false)

  async function fetchTasks(params?: { status?: string; page?: number }) {
    loading.value = true
    try {
      const { data } = await tasksApi.list(params)
      tasks.value = data.tasks
      total.value = data.total
    } finally {
      loading.value = false
    }
  }

  function updateTaskFromWs(taskId: string, updates: Partial<Task>) {
    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index !== -1) {
      tasks.value[index] = { ...tasks.value[index], ...updates }
    }
  }

  return { tasks, total, loading, fetchTasks, updateTaskFromWs }
})
```

### 5. `frontend/src/composables/` — 通用 Hooks

**`frontend/src/composables/useWebSocket.ts`**：

```typescript
import { ref, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { WsMessage } from '@/types/ws'

/**
 * WebSocket composable — 自动重连 + 心跳 + 事件分发。
 */
export function useWebSocket() {
  const connected = ref(false)
  const listeners = new Map<string, Set<(msg: any) => void>>()

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let reconnectAttempts = 0
  const MAX_RECONNECT = 10

  function connect() {
    const authStore = useAuthStore()
    if (!authStore.accessToken) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/tasks?token=${authStore.accessToken}`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
      startHeartbeat()
    }

    ws.onmessage = (event) => {
      const msg: WsMessage = JSON.parse(event.data)
      const typeListeners = listeners.get(msg.type)
      if (typeListeners) {
        typeListeners.forEach(cb => cb(msg))
      }
    }

    ws.onclose = () => {
      connected.value = false
      stopHeartbeat()
      scheduleReconnect()
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function subscribe(taskIds: string[]) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe', task_ids: taskIds }))
    }
  }

  function unsubscribe(taskIds: string[]) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'unsubscribe', task_ids: taskIds }))
    }
  }

  function on(type: string, callback: (msg: any) => void) {
    if (!listeners.has(type)) listeners.set(type, new Set())
    listeners.get(type)!.add(callback)
  }

  function off(type: string, callback: (msg: any) => void) {
    listeners.get(type)?.delete(callback)
  }

  function startHeartbeat() {
    heartbeatTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) clearInterval(heartbeatTimer)
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) return
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
    reconnectTimer = setTimeout(() => {
      reconnectAttempts++
      connect()
    }, delay)
  }

  function disconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    stopHeartbeat()
    ws?.close()
    ws = null
  }

  onUnmounted(disconnect)

  return { connected, connect, disconnect, subscribe, unsubscribe, on, off }
}
```

**`frontend/src/composables/useLoading.ts`**：

```typescript
import { ref } from 'vue'

/**
 * 通用 loading 状态管理。
 */
export function useLoading() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    loading.value = true
    error.value = null
    try {
      return await fn()
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || 'Unknown error'
      return undefined
    } finally {
      loading.value = false
    }
  }

  return { loading, error, run }
}
```

### 6. `frontend/src/router/` — 路由

**`frontend/src/router/index.ts`**：

```typescript
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/login/index.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/pages/register/index.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/pages/dashboard/index.vue'),
    meta: { requiresAuth: true, title: 'Dashboard' },
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('@/pages/tasks/index.vue'),
    meta: { requiresAuth: true, title: 'Tasks' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!to.meta.requiresAuth && authStore.isAuthenticated && (to.name === 'login' || to.name === 'register')) {
    return { name: 'dashboard' }
  }
})

export default router
```

### 7. `frontend/src/styles/` — 主题系统

**`frontend/src/styles/variables.css`**：

```css
:root {
  /* Colors */
  --color-primary: #6366f1;
  --color-primary-hover: #4f46e5;
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-error: #ef4444;
  --color-bg: #ffffff;
  --color-bg-secondary: #f9fafb;
  --color-text: #111827;
  --color-text-secondary: #6b7280;
  --color-border: #e5e7eb;

  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;

  /* Border Radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  /* Font */
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
}

/* Dark mode */
[data-theme="dark"] {
  --color-bg: #111827;
  --color-bg-secondary: #1f2937;
  --color-text: #f9fafb;
  --color-text-secondary: #9ca3af;
  --color-border: #374151;
}
```

**`frontend/src/styles/global.css`**：

```css
@import './variables.css';

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  background: var(--color-bg);
  color: var(--color-text);
  line-height: 1.6;
}

a {
  color: var(--color-primary);
  text-decoration: none;
}
```

### 8. `frontend/src/App.vue` + `frontend/src/main.ts`

**`frontend/src/main.ts`**：

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

**`frontend/src/App.vue`**：

```vue
<template>
  <router-view />
</template>
```

### 9. 占位页面（给 fe-pages 提供路由目标）

创建最小占位文件，让路由不报错：

- `frontend/src/pages/login/index.vue` — `<template><div>Login Page (TODO)</div></template>`
- `frontend/src/pages/register/index.vue` — `<template><div>Register Page (TODO)</div></template>`
- `frontend/src/pages/dashboard/index.vue` — `<template><div>Dashboard (TODO)</div></template>`
- `frontend/src/pages/tasks/index.vue` — `<template><div>Tasks (TODO)</div></template>`

## 验收标准

1. `cd frontend && npm install && npm run dev` 能正常启动开发服务器
2. 访问 `http://localhost:3000` 能看到页面
3. API 代理正确（`/api/*` 转发到 `localhost:8000`）
4. `useAuthStore` 能正确管理 token 和用户状态
5. `useWebSocket` 能连接 WebSocket 并自动重连
6. 路由守卫正确（未登录跳转 login）
7. TypeScript 类型与后端 schemas 对齐
8. 暗色主题 CSS 变量已预留

## 完成后

告诉 orchestrator：T5 完成，列出创建的文件清单。
