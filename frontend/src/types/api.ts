// 与后端 app/schemas/ 对齐的类型定义

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface User {
  id: number
  user_id: number
  email: string
  display_name: string | null
  tier: 'free' | 'pro' | 'enterprise'
  tier_expires_at?: string | null
  status: string
  is_admin: boolean
  created_at: string
}

export interface Task {
  task_id: string
  task_type: string
  status: 'pending' | 'queued' | 'running' | 'retrying' | 'done' | 'failed' | 'cancelled' | 'dead_letter'
  progress: number
  stage_text: string | null
  result: Record<string, any> | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface TaskListResponse {
  tasks: Task[]
  total: number
  page: number
  page_size: number
}

export interface BatchSubmitResponse {
  parent_task_id: string
  child_task_ids: string[]
  status: string
  total_credits_reserved: number
}

export interface ApiKey {
  key_id: string
  name: string
  created_at: string
  api_key?: string  // 仅创建时返回
}
