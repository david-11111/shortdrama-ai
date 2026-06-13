# T13 指令 — fe-pages 终端

## 你的身份

你是 `fe-pages` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 前置条件

- 前端脚手架已就绪（Vue 3 + Vite + Pinia + Router）
- 页面已有：login、register、dashboard、tasks
- API 客户端 `@/api/client.ts` 已配置 token 自动附加和 401 刷新
- `@/api/tasks.ts` 已有 `submitVideos`、`submitImages` 方法
- WebSocket composable `@/composables/useWebSocket.ts` 已就绪

## 任务目标

添加**任务提交页面**和**实时进度展示**，让用户能实际使用系统：

1. 视频生成提交表单
2. 图片生成提交表单
3. 任务详情页（含实时进度条）

## 分支

```bash
git checkout -b fe/phase4-task-submit
```

## 需要创建的文件

### 1. `frontend/src/pages/tasks/submit-video.vue`

视频生成提交页面：

- 表单字段：prompt（文本域）、duration（下拉：5s/8s/10s）、resolution（下拉：720p/1080p）
- 提交按钮调用 `tasksApi.submitVideos([{ prompt, duration, resolution }])`
- 提交成功后跳转到任务列表页，显示 toast 提示
- 积分不足（402）时显示错误提示
- 限流（429）时显示 retry-after 倒计时

### 2. `frontend/src/pages/tasks/submit-image.vue`

图片生成提交页面：

- 表单字段：prompt（文本域）、style（下拉：default/anime/realistic/oil-painting）、size（下拉：512x512/1024x1024）
- 提交按钮调用 `tasksApi.submitImages([{ prompt, style, width, height }])`
- 同样处理 402 和 429

### 3. `frontend/src/pages/tasks/[id].vue`

任务详情页：

- 路由：`/tasks/:id`
- 调用 `tasksApi.get(taskId)` 获取任务信息
- 显示：任务类型、状态、创建时间、进度条、阶段文本
- 使用 WebSocket 订阅该任务的实时更新
- 任务完成时显示结果（视频 URL / 图片 URL）
- 任务失败时显示错误信息和退还积分数

### 4. 更新 `frontend/src/router/index.ts`

添加新路由：

```typescript
{
  path: '/tasks/submit-video',
  component: () => import('@/pages/tasks/submit-video.vue'),
  meta: { requiresAuth: true },
},
{
  path: '/tasks/submit-image',
  component: () => import('@/pages/tasks/submit-image.vue'),
  meta: { requiresAuth: true },
},
{
  path: '/tasks/:id',
  component: () => import('@/pages/tasks/[id].vue'),
  meta: { requiresAuth: true },
},
```

### 5. 更新 `frontend/src/pages/dashboard/index.vue`

在 stats-grid 下方添加快捷入口按钮：

```html
<section class="quick-actions">
  <router-link to="/tasks/submit-video" class="action-btn">生成视频</router-link>
  <router-link to="/tasks/submit-image" class="action-btn">生成图片</router-link>
</section>
```

## 样式要求

- 复用现有 CSS 变量（`--color-primary`、`--color-border`、`--radius-lg` 等）
- 表单使用 `.form-group` + `label` + `input/select/textarea` 结构
- 按钮使用 `.btn-primary` 样式
- 进度条复用 dashboard 中的 `.progress-bar` / `.progress-fill` 样式
- 响应式：移动端表单全宽

## 验收标准

1. `/tasks/submit-video` 页面能提交视频生成请求
2. `/tasks/submit-image` 页面能提交图片生成请求
3. `/tasks/:id` 页面能显示任务详情和实时进度
4. 402 错误显示"积分不足"提示
5. 429 错误显示"请求过于频繁，N 秒后重试"
6. Dashboard 有快捷入口按钮
7. 路由守卫正常（未登录跳转 login）

## 完成后

告诉 orchestrator：T13 完成，列出创建/修改的文件清单。
