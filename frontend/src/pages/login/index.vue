<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-head">
        <p class="auth-kicker">Welcome Back</p>
        <h1>登录</h1>
        <p class="auth-subtitle">登录后继续查看任务进度、积分余额和最近处理记录。</p>
      </div>

      <form class="auth-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label for="email">邮箱</label>
          <input
            id="email"
            v-model.trim="email"
            type="email"
            placeholder="your@email.com"
            required
            autocomplete="email"
            :disabled="loading"
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
            :disabled="loading"
          />
        </div>

        <p v-if="error" class="error-text" role="alert">{{ error }}</p>

        <button type="submit" class="btn-primary" :disabled="loading || !canSubmit">
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
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLoading } from '@/composables/useLoading'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { loading, error, run } = useLoading()

const email = ref('')
const password = ref('')

const canSubmit = computed(() => email.value.trim() !== '' && password.value.trim() !== '')

async function handleLogin() {
  if (!canSubmit.value) return

  await run(async () => {
    await authStore.login(email.value, password.value)
    const redirect = (route.query.redirect as string) || '/'
    // Prevent open redirect — only allow relative paths
    const safeRedirect = redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/'
    await router.push(safeRedirect)
  })
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-xl);
  background:
    radial-gradient(circle at top, color-mix(in srgb, var(--color-primary) 14%, transparent), transparent 32%),
    linear-gradient(180deg, var(--color-bg-secondary), var(--color-bg));
}

.auth-card {
  width: min(100%, 420px);
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--color-bg) 92%, transparent);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(14px);
}

.auth-head {
  margin-bottom: var(--space-lg);
}

.auth-kicker {
  margin: 0 0 var(--space-xs);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.auth-card h1 {
  margin: 0;
  font-size: 1.75rem;
}

.auth-subtitle {
  margin: var(--space-sm) 0 0;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.auth-form {
  display: grid;
  gap: var(--space-md);
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
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.form-group input::placeholder {
  color: color-mix(in srgb, var(--color-text-secondary) 80%, transparent);
}

.form-group input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-primary) 14%, transparent);
}

.form-group input:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.btn-primary {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  color: #fff;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, opacity 0.2s ease, filter 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  filter: brightness(1.05);
  transform: translateY(-1px);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-text {
  margin: 0;
  color: var(--color-error);
  font-size: 0.875rem;
}

.auth-link {
  margin: var(--space-lg) 0 0;
  text-align: center;
  font-size: 0.875rem;
  color: var(--color-text-secondary);
}

@media (max-width: 640px) {
  .auth-page {
    padding: var(--space-md);
  }

  .auth-card {
    padding: var(--space-lg);
  }
}
</style>
