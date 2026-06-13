<template>
  <div class="settings-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Settings</p>
        <h1>设置</h1>
        <p class="page-subtitle">查看账户信息，管理 API Key，并控制每日积分消耗风险。</p>
      </div>
      <router-link to="/" class="btn-back">返回仪表盘</router-link>
    </header>

    <section class="settings-grid">
      <article class="settings-card">
        <div class="card-head">
          <div>
            <h2>账户信息</h2>
            <p>当前登录账户的基础资料与积分概览。</p>
          </div>
        </div>

        <div v-if="profileLoading" class="state-text">加载中...</div>
        <div v-else class="info-list">
          <div class="info-row">
            <span class="info-label">邮箱</span>
            <span class="info-value">{{ authStore.user?.email || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">套餐等级</span>
            <span class="info-value">
              <span class="tier-badge">{{ authStore.user?.tier || 'free' }}</span>
            </span>
          </div>
          <div class="info-row">
            <span class="info-label">注册时间</span>
            <span class="info-value">{{ authStore.user?.created_at ? formatTime(authStore.user.created_at) : '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">积分余额</span>
            <span class="info-value">{{ credits.balance }}</span>
          </div>
        </div>
      </article>

      <article class="settings-card">
        <div class="card-head limit-head">
          <div>
            <h2>每日消费限额</h2>
            <p>限制当天最多可消耗的积分，避免异常任务把账户余额一次性烧完。</p>
          </div>
          <span class="status-pill" :class="{ danger: spendLimit?.blocked }">
            {{ spendLimit?.blocked ? '已触发限额' : '运行中' }}
          </span>
        </div>

        <div v-if="limitLoading" class="state-text">加载中...</div>
        <form v-else class="limit-form" @submit.prevent="saveSpendLimit">
          <div class="limit-stats">
            <div class="limit-stat">
              <span>今日已用</span>
              <strong>{{ spendLimit?.credits_consumed ?? 0 }}</strong>
            </div>
            <div class="limit-stat">
              <span>今日剩余</span>
              <strong>{{ spendLimit?.is_unlimited ? '不限额' : spendLimit?.credits_remaining ?? 0 }}</strong>
            </div>
            <div class="limit-stat">
              <span>系统默认</span>
              <strong>{{ spendLimit?.default_daily_credit_limit ?? 1000 }}</strong>
            </div>
          </div>

          <label class="toggle-row">
            <input v-model="limitUnlimited" type="checkbox" />
            <span>
              <strong>不限额</strong>
              <small>只关闭个人每日限额；平台总风控仍然生效。</small>
            </span>
          </label>

          <div class="form-group">
            <label for="dailyLimit">每日最多消耗积分</label>
            <input
              id="dailyLimit"
              v-model.number="limitValue"
              type="number"
              min="1"
              max="1000000"
              step="1"
              :disabled="limitUnlimited || savingLimit"
            />
          </div>

          <div class="form-actions">
            <button type="submit" class="btn-primary" :disabled="savingLimit || (!limitUnlimited && !limitValue)">
              {{ savingLimit ? '保存中...' : '保存限额' }}
            </button>
            <button type="button" class="btn-refresh" :disabled="limitLoading || savingLimit" @click="loadSpendLimit">
              刷新
            </button>
          </div>
          <p class="hint-text">保存后，新提交的生成、优化、TTS 等扣费任务会按这个限额拦截。</p>
        </form>
      </article>

      <article class="settings-card">
        <div class="card-head">
          <div>
            <h2>API Key 管理</h2>
            <p>创建新的访问凭证，并管理现有 key。</p>
          </div>
        </div>

        <form class="create-form" @submit.prevent="handleCreateKey">
          <div class="form-group">
            <label for="keyName">名称</label>
            <input
              id="keyName"
              v-model.trim="keyName"
              type="text"
              placeholder="例如：CI Runner / 本地脚本"
              :disabled="creating"
            />
          </div>
          <button type="submit" class="btn-primary" :disabled="creating || keyName.length === 0">
            {{ creating ? '创建中...' : '创建 API Key' }}
          </button>
        </form>

        <p v-if="errorMessage" class="error-text" role="alert">{{ errorMessage }}</p>
        <p v-if="successMessage" class="success-text" role="status">{{ successMessage }}</p>

        <section v-if="createdKey" class="created-key-panel">
          <div class="created-key-head">
            <strong>新建成功</strong>
            <button type="button" class="btn-copy" @click="copyCreatedKey">
              {{ copied ? '已复制' : '复制' }}
            </button>
          </div>
          <p class="created-key-note">此 key 仅显示一次，请立即保存。</p>
          <code class="created-key-value">{{ createdKey }}</code>
        </section>

        <div class="list-head">
          <h3>已有 Key</h3>
          <button type="button" class="btn-refresh" :disabled="keysLoading" @click="loadKeys">
            {{ keysLoading ? '刷新中...' : '刷新' }}
          </button>
        </div>

        <div v-if="keysLoading" class="state-text">加载中...</div>
        <div v-else-if="keys.length === 0" class="state-text">暂无 API Key</div>
        <div v-else class="key-list">
          <div v-for="item in keys" :key="item.key_id" class="key-row">
            <div class="key-main">
              <strong>{{ item.name }}</strong>
              <span class="key-meta">{{ formatTime(item.created_at) }}</span>
              <code class="key-id">{{ item.key_id }}</code>
            </div>
            <button
              type="button"
              class="btn-danger"
              :disabled="revokingId === item.key_id"
              @click="handleRevoke(item.key_id)"
            >
              {{ revokingId === item.key_id ? '撤销中...' : '撤销' }}
            </button>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import client from '@/api/client'
import { keysApi } from '@/api/keys'
import { useAuthStore } from '@/stores/auth'
import type { ApiKey } from '@/types/api'

interface CreditsSummary {
  balance: number
  lifetime_earned: number
  lifetime_spent: number
}

interface SpendLimit {
  user_id: number
  daily_credit_limit: number | null
  configured_daily_credit_limit: number | null
  default_daily_credit_limit: number
  is_unlimited: boolean
  credits_consumed: number
  credits_remaining: number | null
  blocked: boolean
  limit_updated_at: string | null
}

const authStore = useAuthStore()

const credits = ref<CreditsSummary>({
  balance: 0,
  lifetime_earned: 0,
  lifetime_spent: 0,
})

const spendLimit = ref<SpendLimit | null>(null)
const limitValue = ref<number | null>(null)
const limitUnlimited = ref(false)
const limitLoading = ref(false)
const savingLimit = ref(false)

const keyName = ref('')
const createdKey = ref('')
const copied = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const keys = ref<ApiKey[]>([])
const creating = ref(false)
const keysLoading = ref(false)
const profileLoading = ref(false)
const revokingId = ref<string | null>(null)

onMounted(async () => {
  await Promise.all([loadProfile(), loadKeys(), loadSpendLimit()])
})

async function loadProfile() {
  profileLoading.value = true

  try {
    if (!authStore.user) {
      await authStore.fetchUser()
    }

    const { data } = await client.get<CreditsSummary>('/credits')
    credits.value = data
  } catch (error: any) {
    errorMessage.value = toErrorMessage(error, '加载账户信息失败')
  } finally {
    profileLoading.value = false
  }
}

async function loadSpendLimit() {
  limitLoading.value = true

  try {
    const { data } = await client.get<SpendLimit>('/credits/spend-limit')
    spendLimit.value = data
    limitUnlimited.value = data.is_unlimited
    limitValue.value = data.daily_credit_limit ?? data.default_daily_credit_limit
  } catch (error: any) {
    errorMessage.value = toErrorMessage(error, '加载消费限额失败')
  } finally {
    limitLoading.value = false
  }
}

async function saveSpendLimit() {
  savingLimit.value = true
  errorMessage.value = ''
  successMessage.value = ''

  try {
    const payload = {
      is_unlimited: limitUnlimited.value,
      daily_credit_limit: limitUnlimited.value ? null : Number(limitValue.value),
    }
    const { data } = await client.put<SpendLimit>('/credits/spend-limit', payload)
    spendLimit.value = data
    limitUnlimited.value = data.is_unlimited
    limitValue.value = data.daily_credit_limit ?? data.default_daily_credit_limit
    successMessage.value = '每日消费限额已保存'
  } catch (error: any) {
    errorMessage.value = toErrorMessage(error, '保存消费限额失败')
  } finally {
    savingLimit.value = false
  }
}

async function loadKeys() {
  keysLoading.value = true

  try {
    const { data } = await keysApi.list()
    keys.value = data.keys
  } catch (error: any) {
    errorMessage.value = toErrorMessage(error, '加载 API Key 失败')
  } finally {
    keysLoading.value = false
  }
}

async function handleCreateKey() {
  if (keyName.value.length === 0) return

  creating.value = true
  copied.value = false
  errorMessage.value = ''
  successMessage.value = ''

  try {
    const { data } = await keysApi.create(keyName.value)
    createdKey.value = data.api_key || ''
    keyName.value = ''
    await loadKeys()
  } catch (error: any) {
    errorMessage.value = toErrorMessage(error, '创建 API Key 失败')
  } finally {
    creating.value = false
  }
}

async function copyCreatedKey() {
  if (!createdKey.value) return

  try {
    await navigator.clipboard.writeText(createdKey.value)
    copied.value = true
  } catch {
    errorMessage.value = '复制失败，请手动复制'
  }
}

async function handleRevoke(keyId: string) {
  const confirmed = window.confirm('确定要撤销这个 API Key 吗？此操作不可恢复。')
  if (!confirmed) return

  revokingId.value = keyId
  errorMessage.value = ''
  successMessage.value = ''

  try {
    await keysApi.revoke(keyId)
    if (createdKey.value && keys.value.some((item) => item.key_id === keyId)) {
      copied.value = false
    }
    await loadKeys()
  } catch (error: any) {
    errorMessage.value = toErrorMessage(error, '撤销 API Key 失败')
  } finally {
    revokingId.value = null
  }
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function toErrorMessage(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return error?.message ?? fallback
}
</script>

<style scoped>
.settings-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-xl);
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-lg);
  align-items: flex-start;
  margin-bottom: var(--space-lg);
}

.page-kicker {
  margin: 0 0 var(--space-xs);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.page-header h1 {
  margin: 0;
  font-size: 2rem;
}

.page-subtitle {
  margin: var(--space-sm) 0 0;
  color: var(--color-text-secondary);
}

.btn-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text-secondary);
}

.settings-grid {
  display: grid;
  gap: var(--space-lg);
}

.settings-card {
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.card-head {
  margin-bottom: var(--space-lg);
}

.limit-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  align-items: flex-start;
}

.card-head h2 {
  margin: 0;
  font-size: 1.25rem;
}

.card-head p {
  margin: var(--space-xs) 0 0;
  color: var(--color-text-secondary);
}

.status-pill {
  flex: 0 0 auto;
  padding: 5px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-success) 14%, var(--color-bg));
  color: var(--color-success);
  font-size: 0.75rem;
  font-weight: 700;
}

