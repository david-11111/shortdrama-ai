import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

/**
 * 生产构建时注入 CSP meta 标签。
 * 开发模式不注入，因为 Vite HMR 依赖内联脚本和 eval。
 *
 * 策略（与 Token 存储方案 C 配套）：
 * - script-src 'self'：禁止内联脚本，挡 XSS 主流注入路径
 * - object-src 'none' / frame-ancestors 'none'：防点击劫持/插件
 * - connect-src：允许同源 + WebSocket，部署到不同源时改这里
 * - img-src：允许 data: 和 https:（产品里有 base64 占位图、外部生成的图片 URL）
 */
const PROD_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "media-src 'self' blob: https:",
  "font-src 'self' data:",
  "connect-src 'self' ws: wss:",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
].join('; ')

function cspPlugin() {
  return {
    name: 'inject-csp-meta',
    transformIndexHtml: {
      order: 'post' as const,
      handler(html: string, ctx: { server?: unknown }) {
        if (ctx.server) return html  // dev 模式跳过
        const meta = `    <meta http-equiv="Content-Security-Policy" content="${PROD_CSP}" />\n`
        return html.replace(/<\/head>/, `${meta}  </head>`)
      },
    },
  }
}

export default defineConfig({
  plugins: [vue(), cspPlugin()],
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
        timeout: 120000,
        proxyTimeout: 120000,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        timeout: 120000,
      },
    },
  },
})
