// WebSocket 消息类型

export interface WsTaskUpdate {
  type: 'task_update'
  task_id: string
  status: string
  progress: number
  stage_text: string
}

export interface WsTaskComplete {
  type: 'task_complete'
  task_id: string
  result: Record<string, any>
}

export interface WsTaskFailed {
  type: 'task_failed'
  task_id: string
  error: string
  credits_refunded?: number
}

export type WsMessage = WsTaskUpdate | WsTaskComplete | WsTaskFailed | { type: 'pong' }
