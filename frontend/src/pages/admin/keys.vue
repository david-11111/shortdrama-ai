<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Key Pool</p>
        <h1>Key Pool</h1>
      </div>
    </header>

    <div v-if="errorMessage" class="feedback error">{{ errorMessage }}</div>
    <div v-if="loading" class="panel">加载中...</div>

    <section v-else class="service-grid">
      <article v-for="service in serviceEntries" :key="service.name" class="panel">
        <div class="panel-head">
          <h2>{{ service.name }}</h2>
          <span>{{ service.items.length }} 个 Key</span>
        </div>

        <div class="key-list">
          <div v-for="item in service.items" :key="item.name" class="key-row" :class="{ cooling: isCooling(item.cooldown_until) }">
            <div class="key-top">
              <strong>{{ item.name }}</strong>
              <span>{{ item.rpm }} RPM</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: `${loadPercent(item.load, item.max_concurrency)}%` }"></div>
            </div>
            <div class="key-meta">
              <span>负载 {{ item.load }} / {{ item.max_concurrency }}</span>
              <span>{{ cooldownText(item.cooldown_until) }}</span>
            </div>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { adminApi, type KeyPoolItem } from '@/api/admin'

const services = ref<Record<string, KeyPoolItem[]>>({})
const loading = ref(true)
const errorMessage = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const serviceEntries = computed(() => Object.entries(services.value).map(([name, items]) => ({ name, items })))

onMounted(async () => {
  await loadPool()
  timer = setInterval(() => {
    void loadPool(false)
  }, 10000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function loadPool(showLoading = true) {
  if (showLoading) loading.value = true

  try {
    const { data } = await adminApi.keyPool()
    services.value = data.services
    errorMessage.value = ''
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载 Key Pool 失败'
  } finally {
    loading.value = false
  }
}

function loadPercent(load: number, maxConcurrency: number) {
  if (!maxConcurrency) return 0
  return Math.min(100, Math.round((load / maxConcurrency) * 100))
}

function isCooling(value: string | null) {
  return !!value && new Date(value).getTime() > Date.now()
}

function cooldownText(value: string | null) {
  if (!value) return '可用'
  if (!isCooling(value)) return '冷却结束'
  return `冷却至 ${new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
}
</script>

<style scoped>
.page-header {
  margin-bottom: 20px;
}

.page-kicker {
  margin: 0 0 8px;
  color: #3156d3;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

h1,
h2 {
  margin: 0;
}

.feedback.error {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fef3f2;
  color: #b42318;
}

.service-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.panel {
  padding: 20px;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-head span,
.key-meta {
  color: #64748b;
}

.key-list {
  display: grid;
  gap: 14px;
}

.key-row {
  padding: 14px;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  background: #f8fafc;
}

.key-row.cooling {
  border-color: #fca5a5;
  background: #fff1f2;
}

.key-top,
.key-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.key-top {
  margin-bottom: 10px;
}

.progress-bar {
  height: 8px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
  margin-bottom: 10px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3156d3, #6183ff);
}

@media (max-width: 960px) {
  .service-grid {
    grid-template-columns: 1fr;
  }
}
</style>
