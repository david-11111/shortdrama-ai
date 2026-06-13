import client from './client'

export interface PricingPlan {
  id: string
  name: string
  credits?: number
  target_tier?: 'pro' | 'enterprise'
  tier_days?: number
  price_cents: number
  description: string
}

export interface Order {
  order_no: string
  amount_cents: number
  credits: number
  order_type?: 'topup' | 'tier_upgrade'
  plan_id?: string | null
  tier_target?: string | null
  tier_days?: number
  payment_method: string
  status: string
  paid_at: string | null
  created_at: string
}

export const paymentApi = {
  getPlans() {
    return client.get<{ plans: PricingPlan[]; credit_plans?: PricingPlan[]; tier_plans?: PricingPlan[] }>('/payment/plans')
  },

  createOrder(plan_id: string, payment_method: string, order_type: 'topup' | 'tier_upgrade' = 'topup') {
    return client.post('/payment/create-order', { plan_id, payment_method, order_type })
  },

  getOrders() {
    return client.get<{ orders: Order[] }>('/payment/orders')
  },
}
