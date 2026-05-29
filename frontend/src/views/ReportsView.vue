<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReportStore } from '../stores/report.js'

const route = useRoute()
const router = useRouter()
const reportStore = useReportStore()

const showCreateForm = ref(false)
const saving = ref(false)
const formError = ref('')
const form = reactive({
  title: '',
  content: '',
  status: 'draft',
})

const statusLabel = { draft: '草稿', completed: '已完成', archived: '已归档', failed: '失败' }
const statusBadgeClass = {
  draft: 'badge-warning',
  completed: 'badge-success',
  archived: 'badge-muted',
  failed: 'badge-danger',
}

onMounted(async () => {
  await loadPageData()
})

watch(() => route.params.id, async () => {
  await loadPageData()
})

const pageTitle = computed(() => route.params.id ? '报告详情' : '研究报告')

async function loadPageData() {
  await reportStore.loadReports()
  if (route.params.id) {
    const id = route.params.id
    const cachedReport = reportStore.reports.find(report => String(report.id) === String(id))
    if (cachedReport) {
      reportStore.currentReportId = cachedReport.id
      reportStore.currentReport = cachedReport
    }
    await reportStore.selectReport(id)
  } else {
    reportStore.currentReportId = null
    reportStore.currentReport = null
  }
}

function resetForm() {
  form.title = ''
  form.content = ''
  form.status = 'draft'
  formError.value = ''
}

function previewText(report) {
  const text = report.content || ''
  return text.replace(/[#*_>`-]/g, '').replace(/\s+/g, ' ').trim().slice(0, 140)
}

function simpleMarkdown(text) {
  if (!text) return ''
  let t = text.trim()
  t = t.replace(/^```\w*\s*\n?/, '').replace(/\n?```\s*$/, '').trim()

  let html = t
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^(?:[-*]) (.+)$/gm, '<li>$1</li>')
    .replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^/, '<p>')
    .replace(/$/, '</p>')

  html = html
    .replace(/<p><h([1-3])>/g, '<h$1>')
    .replace(/<\/h([1-3])><\/p>/g, '</h$1>')
    .replace(/<p><ul>/g, '<ul>')
    .replace(/<\/ul><\/p>/g, '</ul>')
    .replace(/<ul>\n<li>/g, '<ul><li>')
    .replace(/<\/li>\n<\/ul>/g, '</li></ul>')
    .replace(/\n/g, '<br>')

  return html
}

async function submitReport() {
  formError.value = ''
  if (!form.title.trim() || !form.content.trim()) {
    formError.value = '标题和正文不能为空'
    return
  }

  saving.value = true
  try {
    await reportStore.createReport({
      title: form.title.trim(),
      content: form.content.trim(),
      status: form.status,
    })
    resetForm()
    showCreateForm.value = false
  } catch (e) {
    formError.value = e.message || '保存报告失败'
  } finally {
    saving.value = false
  }
}

async function deleteCurrentReport() {
  const id = reportStore.currentReportId
  if (!id) return
  await reportStore.deleteReport(id)
  router.push('/reports')
}
</script>

