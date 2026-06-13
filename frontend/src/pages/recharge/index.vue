<template>
  <div class="recharge-page">
    <h1 class="page-title">充值与套餐升级</h1>

    <section class="current-tier">
      <strong>当前套餐：</strong>
      <span class="tier">{{ auth.user?.tier || 'free' }}</span>
      <span v-if="auth.user?.tier_expires_at" class="expire">到期：{{ formatTime(auth.user.tier_expires_at) }}</span>
    </section>

    <section v-if="creditLimitNotice" class="limit-notice">
      <strong>今日积分不足</strong>
      <span>{{ creditLimitNotice }}</span>
    </section>

    <div class="tab-row">
      <button class="tab-btn" :class="{ active: orderType === 'topup' }" @click="orderType = 'topup'">积分充值</button>
      <button class="tab-btn" :class="{ active: orderType === 'tier_upgrade' }" @click="orderType = 'tier_upgrade'">套餐升级</button>
    </div>

    <div class="plans-grid">
      <div
        v-for="plan in visiblePlans"
        :key="plan.id"
        class="plan-card"
        :class="{ active: selectedPlan === plan.id }"
        @click="selectedPlan = plan.id"
      >
        <h3 class="plan-name">{{ plan.name }}</h3>
        <div v-if="orderType === 'topup'" class="plan-main">{{ plan.credits }} 积分</div>
        <div v-else class="plan-main">{{ plan.target_tier?.toUpperCase() }} · {{ plan.tier_days }} 天</div>
        <div class="plan-price">¥{{ (plan.price_cents / 100).toFixed(2) }}</div>
        <div class="plan-desc">{{ plan.description }}</div>
      </div>
    </div>

    <div class="payment-methods" v-if="selectedPlan">
      <h2>支付方式</h2>
      <div class="method-options">
        <label class="method-option" :class="{ active: paymentMethod === 'wechat' }">
          <input type="radio" v-model="paymentMethod" value="wechat" />
          <span>微信支付</span>
        </label>
        <label class="method-option" :class="{ active: paymentMethod === 'alipay' }">
          <input type="radio" v-model="paymentMethod" value="alipay" />
          <span>支付宝</span>
        </label>
      </div>
    </div>

    <button class="btn-pay" :disabled="!selectedPlan || loading" @click="handlePay">
      {{ loading ? '创建订单中...' : (orderType === 'topup' ? '立即充值' : '立即升级') }}
    </button>

    <div v-if="wechatQrVisible" class="qr-mask" @click.self="wechatQrVisible = false">
      <div class="qr-modal">
        <h3>微信扫码支付</h3>
        <img :src="wechatQrImageUrl" alt="wechat qr" class="qr-image" />
        <p class="qr-hint">完成支付后，点击下方“刷新订单与账号状态”。</p>
        <button class="qr-close" type="button" @click="refreshAfterPay">刷新订单与账号状态</button>
      </div>
    </div>

    <div class="orders-section">
      <h2>订单记录</h2>
      <div v-if="orders.length === 0" class="empty-state">暂无订单记录</div>
      <table v-else class="orders-table">
        <thead>
          <tr>
            <th>订单号</th>
            <th>类型</th>
            <th>内容</th>
            <th>金额</th>
            <th>状态</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="order in orders" :key="order.order_no">
            <td class="order-no">{{ order.order_no }}</td>
            <td>{{ order.order_type === 'tier_upgrade' ? '套餐升级' : '积分充值' }}</td>
            <td>
              <template v-if="order.order_type === 'tier_upgrade'">
                {{ order.tier_target?.toUpperCase() }} · {{ order.tier_days }} 天
              </template>
              <template v-else>
                {{ order.credits }} 积分
              </template>
            </td>
            <td>¥{{ (order.amount_cents / 100).toFixed(2) }}</td>
            <td>
              <span class="status-badge" :class="order.status">{{ statusText(order.status) }}</span>
            </td>
            <td>{{ formatTime(order.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { paymentApi, type Order, type PricingPlan } from '@/api/payment'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const creditPlans = ref<PricingPlan[]>([])
const tierPlans = ref<PricingPlan[]>([])
const orders = ref<Order[]>([])
const selectedPlan = ref('')
const paymentMethod = ref<'wechat' | 'alipay'>('wechat')
const orderType = ref<'topup' | 'tier_upgrade'>(normalizeOrderType(route.query.type))
const loading = ref(false)
const wechatQrVisible = ref(false)
const wechatQrImageUrl = ref('')

const visiblePlans = computed(() => (orderType.value === 'topup' ? creditPlans.value : tierPlans.value))
const creditLimitNotice = computed(() => {
  if (route.query.reason !== 'daily_credit_limit') return ''
  const remaining = firstQueryValue(route.query.remaining)
  const required = firstQueryValue(route.query.required)
  if (remaining && required) {
    return `剩余 ${remaining} 积分，本次需要 ${required} 积分。请充值或升级会员后继续。`
  }
  return '请充值或升级会员后继续生成内容。'
})

watch(orderType, () => {
  selectedPlan.value = ''
})

watch(
  () => route.query.type,
  (type) => {
    orderType.value = normalizeOrderType(type)
  }
)

onMounted(async () => {
  await Promise.all([loadPlans(), loadOrders(), auth.fetchUser()])
})

async function loadPlans() {
  const res = await paymentApi.getPlans()
  creditPlans.value = res.data.credit_plans || res.data.plans || []
  tierPlans.value = res.data.tier_plans || []
}

async function loadOrders() {
  const res = await paymentApi.getOrders()
  orders.value = res.data.orders
}

async function refreshAfterPay() {
  wechatQrVisible.value = false
  await Promise.all([loadOrders(), auth.fetchUser()])
}

async function handlePay() {
  if (!selectedPlan.value) return
  loading.value = true
  try {
    const res = await paymentApi.createOrder(selectedPlan.value, paymentMethod.value, orderType.value)
    const data = res.data
    if (paymentMethod.value === 'wechat' && data.code_url) {
      wechatQrImageUrl.value = `https://api.qrserver.com/v1/create-qr-code/?size=320x320&data=${encodeURIComponent(data.code_url)}`
      wechatQrVisible.value = true
      await loadOrders()
      return
    }
    if (paymentMethod.value === 'alipay' && data.payment_url) {
      const form = document.createElement('form')
      form.action = data.payment_url
      form.method = 'GET'
      for (const [key, val] of Object.entries(data.params || {})) {
        const input = document.createElement('input')
        input.type = 'hidden'
        input.name = key
        input.value = String(val)
        form.appendChild(input)
      }
      document.body.appendChild(form)
      form.submit()
    }
  } finally {
    loading.value = false
  }
}

function statusText(status: string) {
  const map: Record<string, string> = {
    pending: '待支付',
    processing: '处理中',
    paid: '已支付',
    failed: '失败',
    refunded: '已退款',
  }
  return map[status] || status
}

function formatTime(ts?: string | null) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN')
}

function firstQueryValue(value: unknown): string {
  if (Array.isArray(value)) return String(value[0] || '')
  return typeof value === 'string' ? value : ''
}

function normalizeOrderType(value: unknown): 'topup' | 'tier_upgrade' {
  return firstQueryValue(value) === 'tier_upgrade' ? 'tier_upgrade' : 'topup'
}
</script>

<style scoped>
.recharge-page { max-width: 960px; margin: 0 auto; padding: 2rem; }
.page-title { font-size: 1.5rem; margin-bottom: 1rem; }
.current-tier { margin-bottom: 1rem; font-size: 0.95rem; }
.tier { font-weight: 700; margin-right: 0.6rem; }
.expire { color: #64748b; }
.limit-notice { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 1rem; border: 1px solid #facc15; border-radius: 8px; background: #fefce8; color: #713f12; padding: 0.75rem 0.9rem; }
.limit-notice strong { font-size: 0.95rem; }
.limit-notice span { font-size: 0.9rem; line-height: 1.45; }
.tab-row { display: flex; gap: 0.8rem; margin-bottom: 1rem; }
.tab-btn { border: 1px solid #cbd5e1; background: #fff; border-radius: 8px; padding: 0.5rem 0.9rem; cursor: pointer; }
.tab-btn.active { border-color: #3b82f6; color: #1d4ed8; background: #eff6ff; }
.plans-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
.plan-card { border: 2px solid #e2e8f0; border-radius: 12px; padding: 1rem; cursor: pointer; }
.plan-card.active { border-color: #3b82f6; background: #eff6ff; }
.plan-main { font-size: 1.1rem; font-weight: 700; margin: 0.4rem 0; }
.plan-price { color: #dc2626; font-weight: 700; }
.plan-desc { color: #64748b; font-size: 0.85rem; margin-top: 0.35rem; }
.payment-methods { margin-bottom: 1rem; }
.method-options { display: flex; gap: 0.8rem; }
.method-option { border: 1px solid #cbd5e1; border-radius: 8px; padding: 0.6rem 0.9rem; cursor: pointer; }
.method-option.active { border-color: #3b82f6; background: #eff6ff; }
.method-option input { display: none; }
.btn-pay { width: 100%; padding: 0.8rem; border: none; border-radius: 8px; background: #2563eb; color: #fff; cursor: pointer; margin-bottom: 1.4rem; }
.btn-pay:disabled { opacity: 0.55; cursor: not-allowed; }
.qr-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: grid; place-items: center; z-index: 1000; padding: 1rem; }
.qr-modal { width: min(90vw, 360px); background: #fff; border-radius: 12px; padding: 1rem; text-align: center; }
.qr-image { width: 280px; max-width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; }
.qr-hint { color: #475569; font-size: 0.85rem; margin: 0.75rem 0; }
.qr-close { width: 100%; padding: 0.6rem; border: none; border-radius: 8px; background: #2563eb; color: #fff; cursor: pointer; }
.orders-table { width: 100%; border-collapse: collapse; }
.orders-table th, .orders-table td { padding: 0.55rem 0.6rem; border-bottom: 1px solid #e2e8f0; text-align: left; }
.order-no { font-family: monospace; font-size: 0.8rem; }
.status-badge { padding: 0.2rem 0.45rem; border-radius: 6px; font-size: 0.8rem; }
.status-badge.paid { background: #dcfce7; color: #166534; }
.status-badge.pending, .status-badge.processing { background: #fef9c3; color: #854d0e; }
.status-badge.failed { background: #fee2e2; color: #991b1b; }
</style>
