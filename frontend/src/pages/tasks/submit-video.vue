<template>
  <div class="submit-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Video Gen</p>
        <h1>提交视频生成任务</h1>
        <p class="page-subtitle">输入描述词并设置时长与分辨率，系统会创建视频生成任务。</p>
      </div>
      <router-link to="/tasks" class="btn-back">返回任务列表</router-link>
    </header>

    <section class="form-card">
      <form class="submit-form" @submit.prevent="handleSubmit">
        <div class="form-group">
          <label for="prompt">提示词</label>
          <textarea
            id="prompt"
            v-model.trim="prompt"
            rows="6"
            placeholder="描述你希望生成的视频内容、镜头、风格和动作。"
            :disabled="loading"
          />
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label for="provider">生成引擎</label>
            <select id="provider" v-model="provider" :disabled="loading">
              <option value="seedance">Seedance (火山引擎)</option>
              <option value="kling">Kling 可灵 (快手)</option>
            </select>
          </div>

          <div class="form-group">
            <label for="duration">时长</label>
            <select id="duration" v-model="duration" :disabled="loading">
              <option v-for="item in durationOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </div>

          <div class="form-group">
            <label for="resolution">分辨率</label>
            <select id="resolution" v-model="resolution" :disabled="loading">
              <option value="720p">720p</option>
              <option value="1080p">1080p</option>
            </select>
          </div>
        </div>

        <p v-if="errorMessage" class="error-text" role="alert">
          {{ errorMessage }}
          <router-link v-if="errorMessage.includes('充值中心')" to="/recharge" class="upgrade-link">前往充值 →</router-link>
        </p>
        <p v-if="retryAfter > 0 && !errorMessage" class="hint-text">请求过于频繁，{{ retryAfter }} 秒后重试。</p>

        <button type="submit" class="btn-primary" :disabled="loading || retryAfter > 0 || !canSubmit">
          {{ loading ? '提交中...' : '提交视频任务' }}
        </button>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { tasksApi } from '@/api/tasks'

const router = useRouter()

const prompt = ref('')
const provider = ref<'seedance' | 'kling'>('seedance')
const duration = ref<number>(5)
const resolution = ref<'720p' | '1080p'>('720p')
const loading = ref(false)
const errorMessage = ref('')
const retryAfter = ref(0)

let retryTimer: ReturnType<typeof setInterval> | null = null

const canSubmit = computed(() => prompt.value.trim().length > 0)
const durationOptions = computed(() => {
  if (provider.value === 'kling') {
    return [
      { label: '5s', value: 5 },
      { label: '10s', value: 10 },
    ]
  }
  return [
    { label: '5s', value: 5 },
    { label: '8s', value: 8 },
    { label: '10s', value: 10 },
  ]
})

watch(provider, (value) => {
  if (value === 'kling' && duration.value === 8) {
    duration.value = 5
  }
})

function startRetryCountdown(seconds: number) {
  if (retryTimer) clearInterval(retryTimer)
  retryAfter.value = seconds

  retryTimer = setInterval(() => {
    if (retryAfter.value <= 1) {
      retryAfter.value = 0
      if (retryTimer) clearInterval(retryTimer)
      retryTimer = null
      return
    }
    retryAfter.value -= 1
  }, 1000)
}

async function handleSubmit() {
  if (!canSubmit.value || retryAfter.value > 0) return

  loading.value = true
  errorMessage.value = ''

  try {
    await tasksApi.submitVideos([
      {
        prompt: prompt.value,
        duration: duration.value,
        resolution: resolution.value,
        provider: provider.value,
      },
    ])

    sessionStorage.setItem('tasks_toast', '视频生成任务已提交')
    await router.push('/tasks')
  } catch (error: any) {
    const status = error?.response?.status

    if (status === 402) {
      errorMessage.value = '积分不足'
      return
    }

    if (status === 429) {
      const retryHeader = Number(error?.response?.headers?.['retry-after'] ?? 60)
      const detail = error?.response?.data?.detail
      const limit = detail?.limit
      const windowSec = detail?.window_seconds
      const retrySec = Number.isFinite(retryHeader) && retryHeader > 0 ? retryHeader : 60
      const retryText = retrySec >= 60 ? `${Math.ceil(retrySec / 60)} 分钟后` : `${retrySec} 秒后`
      if (detail?.error === 'Concurrent task limit exceeded') {
        errorMessage.value = `当前同时执行任务数已达上限（${limit} 个），请等待已有任务完成后再提交。可前往"充值中心"升级套餐解除限制。`
      } else if (limit && windowSec) {
        const windowText = windowSec === 3600 ? '每小时' : windowSec === 60 ? '每分钟' : `每 ${windowSec} 秒`
        errorMessage.value = `已达免费额度上限：${windowText} ${limit} 次视频生成，${retryText}恢复。可前往"充值中心"升级套餐。`
      } else {
        errorMessage.value = `请求过于频繁，${retryText}重试。`
      }
      startRetryCountdown(retrySec)
      return
    }

    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '提交失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onUnmounted(() => {
  if (retryTimer) clearInterval(retryTimer)
})
</script>

<style scoped>
.submit-page {
  max-width: 960px;
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

.form-card {
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.submit-form {
  display: grid;
  gap: var(--space-md);
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-md);
}

.form-group label {
  display: block;
  margin-bottom: var(--space-xs);
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.form-group textarea,
.form-group select {
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  font: inherit;
}

.form-group textarea {
  resize: vertical;
  min-height: 160px;
}

.form-group textarea:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-primary) 14%, transparent);
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
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-text {
  margin: 0;
  color: var(--color-error);
}

.hint-text {
  margin: 0;
  color: var(--color-text-secondary);
}

@media (max-width: 720px) {
  .submit-page {
    padding: var(--space-md);
  }

  .page-header,
  .grid-2 {
    grid-template-columns: 1fr;
    flex-direction: column;
  }

  .btn-back {
    width: 100%;
  }

  .form-card {
    padding: var(--space-lg);
  }
}
</style>
