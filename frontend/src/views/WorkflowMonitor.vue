<script setup>
import { ref, onMounted } from 'vue'
import { useWorkflowStore } from '../stores/workflow.js'

const workflowStore = useWorkflowStore()
const activeTab = ref('tasks')

onMounted(() => {
  workflowStore.loadTasks()
  workflowStore.loadExecutions()
})

const taskTypeLabel = {
  parse_document: '文档解析',
  generate_report: '报告生成',
  batch_search: '批量检索',
  build_index: '索引重建',
  cleanup_expired: '过期清理',
}

const statusIcon = {
  completed: '✅', failed: '❌', processing: '🔄', pending: '⏳',
  queued: '⏳', done: '✅', cancelled: '❌'
}

const statusLabel = {
  completed: '已完成',
  done: '已完成',
  failed: '失败',
  processing: '处理中',
  pending: '等待中',
  queued: '排队中',
  cancelled: '已取消',
}

function handleCancel(taskId) {
  workflowStore.cancelTask(taskId)
}

async function handleClearExecutions() {
  if (!workflowStore.executions.length) return
  if (!window.confirm('确认清空所有 Agent 执行记录？')) return
  await workflowStore.clearExecutions()
}

function formatDuration(ms) {
  if (ms == null) return '-'
  if (ms < 1000) return ms + 'ms'
  return (ms / 1000).toFixed(1) + 's'
}

function formatBeijingTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}
</script>

<template>
  <div class="workflow-page">
    <h2 class="page-title">任务监控</h2>

    <!-- Tabs -->
    <div class="tabs">
      <button
        class="tab-btn" :class="{ active: activeTab === 'tasks' }"
        @click="activeTab = 'tasks'"
      >异步任务 ({{ workflowStore.tasks.length }})</button>
      <button
        class="tab-btn" :class="{ active: activeTab === 'executions' }"
        @click="activeTab = 'executions'"
      >Agent 执行记录 ({{ workflowStore.executions.length }})</button>
    </div>

    <!-- Tasks Tab -->
    <div v-if="activeTab === 'tasks'" class="tasks-panel">
      <div
        v-for="task in workflowStore.tasks"
        :key="task.task_id"
        class="task-card card"
      >
        <div class="task-header">
          <div class="task-title-row">
            <span class="badge" :class="{
              'badge-success': task.status === 'completed',
              'badge-danger': task.status === 'failed',
              'badge-info': task.status === 'processing',
              'badge-muted': task.status === 'pending'
            }">
              {{ statusIcon[task.status] || '•' }} {{ statusLabel[task.status] || task.status }}
            </span>
            <strong>{{ taskTypeLabel[task.task_type] || task.task_type }}</strong>
            <span class="task-id">{{ task.task_id }}</span>
          </div>
          <button
            v-if="task.status === 'processing'"
            class="btn-ghost btn-sm"
            @click="handleCancel(task.task_id)"
          >取消</button>
        </div>

        <div v-if="task.status === 'processing'" class="task-progress">
          <div class="progress-header">
            <span>{{ task.progress?.message || '正在处理...' }}</span>
            <span>{{ task.progress?.percent || 0 }}%</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: (task.progress?.percent || 0) + '%' }"></div>
          </div>
          <div class="progress-meta">
            <span v-if="task.estimated_remaining_seconds != null">预计剩余 {{ task.estimated_remaining_seconds }} 秒</span>
            <span v-else>正在更新状态</span>
          </div>
        </div>

        <div v-if="task.status === 'completed' || task.status === 'failed'" class="task-result">
          <span>{{ task.progress?.message || '-' }}</span>
        </div>

        <div class="task-footer">
          <span>创建于 {{ task.created_at || '-' }}</span>
        </div>
      </div>
      <div v-if="workflowStore.tasks.length === 0" class="empty-state card">
        暂无异步任务
      </div>
    </div>

    <!-- Executions Tab -->
    <div v-if="activeTab === 'executions'" class="executions-panel">
      <div class="panel-toolbar">
        <button
          class="btn-ghost btn-sm"
          :disabled="workflowStore.executions.length === 0"
          @click="handleClearExecutions"
        >清空记录</button>
      </div>
      <div class="exec-table card">
        <div class="exec-table-header">
          <span>Agent</span>
          <span>状态</span>
          <span>耗时</span>
          <span>Tokens</span>
          <span>工具调用</span>
          <span>时间</span>
        </div>
        <div
          v-for="exec in workflowStore.executions"
          :key="exec.id"
          class="exec-table-row"
        >
          <span class="exec-agent">
            <span class="agent-icon">{{ { Planner: '🧠', Retriever: '🔍', Analyzer: '📊', Critic: '🛡️', Reporter: '📝' }[exec.agent_name] || '🤖' }}</span>
            {{ exec.agent_name }}
          </span>
          <span>
            <span class="badge" :class="{
              'badge-success': exec.status === 'completed',
              'badge-danger': exec.status === 'failed',
              'badge-info': exec.status === 'started'
            }">
              {{ { completed: '完成', failed: '失败', started: '进行中' }[exec.status] }}
            </span>
          </span>
          <span class="exec-duration">{{ formatDuration(exec.duration_ms) }}</span>
          <span class="exec-tokens">{{ exec.token_usage?.total_tokens?.toLocaleString() || '-' }}</span>
          <span>
            <span v-if="exec.tool_calls && exec.tool_calls.length">
              <span v-for="tool in exec.tool_calls" :key="tool" class="badge badge-muted tool-badge">{{ tool }}</span>
            </span>
            <span v-else class="text-muted">-</span>
          </span>
          <span class="exec-date">{{ formatBeijingTime(exec.created_at) }}</span>
        </div>
        <div v-if="workflowStore.executions.length === 0" class="empty-state">
          暂无 Agent 执行记录
        </div>
      </div>

      <!-- Summary -->
      <div class="exec-summary">
        <div class="summary-card card">
          <div class="summary-value">{{ workflowStore.executions.filter(e => e.status === 'completed').length }}</div>
          <div class="summary-label">成功执行</div>
        </div>
        <div class="summary-card card">
          <div class="summary-value">{{ workflowStore.executions.filter(e => e.status === 'failed').length }}</div>
          <div class="summary-label">执行失败</div>
        </div>
        <div class="summary-card card">
          <div class="summary-value">
            {{ (workflowStore.executions.reduce((s, e) => s + (e.duration_ms || 0), 0) / 1000).toFixed(1) }}s
          </div>
          <div class="summary-label">总耗时</div>
        </div>
        <div class="summary-card card">
          <div class="summary-value">
            {{ workflowStore.executions.reduce((s, e) => s + (e.token_usage?.total_tokens || 0), 0).toLocaleString() }}
          </div>
          <div class="summary-label">总 Token 消耗</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-page { flex: 1; overflow-y: auto; padding: 24px; }
