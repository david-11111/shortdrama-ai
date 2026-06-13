# Token 存储方案评估（P8-FEC-5）

> fe-core 产出，交 orchestrator + api-auth + security 三方决策。
> 当前实现：access/refresh 双 Token 均存 `localStorage`，前端手动 Authorization header。

---

## 方案对比

### 方案 A：保留现状（localStorage + Bearer）

Access Token + Refresh Token 都放在 `localStorage`，axios 请求拦截器手动注入 `Authorization: Bearer <token>`。

**优点**
- 零后端改动；`/auth/login` 返回 JSON 即可。
- CSRF 天然免疫（浏览器不会自动把 Token 发到跨域）。
- 跨子域、原生应用、SDK 调用都能直接复用同一套 Token。
- 便于前端做 Token 刷新、跨 tab 同步（storage 事件）。

**缺点**
- 任意 XSS 即可窃 Token。攻击者拿到 Refresh Token 可无限续命。
- 无法用浏览器 `HttpOnly`、`Secure`、`SameSite` 这些标志位做兜底保护。
- 第三方脚本（埋点、AB 测试、支付 SDK）都有读 `localStorage` 的能力，供应链风险高。

**已做缓解**
- axios 请求拦截器统一注入，未落地到 URL。
- `useWebSocket` 已在 Token 变化时自动重连（P8-FEC-1）。

### 方案 B：HttpOnly Cookie（推荐）

Access Token + Refresh Token 都写到 `HttpOnly; Secure; SameSite=Strict` Cookie 里，浏览器自动带上。前端不再手动管 Token。

**优点**
- JS 读不到 Token，XSS 只能借当前会话发请求，无法导出 Token。
- `SameSite=Strict` 让 CSRF 基本不用额外防御（绝大多数跨站发起的写请求会被浏览器拦下）。
- 前端代码显著简化：删掉 `accessToken` 状态、请求拦截器注入、刷新队列大半的代码。

**缺点**
- 后端要开发：`Set-Cookie` 流程、登出清 Cookie、刷新 Token 时原子化轮换、跨域 Cookie（前后端不同源时）。
- 开发环境 Vite dev server 代理要配 `cookieDomainRewrite`。
- **WebSocket 鉴权要换模型**：当前 `/ws/tasks?token=...` 在 URL 里传 Token。Cookie 场景需要服务端直接从 `Sec-WebSocket-Protocol` 或握手 Cookie 里取 session，后端要配套改。
- 原生 App / 桌面端复用时要走一套不同的鉴权（Bearer），可能造成双轨。
- 需要配 CSRF Token（即便 SameSite=Strict，POST/PUT/DELETE 接口建议再加一道 `X-CSRF-Token`）。

**所需改造清单**
1. 后端 `/auth/login`、`/auth/register`、`/auth/refresh`：`Set-Cookie`，不再返回 Token 到 body。
2. 后端 `/auth/logout`：`Set-Cookie` 空值 + Max-Age=0。
3. 后端中间件从 Cookie 取 Token（`access_token` cookie）→ 兼容 `Authorization` 头（SDK / App）。
4. 前端 axios：`withCredentials: true`，删掉 Token 注入和 localStorage 读写。
5. WebSocket：服务端从 `request.cookies` 取 Token；前端不再拼 querystring，直接连 `/ws/tasks`。
6. CSRF：POST/PUT/DELETE/PATCH 接口要求 `X-CSRF-Token` 头；登录响应下发一个可读 Cookie（非 HttpOnly）`csrf_token` 供前端读取并回填。
7. 跨域部署场景确认：如果前端部署在 `app.example.com`，后端在 `api.example.com`，Cookie `Domain=.example.com`；否则 `SameSite=Lax` 会挡住 WebSocket 首帧。

### 方案 C：localStorage + 严格 CSP

保留 localStorage，用内容安全策略收缩 XSS 攻击面。

