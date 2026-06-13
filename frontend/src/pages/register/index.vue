<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-head">
        <p class="auth-kicker">Create Account</p>
        <h1>注册</h1>
        <p class="auth-subtitle">创建账户后即可进入仪表盘，查看额度并追踪任务执行状态。</p>
      </div>

      <form class="auth-form" @submit.prevent="handleRegister">
        <div class="form-group">
          <label for="displayName">昵称（可选）</label>
          <input
            id="displayName"
            v-model.trim="displayName"
            type="text"
            placeholder="你的昵称"
            autocomplete="nickname"
            :disabled="loading"
          />
        </div>

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
            minlength="8"
            autocomplete="new-password"
            :disabled="loading"
          />
        </div>

        <div class="form-group">
          <label for="confirmPassword">确认密码</label>
          <input
            id="confirmPassword"
            v-model="confirmPassword"
            type="password"
            placeholder="再次输入密码"
            required
            autocomplete="new-password"
            :disabled="loading"
          />
        </div>

        <p v-if="error" class="error-text" role="alert">{{ error }}</p>
        <p v-if="mismatch" class="error-text" role="alert">两次密码不一致</p>

        <button type="submit" class="btn-primary" :disabled="loading || mismatch || !canSubmit">
          {{ loading ? '注册中...' : '注册' }}
        </button>
      </form>

      <p class="auth-link">
        已有账号？<router-link to="/login">登录</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useLoading } from '@/composables/useLoading'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const { loading, error, run } = useLoading()

const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const displayName = ref('')

const mismatch = computed(() => confirmPassword.value !== '' && password.value !== confirmPassword.value)
const canSubmit = computed(() => email.value.trim() !== '' && password.value.length >= 8)

async function handleRegister() {
  if (mismatch.value || !canSubmit.value) return

  await run(async () => {
    await authStore.register(email.value, password.value, displayName.value || undefined)
    await router.push('/')
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
