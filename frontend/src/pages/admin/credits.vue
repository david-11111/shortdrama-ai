<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Revenue</p>
        <h1>积分与收入</h1>
      </div>
    </header>

    <section class="toolbar">
      <select v-model="days" class="input" @change="loadRevenue">
        <option :value="7">最近 7 天</option>
        <option :value="30">最近 30 天</option>
        <option :value="90">最近 90 天</option>
      </select>
    </section>

    <div v-if="errorMessage" class="feedback error">{{ errorMessage }}</div>

    <section class="panel">
      <div class="panel-head">
        <h2>日收入趋势</h2>
      </div>
      <div v-if="loadingRevenue" class="state-block">加载中...</div>
      <div v-else-if="dailyRevenue.length === 0" class="state-block">暂无收入数据</div>
      <div v-else class="chart-list">
        <div v-for="item in dailyRevenue" :key="item.date" class="chart-row">
          <span class="chart-date">{{ item.date }}</span>
          <div class="chart-bar">
            <div class="chart-fill" :style="{ width: `${barWidth(item.revenue)}%` }"></div>
          </div>
          <strong class="chart-value">{{ item.revenue }}</strong>
          <span class="chart-meta">{{ item.transactions }} 笔</span>
        </div>
      </div>
    </section>

    <section class="grid-2">
      <article class="panel">
        <div class="panel-head">
          <h2>Top 10 消费者</h2>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>邮箱</th>
                <th>套餐</th>
                <th>累计消费</th>
                <th>余额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in topSpenders" :key="item.id">
                <td>{{ item.email }}</td>
                <td>{{ item.tier }}</td>
                <td>{{ item.lifetime_spent }}</td>
                <td>{{ item.balance }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head">
          <h2>定价管理</h2>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>操作</th>
                <th>价格</th>
                <th>启用</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loadingPricing">
                <td colspan="4" class="state-cell">加载中...</td>
              </tr>
              <tr v-for="item in pricing" :key="item.id">
                <td>{{ item.operation }}</td>
                <td>
                  <input v-model.number="pricingEdits[item.id].credits_cost" class="mini-input" type="number" min="0" />
                </td>
                <td>
                  <input v-model="pricingEdits[item.id].active" type="checkbox" />
                </td>
                <td>
                  <button class="btn-primary" type="button" :disabled="savingPricingId === item.id" @click="savePricing(item.id)">
                    {{ savingPricingId === item.id ? '保存中...' : '保存' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { adminApi, type PricingRule, type RevenuePoint, type TopSpender } from '@/api/admin'

const days = ref(30)
const dailyRevenue = ref<RevenuePoint[]>([])
const topSpenders = ref<TopSpender[]>([])
const pricing = ref<PricingRule[]>([])
const pricingEdits = ref<Record<number, { credits_cost: number; active: boolean }>>({})
const loadingRevenue = ref(false)
const loadingPricing = ref(false)
const savingPricingId = ref<number | null>(null)
const errorMessage = ref('')

const maxRevenue = computed(() => Math.max(...dailyRevenue.value.map((item) => item.revenue), 1))

onMounted(async () => {
  await Promise.all([loadRevenue(), loadPricing()])
})

async function loadRevenue() {
  loadingRevenue.value = true
  errorMessage.value = ''

  try {
    const { data } = await adminApi.revenue(days.value)
    dailyRevenue.value = [...data.daily_revenue].reverse()
    topSpenders.value = data.top_spenders
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载收入失败'
  } finally {
    loadingRevenue.value = false
  }
}

async function loadPricing() {
  loadingPricing.value = true

  try {
    const { data } = await adminApi.pricing()
    pricing.value = data.pricing
    pricingEdits.value = Object.fromEntries(
      data.pricing.map((item) => [item.id, { credits_cost: item.credits_cost, active: item.active }]),
    )
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载定价失败'
  } finally {
    loadingPricing.value = false
  }
}

async function savePricing(pricingId: number) {
  savingPricingId.value = pricingId
  errorMessage.value = ''

  try {
    await adminApi.updatePricing(pricingId, pricingEdits.value[pricingId])
    await loadPricing()
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '保存定价失败'
  } finally {
    savingPricingId.value = null
  }
}

function barWidth(value: number) {
  return Math.round((value / maxRevenue.value) * 100)
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

.toolbar {
  margin-bottom: 16px;
}

.input,
.mini-input {
  padding: 10px 12px;
  border: 1px solid #dbe2f0;
  border-radius: 12px;
  background: #fff;
}

.feedback.error {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fef3f2;
  color: #b42318;
}

.panel {
  padding: 20px;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
}

.panel + .panel,
.grid-2 {
  margin-top: 16px;
}

.panel-head {
  margin-bottom: 16px;
}

.chart-list {
  display: grid;
  gap: 12px;
}

.chart-row {
  display: grid;
  grid-template-columns: 100px minmax(120px, 1fr) 80px 60px;
  gap: 12px;
  align-items: center;
}

.chart-date,
.chart-meta {
  color: #64748b;
  font-size: 0.875rem;
}

.chart-bar {
  height: 10px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
}

.chart-fill {
  height: 100%;
  background: linear-gradient(90deg, #3156d3, #6183ff);
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.table-wrap {
  overflow-x: auto;
}

.table {
  width: 100%;
  min-width: 420px;
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

.btn-primary {
  padding: 8px 12px;
  border: none;
  border-radius: 10px;
  background: #3156d3;
  color: #fff;
  cursor: pointer;
}

.state-block,
.state-cell {
  color: #64748b;
}

@media (max-width: 960px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }

  .chart-row {
    grid-template-columns: 1fr;
  }
}
</style>