<template>
  <div class="reports-layout">
    <template v-if="!route.params.id">
      <div class="reports-page">
        <div class="page-header">
          <h2 class="page-title">{{ pageTitle }}</h2>
          <div class="page-actions">
            <button class="btn-ghost btn-sm" @click="reportStore.loadReports()">刷新</button>
            <button class="btn-primary btn-sm" @click="showCreateForm = !showCreateForm">
              {{ showCreateForm ? '收起' : '新建报告' }}
            </button>
          </div>
        </div>

        <form v-if="showCreateForm" class="report-form card" @submit.prevent="submitReport">
          <input v-model="form.title" placeholder="报告标题" />
          <select v-model="form.status">
            <option value="draft">草稿</option>
            <option value="completed">已完成</option>
            <option value="archived">已归档</option>
          </select>
          <textarea v-model="form.content" rows="8" placeholder="Markdown 报告正文"></textarea>
          <p v-if="formError" class="form-error">{{ formError }}</p>
          <div class="form-actions">
            <button type="button" class="btn-ghost btn-sm" @click="resetForm()">清空</button>
            <button type="submit" class="btn-primary btn-sm" :disabled="saving">
              {{ saving ? '保存中...' : '保存报告' }}
            </button>
          </div>
        </form>

        <div v-if="reportStore.error" class="notice-error">{{ reportStore.error }}</div>
        <div v-if="reportStore.loading" class="empty-state">
          <div class="text">正在加载报告...</div>
        </div>

        <div v-else-if="reportStore.reports.length" class="report-grid">
          <div
            v-for="report in reportStore.reports"
            :key="report.id"
            class="report-card card"
            @click="router.push(`/reports/${report.id}`)"
          >
            <div class="report-card-header">
              <span class="badge" :class="statusBadgeClass[report.status] || 'badge-muted'">
                {{ statusLabel[report.status] || report.status }}
              </span>
              <span class="report-date">{{ report.created_at?.slice(0, 10) ?? '' }}</span>
            </div>
            <h3 class="report-card-title">{{ report.title }}</h3>
            <p class="report-card-preview">{{ previewText(report) || '暂无正文预览' }}</p>
            <div class="report-card-meta">
              <span v-if="report.sources?.length">{{ report.sources.length }} 个引用源</span>
              <span v-if="report.conversation_id">会话 #{{ report.conversation_id }}</span>
            </div>
          </div>
        </div>

        <div v-else class="empty-state">
          <div class="icon">📄</div>
          <div class="text">暂无研究报告</div>
          <div class="hint">完成一次研究会话或手动新建后，报告会出现在这里。</div>
        </div>
      </div>
    </template>

    <template v-if="route.params.id && reportStore.currentReport">
      <div class="report-detail">
        <button class="btn-ghost back-btn" @click="router.push('/reports')">返回列表</button>
        <div class="report-detail-header">
          <h2>{{ reportStore.currentReport.title }}</h2>
          <span class="badge" :class="statusBadgeClass[reportStore.currentReport.status] || 'badge-muted'">
            {{ statusLabel[reportStore.currentReport.status] || reportStore.currentReport.status }}
          </span>
          <span class="report-date">{{ reportStore.currentReport.created_at?.slice(0, 10) ?? '' }}</span>
        </div>

        <div class="report-body card">
          <div class="markdown-content" v-html="simpleMarkdown(reportStore.currentReport.content)"></div>
        </div>

        <div v-if="reportStore.currentReport.sources?.length" class="report-sources card">
          <h3>引用来源</h3>
          <div v-for="(src, i) in reportStore.currentReport.sources" :key="i" class="source-item">
            <span class="source-index">{{ i + 1 }}</span>
            <span>{{ src.title || src.source || '未命名来源' }}</span>
            <a v-if="src.url" :href="src.url" target="_blank" class="source-link">查看</a>
          </div>
        </div>

        <div class="report-actions">
          <button class="btn-ghost btn-sm" @click="reportStore.refreshCurrentReport()">刷新</button>
          <button class="btn-danger btn-sm" @click="deleteCurrentReport()">删除报告</button>
        </div>
      </div>
    </template>

    <div v-if="route.params.id && !reportStore.currentReport && !reportStore.loading" class="empty-state">
      <div class="icon">🔎</div>
      <div class="text">报告未找到</div>
      <button class="btn-ghost btn-sm" @click="router.push('/reports')">返回列表</button>
    </div>
  </div>
</template>

<style scoped>
.reports-layout,
.reports-page,
.report-detail {
  flex: 1;
  overflow-y: auto;
}

.reports-page,
.report-detail {
  padding: 24px;
}

.page-header,
.report-detail-header,
.report-actions,
.form-actions,
.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-header {
  justify-content: space-between;
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
}

.report-form {
  display: grid;
  gap: 10px;
  padding: 16px;
  margin-bottom: 16px;
}

.report-form input,
.report-form select,
.report-form textarea {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 9px 10px;
  font-size: 14px;
  color: var(--text-primary);
  background: var(--bg-sidebar);
  outline: none;
}

.report-form textarea {
  resize: vertical;
  line-height: 1.6;
}

.form-actions,
.report-actions {
  justify-content: flex-end;
}

.form-error,
.notice-error {
  color: #dc2626;
  font-size: 13px;
}

.notice-error {
  margin-bottom: 12px;
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.report-card {
  padding: 20px;
  cursor: pointer;
  transition: box-shadow 0.15s, transform 0.15s;
}

.report-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.report-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.report-date {
  font-size: 12px;
  color: var(--text-muted);
}

.report-card-title {
  font-size: 16px;
  margin-bottom: 8px;
}

.report-card-preview {
  min-height: 42px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.report-card-meta {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  color: var(--text-muted);
}

.empty-state .icon {
  font-size: 32px;
}

.empty-state .text {
  font-size: 15px;
  color: var(--text-secondary);
}

.empty-state .hint {
  font-size: 13px;
}

.back-btn {
  margin-bottom: 16px;
}

.report-detail-header {
  margin-bottom: 20px;
}

.report-detail-header h2 {
  font-size: 22px;
}

.report-body {
  padding: 24px;
  margin-bottom: 16px;
}

.report-sources {
  padding: 16px 20px;
  margin-bottom: 16px;
}

.report-sources h3 {
  font-size: 14px;
  margin-bottom: 10px;
}

.source-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-secondary);
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}

.source-item:last-child {
  border-bottom: none;
}

.source-index {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.source-link {
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
}

.markdown-content {
  color: var(--text-primary);
  line-height: 1.75;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin: 14px 0 8px;
}

.markdown-content :deep(p) {
  margin: 0 0 12px;
}

.markdown-content :deep(ul) {
  margin: 8px 0 12px 20px;
  padding: 0;
}

.markdown-content :deep(li) {
  margin: 4px 0;
}
</style>