.status-pill.danger {
  background: color-mix(in srgb, var(--color-error) 12%, var(--color-bg));
  color: var(--color-error);
}

.info-list,
.limit-form,
.create-form {
  display: grid;
  gap: var(--space-md);
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  padding-bottom: var(--space-sm);
  border-bottom: 1px solid var(--color-border);
}

.info-row:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.info-label,
.limit-stat span,
.hint-text {
  color: var(--color-text-secondary);
}

.info-value {
  text-align: right;
}

.tier-badge {
  display: inline-flex;
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 15%, transparent);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.limit-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-md);
}

.limit-stat {
  display: grid;
  gap: 6px;
  min-height: 82px;
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 55%, var(--color-bg));
}

.limit-stat strong {
  font-size: 1.35rem;
}

.toggle-row {
  display: flex;
  gap: var(--space-md);
  align-items: center;
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
}

.toggle-row input {
  width: 18px;
  height: 18px;
}

.toggle-row span {
  display: grid;
  gap: 3px;
}

.toggle-row small {
  color: var(--color-text-secondary);
}

.form-group label {
  display: block;
  margin-bottom: var(--space-xs);
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.form-group input {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  font: inherit;
}

.form-group input:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.form-group input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-primary) 14%, transparent);
}

.form-actions {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
}

