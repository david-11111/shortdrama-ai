# T19 指令 — fe-pages 终端

## 你的身份

你是 `fe-pages` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

实现管理后台前端：7 个页面 + 侧边栏布局 + admin 路由守卫。

## 分支

（如果 git 报错可忽略，直接在当前分支工作）

## API 端点与响应格式

所有端点前缀 `/api/admin/`，需要 admin 用户的 JWT。

```
GET /admin/overview → {
  users: { total_users, active_users, new_today },
  tasks: { active_tasks, completed_today, failed_today },
  revenue_today: number,
  dead_letter_count: number
}

GET /admin/users?page=1&page_size=20&tier=&status=&search= → {
  users: [{ id, email, display_name, tier, status, is_admin, created_at, balance, lifetime_spent }],
  total, page, page_size
}

PATCH /admin/users/:id  body: { tier?, status?, is_admin? }

GET /admin/tasks?page=1&status=&task_type=&user_id= → {
  tasks: [{ task_id, user_id, user_email, task_type, status, progress, stage_text, error_message, retry_count, created_at, started_at, completed_at }],
  total, page, page_size
}

GET /admin/tasks/stats → {
  stats: [{ task_type, total, succeeded, failed, active, avg_duration_seconds }]
}

GET /admin/credits/revenue?days=30 → {
  daily_revenue: [{ date, revenue, transactions }],
  top_spenders: [{ id, email, tier, lifetime_spent, balance }]
}

GET /admin/credits/pricing → {
  pricing: [{ id, operation, credits_cost, active }]
}

PATCH /admin/credits/pricing/:id  body: { credits_cost?, active? }

GET /admin/dead-letter?resolved=false&page=1 → {
  items: [{ id, original_task_id, user_id, user_email, task_type, payload, error_history, dead_at, resolved }],
  total, page
}

POST /admin/dead-letter/:id/retry → { message, new_task_id }
PATCH /admin/dead-letter/:id/resolve → { message }

GET /admin/key-pool → {
  services: { seedance: [{ name, load, rpm, cooldown_until, max_concurrency }], ... }
}

GET /admin/system → {
  database: "healthy"|"unhealthy",
  redis: { used_memory_human, used_memory_peak_human },
  queue_depth: { video_gen: N, image_gen: N, ... }
}

GET /admin/rate-limits → {
  rules: [{ id, tier, resource, window_seconds, max_count }]
}

PATCH /admin/rate-limits/:id  body: { window_seconds?, max_count? }
```

## 需要创建/修改的文件

### 1. `frontend/src/api/admin.ts`（新建）

Admin API 客户端，封装所有 admin 端点调用。

### 2. `frontend/src/layouts/AdminLayout.vue`（新建）

管理后台布局：左侧边栏导航 + 右侧内容区。

侧边栏菜单项：
- 总览 (`/admin`)
- 用户管理 (`/admin/users`)
- 任务监控 (`/admin/tasks`)
- 积分与收入 (`/admin/credits`)
- 死信队列 (`/admin/dead-letter`)
- Key Pool (`/admin/keys`)
- 系统健康 (`/admin/system`)
- ← 返回前台 (`/`)

样式：
- 侧边栏宽度 240px，深色背景（`#1a1a2e` 或类似）
- 当前激活项高亮
- 内容区有 padding，最大宽度 1200px
- 响应式：移动端侧边栏可折叠

### 3. `frontend/src/pages/admin/index.vue` — 总览仪表盘

4 个统计卡片（用户数、活跃任务、今日收入、死信数）+ 简要图表或数字展示。

### 4. `frontend/src/pages/admin/users.vue` — 用户管理

- 搜索框 + tier/status 筛选下拉
- 用户表格：邮箱、套餐、状态、余额、注册时间、操作
- 操作：修改套餐（下拉）、禁用/启用（按钮）、设为管理员（开关）
- 分页

### 5. `frontend/src/pages/admin/tasks.vue` — 任务监控

