import client from './client'

export interface AdminOverviewResponse {
  users: {
    total_users: number
    active_users: number
    new_today: number
  }
  tasks: {
    active_tasks: number
    completed_today: number
    failed_today: number
  }
  revenue_today: number
  dead_letter_count: number
}

export interface AdminUserRow {
  id: number
  email: string
  display_name: string | null
  tier: 'free' | 'pro' | 'enterprise'
  status: string
  is_admin: boolean
  created_at: string
  balance: number | null
  lifetime_spent: number | null
}

export interface AdminUsersResponse {
  users: AdminUserRow[]
  total: number
  page: number
  page_size: number
}

export interface AdminTaskRow {
  task_id: string
  user_id: number
  user_email: string
  task_type: string
  status: string
  progress: number
  stage_text: string | null
  error_message: string | null
  retry_count: number
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface AdminTasksResponse {
  tasks: AdminTaskRow[]
  total: number
  page: number
  page_size: number
}

export interface AdminTaskStat {
  task_type: string
  total: number
  succeeded: number
  failed: number
  active: number
  avg_duration_seconds: number | null
}

export interface AdminTaskStatsResponse {
  stats: AdminTaskStat[]
}

export interface RevenuePoint {
  date: string
  revenue: number
  transactions: number
}

export interface TopSpender {
  id: number
  email: string
  tier: string
  lifetime_spent: number
  balance: number
}

export interface AdminRevenueResponse {
  daily_revenue: RevenuePoint[]
  top_spenders: TopSpender[]
}

export interface PricingRule {
  id: number
  operation: string
  credits_cost: number
  active: boolean
}

export interface PricingResponse {
  pricing: PricingRule[]
}

export interface DeadLetterItem {
  id: number
  original_task_id: string
  user_id: number
  user_email: string
  task_type: string
  payload: unknown
  error_history: unknown
  dead_at: string
  resolved: boolean
}

export interface DeadLetterResponse {
  items: DeadLetterItem[]
  total: number
  page: number
}

export interface KeyPoolItem {
  name: string
  load: number
  rpm: number
  cooldown_until: string | null
  max_concurrency: number
}

export interface KeyPoolResponse {
  services: Record<string, KeyPoolItem[]>
}

export interface SystemResponse {
  database: 'healthy' | 'unhealthy'
  redis: {
    used_memory_human: string
    used_memory_peak_human: string
  }
  queue_depth: Record<string, number>
}

export interface RateLimitRule {
  id: number
  tier: string
  resource: string
  window_seconds: number
  max_count: number
}

export interface RateLimitsResponse {
  rules: RateLimitRule[]
}

export const adminApi = {
  overview() {
    return client.get<AdminOverviewResponse>('/admin/overview')
  },

  users(params?: { page?: number; page_size?: number; tier?: string; status?: string; search?: string }) {
    return client.get<AdminUsersResponse>('/admin/users', { params })
  },

  updateUser(userId: number, payload: { tier?: string; status?: string; is_admin?: boolean }) {
    return client.patch(`/admin/users/${userId}`, payload)
  },

  tasks(params?: { page?: number; page_size?: number; status?: string; task_type?: string; user_id?: number }) {
    return client.get<AdminTasksResponse>('/admin/tasks', { params })
  },

  taskStats() {
    return client.get<AdminTaskStatsResponse>('/admin/tasks/stats')
  },

  revenue(days = 30) {
    return client.get<AdminRevenueResponse>('/admin/credits/revenue', { params: { days } })
  },

  pricing() {
    return client.get<PricingResponse>('/admin/credits/pricing')
  },

  updatePricing(pricingId: number, payload: { credits_cost?: number; active?: boolean }) {
    return client.patch(`/admin/credits/pricing/${pricingId}`, payload)
  },

  deadLetter(params?: { resolved?: boolean; page?: number; page_size?: number }) {
    return client.get<DeadLetterResponse>('/admin/dead-letter', { params })
  },

  retryDeadLetter(itemId: number) {
    return client.post<{ message: string; new_task_id: string }>(`/admin/dead-letter/${itemId}/retry`)
  },

  resolveDeadLetter(itemId: number) {
    return client.patch<{ message: string }>(`/admin/dead-letter/${itemId}/resolve`)
  },

  keyPool() {
    return client.get<KeyPoolResponse>('/admin/key-pool')
  },

  system() {
    return client.get<SystemResponse>('/admin/system')
  },

  rateLimits() {
    return client.get<RateLimitsResponse>('/admin/rate-limits')
  },

  updateRateLimit(ruleId: number, payload: { window_seconds?: number; max_count?: number }) {
    return client.patch(`/admin/rate-limits/${ruleId}`, payload)
  },
}