.btn-primary {
  justify-self: start;
  padding: var(--space-sm) var(--space-lg);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:disabled,
.btn-refresh:disabled,
.btn-danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.created-key-panel {
  margin-top: var(--space-lg);
  padding: var(--space-lg);
  border: 1px solid color-mix(in srgb, var(--color-primary) 24%, var(--color-border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-primary) 10%, var(--color-bg));
}

.created-key-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  align-items: center;
}

.created-key-note {
  margin: var(--space-sm) 0;
  color: var(--color-text-secondary);
}

.created-key-value,
.key-id {
  display: block;
  font-family: Consolas, 'SFMono-Regular', Monaco, monospace;
  word-break: break-all;
}

.created-key-value {
  padding: var(--space-md);
  border-radius: var(--radius-md);
  background: var(--color-bg);
}

.btn-copy,
.btn-refresh {
  padding: 6px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.list-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  align-items: center;
  margin-top: var(--space-lg);
  margin-bottom: var(--space-md);
}

.list-head h3 {
  margin: 0;
  font-size: 1rem;
}

.key-list {
  display: grid;
  gap: var(--space-md);
}

.key-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-md);
  align-items: flex-start;
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 55%, var(--color-bg));
}

.key-main {
  display: grid;
  gap: 4px;
}

.key-meta {
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.btn-danger {
  padding: 6px 12px;
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-error);
  cursor: pointer;
}

.error-text {
  margin: var(--space-md) 0 0;
  color: var(--color-error);
}

.success-text {
  margin: var(--space-md) 0 0;
  color: var(--color-success);
}

.state-text {
  color: var(--color-text-secondary);
}

@media (max-width: 720px) {
  .settings-page {
    padding: var(--space-md);
  }

  .page-header,
  .info-row,
  .created-key-head,
  .key-row,
  .list-head,
  .limit-head,
  .form-actions {
    flex-direction: column;
    align-items: flex-start;
  }

  .limit-stats {
    grid-template-columns: 1fr;
  }

  .btn-back,
  .btn-primary,
  .btn-danger,
  .btn-refresh {
    width: 100%;
  }

  .info-value {
    text-align: left;
  }

  .settings-card {
    padding: var(--space-lg);
  }
}
</style>
