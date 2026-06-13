import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import toast from './plugins/toast'
import { onAuthExpired } from './api/authEvents'
import './styles/global.css'
import './styles/animations.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(toast)

// 全局 Vue 渲染异常捕获
app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue global error]', err, info)
  // 尽量不吞异常，保证错误可见
}

// 刷新 Token 失败 ⇒ client.ts 发出 auth-expired 事件，由此统一跳登录页
onAuthExpired(() => {
  const current = router.currentRoute.value
  if (current.name === 'login') return
  router.replace({ name: 'login', query: { redirect: current.fullPath } })
})

app.mount('#app')