.page-title { font-size: 20px; margin-bottom: 20px; }

.tabs { display: flex; gap: 2px; margin-bottom: 20px; border-bottom: 2px solid var(--border); }
.tab-btn {
  padding: 10px 20px; background: none; border-radius: 8px 8px 0 0;
  color: var(--text-secondary); font-size: 14px; border-bottom: 2px solid transparent;
  margin-bottom: -2px; transition: all 0.15s;
}
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }

/* Tasks */
.tasks-panel { display: flex; flex-direction: column; gap: 12px; }
.task-card { padding: 16px 20px; }
.task-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.task-title-row { display: flex; align-items: center; gap: 10px; }
.task-id { font-size: 11px; color: var(--text-muted); font-family: monospace; }
.task-progress { margin: 12px 0; }
.progress-header { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px; }
.progress-bar { height: 6px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.task-result { font-size: 13px; color: var(--text-secondary); padding: 8px 0; }
.task-footer { font-size: 11px; color: var(--text-muted); border-top: 1px solid var(--border); padding-top: 8px; }
.empty-state { padding: 20px; text-align: center; color: var(--text-muted); font-size: 13px; }

/* Executions */
.executions-panel { }
.panel-toolbar { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.panel-toolbar button:disabled { opacity: 0.45; cursor: not-allowed; }
.exec-table { overflow: hidden; }
.exec-table-header, .exec-table-row {
  display: grid; grid-template-columns: 1.1fr 0.55fr 0.55fr 0.6fr 1fr 1.2fr;
  padding: 10px 16px; align-items: center; font-size: 13px;
}
.exec-table-header {
  background: var(--bg-hover); font-weight: 600; color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
}
.exec-table-row { border-bottom: 1px solid var(--border); }
.exec-table-row:last-child { border-bottom: none; }
.exec-agent { display: flex; align-items: center; gap: 6px; }
.agent-icon { font-size: 16px; }
.exec-duration { font-family: monospace; font-size: 12px; }
.exec-tokens { font-family: monospace; font-size: 12px; }
.exec-date { font-size: 12px; color: var(--text-muted); }
.tool-badge { margin-right: 4px; }
.text-muted { color: var(--text-muted); }

.exec-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 16px; }
.summary-card { padding: 16px; text-align: center; }
.summary-value { font-size: 24px; font-weight: 700; color: var(--accent); }
.summary-label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
</style>
