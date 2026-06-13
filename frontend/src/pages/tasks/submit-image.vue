<template>
  <div class="submit-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Image Gen</p>
        <h1>提交图片生成任务</h1>
        <p class="page-subtitle">设置风格与尺寸后提交图片生成请求，任务会进入队列并可实时查看进度。</p>
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
            placeholder="描述画面主体、氛围、构图和风格。"
            :disabled="loading"
          />
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label for="style">风格</label>
            <select id="style" v-model="style" :disabled="loading">
              <option value="default">default</option>
              <option value="anime">anime</option>
              <option value="realistic">realistic</option>
              <option value="oil-painting">oil-painting</option>
            </select>
          </div>

          <div class="form-group">
            <label for="size">尺寸</label>
            <select id="size" v-model="size" :disabled="loading">
              <option value="512x512">512x512</option>
              <option value="1024x1024">1024x1024</option>
            </select>
          </div>
        </div>

        <p v-if="errorMessage" class="error-text" role="alert">
          {{ errorMessage }}
          <router-link v-if="errorMessage.includes('充值中心')" to="/recharge" class="upgrade-link">前往充值 →</router-link>
        </p>
        <p v-if="retryAfter > 0 && !errorMessage" class="hint-text">请求过于频繁，{{ retryAfter }} 秒后重试。</p>

        <button type="submit" class="btn-primary" :disabled="loading || retryAfter > 0 || !canSubmit">
          {{ loading ? '提交中...' : '提交图片任务' }}
        </button>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { tasksApi } from '@/api/tasks'

type ImageStyle = 'default' | 'anime' | 'realistic' | 'oil-painting'
type ImageSize = '512x512' | '1024x1024'

const router = useRouter()

const prompt = ref('')
const style = ref<ImageStyle>('default')
const size = ref<ImageSize>('1024x1024')
const loading = ref(false)
const errorMessage = ref('')
const retryAfter = ref(0)

let retryTimer: ReturnType<typeof setInterval> | null = null

const canSubmit = computed(() => prompt.value.trim().length > 0)

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

function getDimensions(value: ImageSize) {
  const [width, height] = value.split('x').map(Number)
  return { width, height }
}

async function handleSubmit() {
  if (!canSubmit.value || retryAfter.value > 0) return

  loading.value = true
  errorMessage.value = ''

  try {
    const { width, height } = getDimensions(size.value)
    await tasksApi.submitImages([
      {
        prompt: prompt.value,
        style: style.value,
        width,
        height,
      },
    ])

    sessionStorage.setItem('tasks_toast', '图片生成任务已提交')
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
        errorMessage.value = `已达免费额度上限：${windowText} ${limit} 张图片生成，${retryText}恢复。可前往"充值中心"升级套餐。`
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
