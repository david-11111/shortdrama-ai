import client from './client'
import type { TaskListResponse, Task, BatchSubmitResponse } from '@/types/api'

export const tasksApi = {
  list(params?: { status?: string; page?: number; page_size?: number }) {
    return client.get<TaskListResponse>('/tasks', { params })
  },

  get(taskId: string) {
    return client.get<Task>(`/tasks/${taskId}`)
  },

  cancel(taskId: string) {
    return client.post(`/tasks/${taskId}/cancel`)
  },

  submitVideos(items: any[]) {
    return client.post<BatchSubmitResponse>('/batch/generate-videos', { items })
  },

  submitImages(items: any[]) {
    return client.post<BatchSubmitResponse>('/batch/generate-images', { items })
  },

  submitTts(payload: { text: string; voice?: string; speed?: number }) {
    return client.post<{ task_id: string; status: string; message: string }>('/tts/generate', payload)
  },
}
