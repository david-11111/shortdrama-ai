# T14 指令 — fe-pages 终端

## 你的身份

你是 `fe-pages` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 前置条件

- 后端 API Key 端点已就绪：
  - `POST /api/keys` — 创建（body: `{ name: string }`，返回含 `api_key` 字段，仅此一次可见）
  - `GET /api/keys` — 列出（返回 `{ keys: [{ key_id, name, created_at }] }`）
  - `DELETE /api/keys/{key_id}` — 撤销
- 前端类型 `@/types/api.ts` 已有 `ApiKey` 接口
- 路由守卫已就绪

## 任务目标

创建 **设置页面**，包含：
1. API Key 管理（创建、列表、撤销）
2. 账户信息展示

## 分支

```bash
git checkout -b fe/phase4-settings-page
```
（如果 git 报错可忽略，直接在当前分支工作）

## 需要创建/修改的文件

### 1. `frontend/src/api/keys.ts`（新建）

```typescript
import client from './client'
import type { ApiKey } from '@/types/api'

interface ApiKeyListResponse {
  keys: ApiKey[]
}

export const keysApi = {
  list() {
    return client.get<ApiKeyListResponse>('/keys')
  },

  create(name: string) {
    return client.post<ApiKey>('/keys', { name })
  },

  revoke(keyId: string) {
    return client.delete(`/keys/${keyId}`)
  },
}
```

### 2. `frontend/src/pages/settings/index.vue`（新建）

设置页面，包含两个区块：

**账户信息区块：**
- 显示邮箱、套餐等级、注册时间
- 积分余额（从 `/api/credits` 获取）

**API Key 管理区块：**
- 创建表单：名称输入框 + 创建按钮
- 创建成功后显示完整 key（带复制按钮），提示"此 key 仅显示一次"
- Key 列表：显示 name、created_at、撤销按钮
- 撤销前弹确认对话框

**样式要求：**
- 复用现有 CSS 变量
- 卡片式布局，每个区块一个卡片
- API Key 显示用 `font-family: monospace`
- 撤销按钮用红色（`--color-error`）

### 3. 更新 `frontend/src/router/index.ts`

在 tasks/:id 路由之后添加：

```typescript
{
  path: '/settings',
  name: 'settings',
  component: () => import('@/pages/settings/index.vue'),
  meta: { requiresAuth: true, title: 'Settings' },
},
```

### 4. 更新 `frontend/src/pages/dashboard/index.vue`

在 user-panel 区域添加设置入口（在退出按钮前）：

```html
<router-link to="/settings" class="btn-text">设置</router-link>
```

## 验收标准

1. `/settings` 页面能显示账户信息
2. 能创建 API Key 并显示完整 key（仅一次）
3. 能列出已有的 API Key
4. 能撤销 API Key（带确认）
5. Dashboard 有设置入口
6. 路由守卫正常

## 完成后

告诉 orchestrator：T14 完成，列出创建/修改的文件清单。
