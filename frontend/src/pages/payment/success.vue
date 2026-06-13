<template>
  <div class="success-page">
    <div class="success-card">
      <div class="success-icon" aria-hidden="true">
        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
      </div>

      <h1>支付成功</h1>
      <p class="success-desc">您的订单已完成支付，积分将自动到账。</p>

      <p v-if="orderNo" class="order-info">订单号：{{ orderNo }}</p>

      <router-link to="/" class="btn-primary">返回首页</router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const orderNo = computed(() => (route.query.order_no as string) || '')
</script>

<style scoped>
.success-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: var(--space-xl);
}

.success-card {
  text-align: center;
  max-width: 480px;
  padding: var(--space-xl);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.success-icon {
  color: #059669;
  margin-bottom: var(--space-md);
}

.success-card h1 {
  margin: 0 0 var(--space-sm);
  font-size: 1.5rem;
}

.success-desc {
  margin: 0 0 var(--space-md);
  color: var(--color-text-secondary);
}

.order-info {
  margin: 0 0 var(--space-lg);
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-sm) var(--space-lg);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  color: #fff;
  font-size: 1rem;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
}
</style>