- 筛选：status 下拉、task_type 下拉
- 任务表格：ID(截断)、用户邮箱、类型、状态、进度、耗时、创建时间
- 顶部统计卡片（来自 /tasks/stats）：各类型成功率
- 分页

### 6. `frontend/src/pages/admin/credits.vue` — 积分与收入

- 日收入趋势（简单的数字列表或 CSS bar chart）
- Top 10 消费者表格
- 定价管理表格（可编辑 credits_cost，保存按钮）

### 7. `frontend/src/pages/admin/dead-letter.vue` — 死信队列

- 死信任务列表：任务类型、用户、错误信息、死亡时间
- 操作按钮：重试、标记解决
- 重试前确认对话框
- 切换显示已解决/未解决

### 8. `frontend/src/pages/admin/keys.vue` — Key Pool

- 按服务分组展示
- 每个 Key 显示：名称、当前负载/最大并发、RPM、冷却状态
- 负载条形图（load / max_concurrency）
- 冷却中的 Key 标红
- 自动刷新（每 10 秒）

### 9. `frontend/src/pages/admin/system.vue` — 系统健康

- 数据库状态指示灯
- Redis 内存使用
- 各队列深度
- 限流配置表格（可编辑 max_count，保存按钮）

### 10. 更新 `frontend/src/router/index.ts`

添加 admin 路由组（使用 AdminLayout）：

```typescript
{
  path: '/admin',
  component: () => import('@/layouts/AdminLayout.vue'),
  meta: { requiresAuth: true, requiresAdmin: true },
  children: [
    { path: '', name: 'admin-overview', component: () => import('@/pages/admin/index.vue') },
    { path: 'users', name: 'admin-users', component: () => import('@/pages/admin/users.vue') },
    { path: 'tasks', name: 'admin-tasks', component: () => import('@/pages/admin/tasks.vue') },
    { path: 'credits', name: 'admin-credits', component: () => import('@/pages/admin/credits.vue') },
    { path: 'dead-letter', name: 'admin-dead-letter', component: () => import('@/pages/admin/dead-letter.vue') },
    { path: 'keys', name: 'admin-keys', component: () => import('@/pages/admin/keys.vue') },
    { path: 'system', name: 'admin-system', component: () => import('@/pages/admin/system.vue') },
  ],
},
```

路由守卫：`requiresAdmin` meta 检查 `authStore.user?.is_admin`。

### 11. 更新 `frontend/src/types/api.ts`

User 接口添加 `is_admin: boolean`。

### 12. 更新 `frontend/src/stores/auth.ts`

`fetchUser` 后存储 is_admin 状态，供路由守卫使用。

### 13. 更新 `frontend/src/pages/dashboard/index.vue`

如果用户是 admin，在 user-panel 区域显示"管理后台"入口链接。

## 样式要求

- 管理后台使用独立的深色侧边栏风格，与前台区分
- 表格使用简洁的 border-bottom 分隔行
- 统计卡片复用前台的 `.stat-card` 样式
- 操作按钮：主操作蓝色、危险操作红色、次要操作灰色
- 所有列表支持 loading 状态
- 响应式：表格在移动端横向滚动

## 验收标准

1. `/admin` 总览页显示 4 个核心指标
2. `/admin/users` 能搜索、筛选、修改用户套餐和状态
3. `/admin/tasks` 能看所有用户任务，有统计卡片
4. `/admin/credits` 显示收入趋势和 Top 消费者，能编辑定价
5. `/admin/dead-letter` 能查看死信、重试、标记解决
6. `/admin/keys` 实时显示 Key Pool 状态，自动刷新
7. `/admin/system` 显示系统健康和限流配置
8. 非 admin 用户访问 /admin 被重定向
9. Dashboard 对 admin 用户显示管理后台入口
10. `npm run build` 通过

## 完成后

告诉 orchestrator：T19 完成，列出创建/修改的文件清单。
