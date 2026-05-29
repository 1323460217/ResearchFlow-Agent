import { defineStore } from 'pinia'
import { ref } from 'vue'
import { workflowApi } from '../api/index.js'

export const useWorkflowStore = defineStore('workflow', () => {
  const tasks = ref([])
  const executions = ref([])

  async function loadTasks() {
    try {
      const data = await workflowApi.listTasks()
      tasks.value = data.items || data || []
    } catch (e) { console.error('loadTasks failed:', e.message || e) }
  }

  async function loadExecutions() {
    try {
      const data = await workflowApi.listExecutions()
      executions.value = data.items || data || []
    } catch (e) { console.error('loadExecutions failed:', e.message || e) }
  }

  async function clearExecutions() {
    await workflowApi.clearExecutions()
    executions.value = []
  }

  async function fetchTaskStatus(taskId) {
    try {
      const data = await workflowApi.getTaskStatus(taskId)
      const existing = tasks.value.findIndex(t => t.task_id === taskId)
      const progress = data.progress || {}
      const task = {
        task_id: data.task_id || taskId,
        task_type: data.task_type || data.name || 'unknown',
        status: data.status || (
          data.state === 'SUCCESS' ? 'completed'
            : data.state === 'FAILURE' ? 'failed'
              : data.state === 'PENDING' ? 'pending' : 'processing'
        ),
        progress: {
          percent: progress.percent ?? (data.status === 'completed' || data.state === 'SUCCESS' ? 100 : 50),
          message: progress.message || progress.error || '',
          step: progress.step,
        },
        created_at: data.created_at,
        estimated_remaining_seconds: data.estimated_remaining_seconds,
      }
      if (existing >= 0) {
        tasks.value[existing] = task
      } else {
        tasks.value.unshift(task)
      }
      return task
    } catch (e) {
      console.error('fetchTaskStatus failed:', e.message || e)
      return null
    }
  }

  function cancelTask(taskId) {
    const task = tasks.value.find(t => t.task_id === taskId)
    if (task) task.status = 'failed'
  }

  function reset() {
    tasks.value = []
    executions.value = []
  }

  return {
    tasks, executions,
    loadTasks, loadExecutions, clearExecutions,
    fetchTaskStatus, cancelTask, reset,
  }
})
