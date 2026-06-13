<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">System</p>
        <h1>系统健康</h1>
      </div>
    </header>

    <div v-if="errorMessage" class="feedback error">{{ errorMessage }}</div>

    <section class="stats-grid">
      <article class="panel">
        <h2>数据库</h2>
        <div class="health-row">
          <span class="health-dot" :class="system?.database"></span>
          <strong>{{ system?.database || 'unknown' }}</strong>
        </div>
      </article>
      <article class="panel">
        <h2>Redis</h2>
        <div class="metric-list">
          <div class="metric-row"><span>当前内存</span><strong>{{ system?.redis.used_memory_human || '-' }}</strong></div>
          <div class="metric-row"><span>峰值内存</span><strong>{{ system?.redis.used_memory_peak_human || '-' }}</strong></div>
        </div>
      </article>
      <article class="panel">
        <h2>队列深度</h2>
        <div class="metric-list">
          <div v-for="queue in queueEntries" :key="queue.name" class="metric-row">
            <span>{{ queue.name }}</span>
            <strong>{{ queue.depth }}</strong>
          </div>
        </div>
      </article>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>限流配置</h2>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Tier</th>
              <th>资源</th>
              <th>窗口(秒)</th>
              <th>最大次数</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loadingRules">
              <td colspan="5" class="state-cell">加载中...</td>
            </tr>
            <tr v-for="rule in rules" :key="rule.id">
              <td>{{ rule.tier }}</td>
              <td>{{ rule.resource }}</td>
              <td>
                <input v-model.number="ruleEdits[rule.id].window_seconds" class="mini-input" type="number" min="1" />
              </td>
              <td>
                <input v-model.number="ruleEdits[rule.id].max_count" class="mini-input" type="number" min="1" />
              </td>
              <td>
                <button class="btn-primary" type="button" :disabled="savingRuleId === rule.id" @click="saveRule(rule.id)">
                  {{ savingRuleId === rule.id ? '保存中...' : '保存' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { adminApi, type RateLimitRule, type SystemResponse } from '@/api/admin'

const system = ref<SystemResponse | null>(null)
const rules = ref<RateLimitRule[]>([])
const ruleEdits = ref<Record<number, { window_seconds: number; max_count: number }>>({})
const loadingRules = ref(false)
const savingRuleId = ref<number | null>(null)
const errorMessage = ref('')

const queueEntries = computed(() => Object.entries(system.value?.queue_depth || {}).map(([name, depth]) => ({ name, depth })))

onMounted(async () => {
  await Promise.all([loadSystem(), loadRules()])
})

async function loadSystem() {
  try {
    const { data } = await adminApi.system()
    system.value = data
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载系统状态失败'
  }
}

async function loadRules() {
  loadingRules.value = true

  try {
    const { data } = await adminApi.rateLimits()
    rules.value = data.rules
    ruleEdits.value = Object.fromEntries(
      data.rules.map((rule) => [rule.id, { window_seconds: rule.window_seconds, max_count: rule.max_count }]),
    )
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载限流配置失败'
  } finally {
    loadingRules.value = false
  }
}

async function saveRule(ruleId: number) {
  savingRuleId.value = ruleId
  errorMessage.value = ''

  try {
    await adminApi.updateRateLimit(ruleId, ruleEdits.value[ruleId])
    await loadRules()
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '保存限流配置失败'
  } finally {
    savingRuleId.value = null
  }
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.panel {
  padding: 20px;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
}

.health-row,
.metric-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.metric-list {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.health-dot {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  display: inline-block;
  margin-right: 8px;
}

.health-dot.healthy {
  background: #12b76a;
}

.health-dot.unhealthy {
  background: #f04438;
}

.panel-head {
  margin-bottom: 16px;
}

.table-wrap {
  overflow-x: auto;
}

.table {
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 12px 8px;
  border-bottom: 1px solid #e5e7eb;
  text-align: left;
}

.table tbody tr:last-child td {
  border-bottom: none;
}

.mini-input {
  padding: 8px 10px;
  border: 1px solid #dbe2f0;
  border-radius: 10px;
  background: #fff;
}

.btn-primary {
  padding: 8px 12px;
  border: none;
  border-radius: 10px;
  background: #3156d3;
  color: #fff;
  cursor: pointer;
}

.state-cell {
  color: #64748b;
}

@media (max-width: 960px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