**必备 CSP**
- `script-src 'self'`，禁止 `'unsafe-inline'`、`'unsafe-eval'`。
- `connect-src 'self' https://api.example.com wss://api.example.com`。
- `frame-ancestors 'none'`。
- 显式 nonce 化所有内联脚本；Vue 默认不产生内联，但第三方库（支付、埋点）需要逐个审。
- Access Token TTL ≤ 15 分钟，Refresh Token 存 `sessionStorage`（仅当前标签页）+ 服务端刷新时轮换。

**优点**
- 改动成本小：前端改 CSP 头 + Token 生命周期；后端加 Refresh Token 轮换。
- 可与方案 B 叠加（纵深防御）。

**缺点**
- 依赖开发自律：一旦有人 `v-html` 用户内容、加 `'unsafe-inline'` 例外，防线就破。
- Vite dev server 的 HMR 用到内联脚本，生产/开发 CSP 会分两套，容易出现"开发正常生产挂"。
- XSS 仍可在窗口期内偷当前 Token 冒充用户调接口，只是阻断了永久凭证泄露。

---

## 风险对比矩阵

| 风险 | 方案 A | 方案 B | 方案 C |
|------|--------|--------|--------|
| XSS 导出 Refresh Token | 高 | 无 | 低 |
| XSS 冒充当前会话 | 高 | 中（仅发当前标签页请求） | 中 |
| CSRF | 无 | 低（SameSite+CSRF Token） | 无 |
| 供应链脚本读 Token | 高 | 无 | 低 |
| 改造工作量 | 0 | 高（前后端 + WS） | 中（CSP 审） |
| 多端复用 | 好 | 需双轨 | 好 |

---

## fe-core 建议

**短期（本期 Phase 8）**：
- 维持 localStorage，但叠加 CSP（方案 C）作为过渡。同时落实：
  - Access Token TTL 收紧到 15 分钟，服务端维护可失效的 jti 列表（已有 P8-SEC-4 Token 黑名单）。
  - Refresh Token 轮换：每次刷新后旧 Refresh 立即作废（api-auth 配合）。
  - 生产 CSP 固定为 `script-src 'self'`，接受 Vite dev 与生产模式差异。
  - 不新引入任何第三方脚本库到生产 bundle（支付二维码用库而非第三方脚本）。
- 成本：fe-core ≤ 0.5 天（配 CSP）+ api-auth 2 天（Refresh 轮换）+ security 跟进黑名单联调。

**中期（Phase 9 计划）**：
- 切换到 HttpOnly Cookie（方案 B）。时间点建议放在 WebSocket 重构之后，避免一次性改动过大。
- 负责人拆分：
  - api-auth：Set-Cookie / Clear-Cookie / Refresh 轮换。
  - security：CSRF Token 中间件、Cookie 属性审计。
  - fe-core：axios `withCredentials`，下线 localStorage，Router 守卫改用 `/auth/me` 探活。
  - api-biz + worker：WebSocket 服务端从 Cookie 取 Token，不再接受 URL Token。
- 成本：3 个终端各 2–3 天；qa 2 天做双轨兼容测试（迁移期需要 Cookie 与 Bearer 同时被接受）。

**不推荐**：
- 永远停留在方案 A。XSS 防不住，Refresh Token 一旦泄漏代价是永久权限。
- 直接跳过 C 冲 B。期间 WebSocket、SDK、原生端会全线拥堵，且没有 CSRF 框架铺垫。

## 需 orchestrator 决策的事项

1. Phase 8 是否采纳"方案 C 临时落地 + CSP 头"，若是 fe-core 起分支 `fe-core/phase8-csp`。
2. Phase 9 是否立项"Cookie 切换"，若是请在 `state.md` 开新任务组并分派 api-auth + security 前置调研。
3. WebSocket Token 传递方式：是否同意 Phase 9 将 URL Token 改为 Cookie（影响 `/ws/tasks` 所有消费者）。

---

_产出时间：2026-05-12_
_作者：fe-core 终端_
