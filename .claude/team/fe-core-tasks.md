# fe-core 当前任务（P0 — 其他终端依赖）

## 背景

生产流水线 UI 升级，参考 LibTV/Runway 深色主题风格。fe-pages 依赖你产出的 poller 和动画工具。

## 任务清单

### 任务 1：useTaskPoller composable

新建 `frontend/src/composables/useTaskPoller.ts`

```typescript
// 接口规范
export function useTaskPoller() {
  function start(taskId: string): void  // 开始轮询
  function stop(): void                 // 手动停止
  const status: Ref<string>             // queued/running/done/failed
  const progress: Ref<number>           // 0-100
  const stageText: Ref<string>          // 当前阶段文字
  const result: Ref<any>                // done 时的结果
  const error: Ref<string>              // failed 时的错误信息
  const isPolling: Ref<boolean>         // 是否正在轮询
}
```

实现要求：
- 每 2s 轮询 `GET /api/tasks/{task_id}`（用 `@/api/client`）
- status 为 done/failed/cancelled 时自动停止
- 超时 10 分钟自动停止
- 支持同时跟踪多个任务（每次 start 新 task 会停掉旧的）
- 组件 unmount 时自动清理（onUnmounted）

### 任务 2：动画/过渡工具

新建 `frontend/src/styles/animations.css`

```css
/* 必须包含以下 keyframes 和工具类 */
@keyframes pulse-glow { /* 卡片边框呼吸灯 — 任务进行中 */ }
@keyframes progress-stripe { /* 进度条斜纹滚动 */ }
@keyframes fade-in { /* 内容淡入 */ }
@keyframes slide-up { /* 卡片从下方滑入 */ }
@keyframes skeleton-shimmer { /* 骨架屏闪烁 */ }

.animate-pulse-glow { animation: pulse-glow 2s ease-in-out infinite; }
.animate-progress { animation: progress-stripe 1s linear infinite; }
.animate-fade-in { animation: fade-in 0.3s ease-out; }
.animate-slide-up { animation: slide-up 0.3s ease-out; }
.skeleton { animation: skeleton-shimmer 1.5s infinite; }
.transition-all { transition: all 0.2s ease; }
```

在 `frontend/src/main.ts` 中添加 `import './styles/animations.css'`

### 任务 3：深色主题变量扩展

修改 `frontend/src/styles/variables.css`，在 `[data-theme="dark"]` 块中追加：

```css
--shadow-card: 0 0 0 1px rgba(99, 102, 241, 0.1), 0 4px 12px rgba(0, 0, 0, 0.3);
--shadow-card-hover: 0 0 0 1px rgba(99, 102, 241, 0.2), 0 8px 24px rgba(0, 0, 0, 0.4);
--glow-primary: 0 0 12px rgba(99, 102, 241, 0.4);
--glow-success: 0 0 12px rgba(16, 185, 129, 0.4);
--glow-warning: 0 0 12px rgba(245, 158, 11, 0.4);
--gradient-progress: linear-gradient(90deg, #6366f1, #8b5cf6, #6366f1);
--bg-chat-user: rgba(99, 102, 241, 0.08);
--bg-chat-assistant: rgba(16, 185, 129, 0.08);
--bg-chat-system: rgba(239, 68, 68, 0.08);
--bg-skeleton: linear-gradient(90deg, #1f2937 25%, #374151 50%, #1f2937 75%);
```

同时在默认（浅色）主题中也加对应变量（用浅色值）。

## 验收

```bash
cd frontend && npm run build
```

编译通过即可提交。不需要页面视觉验证（那是 fe-pages 的事）。

## 完成后

通知 orchestrator，fe-pages 可以开始任务 4-8。
