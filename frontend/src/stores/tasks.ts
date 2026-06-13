import { defineStore } from 'pinia'
import { ref } from 'vue'
import { tasksApi } from '@/api/tasks'
import type { Task } from '@/types/api'

export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<Task[]>([])
  const total = ref(0)
  const loading = ref(false)

  async function fetchTasks(params?: { status?: string; page?: number }) {
    loading.value = true
    try {
      const { data } = await tasksApi.list(params)
      tasks.value = data.tasks
      total.value = data.total
    } finally {
      loading.value = false
    }
  }

  function updateTaskFromWs(taskId: string, updates: Partial<Task>) {
    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index !== -1) {
      tasks.value[index] = { ...tasks.value[index], ...updates }
    }
  }

  return { tasks, total, loading, fetchTasks, updateTaskFromWs }
})
