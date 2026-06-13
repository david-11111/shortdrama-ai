# fe-pages 当前任务（P1 — 等 fe-core 完成后执行）

## 紧急修复（P0 — 最高优先级，开工第一件事做）

### 任务 9：发送时自动创建项目

**这是一个严重的交互设计失误。用户打开页面，输入创意，点发送，结果弹一个"请先选择项目"——这在任何商业产品里都是不可接受的。用户不知道什么是 project_id，也不应该知道。这是内部概念，不该暴露给用户。**

**你上一轮交付的 ChatPanel.vue 犯了这个错误：把后端的数据模型约束直接甩给了用户。这不是前端该做的事。前端的职责是屏蔽复杂度，不是转嫁复杂度。**

文件：`frontend/src/pages/director/produce/ChatPanel.vue`

要求（没有商量余地）：
1. 用户打开页面，直接输入创意，点发送。**不需要任何前置操作。**
2. 如果 `session.projectId.value` 为空，**静默**调 `createProject({ name: 用户输入前10个字 })`
3. 拿到 `project_id` 后写入 session，然后继续发 chat
4. 用户全程无感知。没有弹窗、没有提示、没有跳转。
5. `generateScript()` 同理——没有项目就自动建。
6. 顶部的项目选择器保留，但它是**可选的高级功能**，不是必填前置条件。

**验收标准：我（orchestrator）打开一个全新浏览器标签，进入 /director/produce，输入一句话点发送，必须直接进入"导演思考中"状态。如果弹出任何关于项目的提示，打回重做。**

---

## 前置依赖

等 fe-core 完成以下产出后再开始：
- `composables/useTaskPoller.ts` 存在且可 import
- `styles/animations.css` 存在且已在 main.ts 中引入
- `styles/variables.css` 中有 `--shadow-card`、`--glow-primary`、`--bg-chat-*` 等变量

## 背景

生产流水线页面 UI 升级。参考 LibTV / Runway 风格：
- **深色主题为主**（背景 #111827，卡片 #1f2937）
- **卡片带微妙阴影和 border glow**
- **进度/状态用动画反馈**（pulse、shimmer、fade-in）
- **信息密度高**，一屏看全
- **操作按钮有 hover 动效**

所有文件在 `frontend/src/pages/director/produce/` 目录下。

## 任务清单

### 任务 4：ChatPanel.vue 重写

核心改动：
1. 用 `useTaskPoller` 替代当前的 `pollTaskResult` 内联函数
2. 发送消息后，立即在对话区显示"导演思考中..."占位气泡（带 `.animate-pulse-glow` 类）
3. 任务 done 后，占位气泡替换为真实回复（带 `.animate-fade-in`）
4. 阶段进度条改为横向 step bar：每步之间有连线，当前步有 glow，已完成步有 checkmark
5. 对话区高度：`min-height: 200px; max-height: 60vh; overflow-y: auto`
6. 深色主题：消息背景用 `var(--bg-chat-user)` / `var(--bg-chat-assistant)` / `var(--bg-chat-system)`
7. 输入框：深色背景、浅色文字、focus 时 border glow

### 任务 5：ShotCards.vue 重写

核心改动：
1. 卡片样式：`background: var(--bg-secondary); box-shadow: var(--shadow-card); border-radius: var(--radius-lg)`
2. Hover 效果：`transform: translateY(-2px); box-shadow: var(--shadow-card-hover)`
3. 状态 badge：generating 状态加 `.animate-pulse-glow`
4. 进行中的卡片：整个卡片边框用 `box-shadow: var(--glow-primary)`
5. 无图时：显示骨架屏占位（`.skeleton` 类，宽高比 16:9）
6. 进入页面时如果 projectId 存在，自动调用 loadShots()（不需要手动点刷新）
7. 批量操作按钮组：改为 toolbar 风格，按钮之间无间隙，首尾圆角
8. "一键生产"按钮：渐变背景 `var(--gradient-progress)`，hover 发光

### 任务 6：RefImageGrid.vue 重写

核心改动：
1. "生成参考图"点击后 inline 展开角色描述输入区（不是 alert）
2. 输入区：textarea + views 多选（front/side/smile/full_body checkbox）+ 确认按钮
3. 提交后每个 view 位置显示骨架屏（`.skeleton`，1:1 比例）
4. 用 `useTaskPoller` 跟踪任务，done 后从 result 中提取 views URL 填充到对应位置
5. 图片卡片 hover：`transform: scale(1.05)` + 半透明遮罩显示 view 名称
6. 支持点击选中（边框高亮 `var(--glow-primary)`），为后续绑定到 shot 做准备

### 任务 7：index.vue 布局升级

核心改动：
1. onMounted 时设置 `document.documentElement.setAttribute('data-theme', 'dark')`
2. onUnmounted 时恢复原主题
3. 顶部 header：`position: sticky; top: 0; backdrop-filter: blur(12px); z-index: 10`
4. 两栏布局比例：`grid-template-columns: 5fr 7fr`（左窄右宽）
5. 项目 ID：改为 select + input 混合（可输入可选择），onMounted 时调 `listProjects()` 填充选项
6. 页面底部：全局进度条（当有任务 isPolling 时显示，用 `var(--gradient-progress)` + `.animate-progress`）

### 任务 8：AssetPool.vue 升级

核心改动：
1. 空状态：虚线边框区域 + 上传图标（SVG inline）+ "拖拽或点击上传"文字
2. 拖拽上传：`@dragover.prevent` + `@drop` 处理
3. 上传中：显示文件名 + 进度条
4. 图片网格：hover 显示半透明遮罩 + 操作按钮（删除、绑定）
5. 深色主题适配

## 视觉规范速查

```
背景色：#111827（页面）/ #1f2937（卡片）/ #374151（输入框）
文字色：#f9fafb（主）/ #9ca3af（次）
主色：#6366f1（按钮、高亮、glow）
成功：#10b981
警告：#f59e0b
错误：#ef4444
圆角：8px（小）/ 12px（卡片）/ 16px（大容器）
间距：8px / 12px / 16px / 24px
字号：12px（标签）/ 13px（正文）/ 14px（标题）/ 18px（页面标题）
```

## 验收

```bash
cd frontend && npm run build
```

编译通过 + 浏览器打开 `/director/produce` 视觉检查：
- 深色主题渲染正确
- 发送消息有"思考中"动画
- 分镜卡片有 hover 效果
- 参考图有骨架屏

## 注意事项

- **不要引入 element-plus 或任何 UI 库**，全部用原生 HTML + CSS
- **不要修改 `api/director.ts` 或 `api/workbench.ts`**，只 import 使用
- **不要修改 `composables/useDirectorSession.ts`**，只 import 使用
- 可以新增 CSS 类，但优先使用 fe-core 提供的动画工具类
