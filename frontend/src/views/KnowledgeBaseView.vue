<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKnowledgeBaseStore } from '../stores/knowledgeBase.js'
import { useWorkflowStore } from '../stores/workflow.js'

const route = useRoute()
const router = useRouter()
const kbStore = useKnowledgeBaseStore()
const workflowStore = useWorkflowStore()

onMounted(async () => {
  await kbStore.loadKnowledgeBases()
  if (route.params.id) {
    kbStore.selectKB(Number(route.params.id))
  }
})

// Watch route param changes (component is reused for /knowledge-bases and /knowledge-bases/:id)
watch(() => route.params.id, (newId) => {
  if (newId) {
    kbStore.selectKB(Number(newId))
  } else {
    kbStore.currentKBId = null
    kbStore.currentKB = null
    kbStore.documents = []
  }
})

const showCreateDialog = ref(false)
const showUploadDialog = ref(false)
const showDeleteConfirm = ref(false)
const rebuilding = ref(false)
const newKB = ref({ name: '', description: '' })
const uploadFile = ref(null)
const fileInputRef = ref(null)

const statusLabel = {
  pending: '等待中', parsing: '解析中', embedding: '向量化', done: '已完成', failed: '失败'
}
const statusBadgeClass = {
  pending: 'badge-muted', parsing: 'badge-warning', embedding: 'badge-info', done: 'badge-success', failed: 'badge-danger'
}
const statusIcon = {
  pending: '⏳', parsing: '🔄', embedding: '🧮', done: '✅', failed: '❌'
}

function handleCreateKB() {
  if (!newKB.value.name.trim()) return
  kbStore.createKB(newKB.value.name, newKB.value.description)
  showCreateDialog.value = false
  newKB.value = { name: '', description: '' }
}

function handleUpload() {
  if (!uploadFile.value || !kbStore.currentKBId) return
  kbStore.uploadDocument(kbStore.currentKBId, uploadFile.value)
  showUploadDialog.value = false
  uploadFile.value = null
}

async function handleRebuild() {
  if (!kbStore.currentKBId || rebuilding.value) return
  rebuilding.value = true
  try {
    await kbStore.rebuildIndex(kbStore.currentKBId)
  } finally {
    rebuilding.value = false
  }
}

async function handleDelete() {
  if (!kbStore.currentKBId) return
  await kbStore.deleteKB(kbStore.currentKBId)
  showDeleteConfirm.value = false
  router.push('/knowledge-bases')
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function handleCancelTask(taskId) {
  workflowStore.cancelTask(taskId)
}

async function handleDeleteDoc(docId) {
  if (!kbStore.currentKBId || !confirm('确定要删除该文档吗？')) return
  await kbStore.deleteDocument(kbStore.currentKBId, docId)
}
</script>

<template>
  <div class="kb-layout">
    <!-- KB List -->
    <div class="kb-sidebar">
      <div class="section-title">知识库</div>
      <button class="btn-primary new-kb-btn" @click="showCreateDialog = true">+ 新建知识库</button>
      <div class="kb-list">
        <div
          v-for="kb in kbStore.knowledgeBases"
          :key="kb.id"
          class="kb-item"
          :class="{ active: kbStore.currentKBId === kb.id }"
          @click="router.push(`/knowledge-bases/${kb.id}`); kbStore.selectKB(kb.id)"
        >
          <div class="kb-icon">📚</div>
          <div class="kb-info">
            <div class="kb-name">{{ kb.name }}</div>
            <div class="kb-meta">{{ kb.doc_count }} 文档 · {{ kb.chunk_count?.toLocaleString() ?? '0' }} 切片</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Document List -->
    <div class="kb-main">
      <template v-if="kbStore.currentKB">
        <div class="kb-header">
          <h2>{{ kbStore.currentKB.name }}</h2>
          <p class="kb-desc">{{ kbStore.currentKB.description }}</p>
          <div class="kb-actions">
            <button class="btn-primary" @click="showUploadDialog = true">📤 上传文档</button>
            <button class="btn-ghost btn-sm" @click="handleRebuild" :disabled="rebuilding">
              {{ rebuilding ? '重建中...' : '🔄 重建索引' }}
            </button>
            <button class="btn-danger btn-sm" @click="showDeleteConfirm = true">删除知识库</button>
          </div>
        </div>

        <div class="doc-table card">
          <div class="doc-table-header">
            <span class="doc-col-name">文件名</span>
            <span class="doc-col-type">类型</span>
            <span class="doc-col-size">大小</span>
            <span class="doc-col-status">状态</span>
            <span class="doc-col-date">上传时间</span>
            <span class="doc-col-action">操作</span>
          </div>
          <div v-if="kbStore.documents.length === 0" class="empty-state" style="padding:40px">
            <div class="icon">📂</div>
            <div class="text">暂无文档，点击"上传文档"开始</div>
          </div>
          <div
            v-for="doc in kbStore.documents"
            :key="doc.id"
            class="doc-table-row"
          >
            <span class="doc-col-name">{{ doc.filename }}</span>
            <span class="doc-col-type">
              <span class="badge badge-muted">{{ doc.file_type.toUpperCase() }}</span>
            </span>
            <span class="doc-col-size">{{ formatSize(doc.file_size_bytes) }}</span>
            <span class="doc-col-status">
              <span class="badge" :class="statusBadgeClass[doc.ingestion_status]">
                {{ statusIcon[doc.ingestion_status] }} {{ statusLabel[doc.ingestion_status] }}
              </span>
              <div v-if="doc.ingestion_error" class="ingestion-error">{{ doc.ingestion_error }}</div>
            </span>
            <span class="doc-col-date">{{ doc.created_at.slice(0, 10) }}</span>
            <span class="doc-col-action">
              <button class="btn-danger btn-sm" @click="handleDeleteDoc(doc.id)">删除</button>
            </span>
          </div>
        </div>

        <!-- Upload progress -->
        <div v-if="kbStore.uploading" class="upload-progress card">
          <div class="progress-header">
            <span>📤 {{ kbStore.uploadStatus === 'parsing' ? '解析中' : '向量化中' }}...</span>
            <span>{{ kbStore.uploadProgress }}%</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: kbStore.uploadProgress + '%' }"></div>
          </div>
        </div>
      </template>

      <div v-else class="empty-state">
        <div class="icon">📚</div>
        <div class="text">选择一个知识库或新建一个</div>
      </div>
    </div>

    <!-- Create KB Dialog -->
    <div v-if="showCreateDialog" class="dialog-overlay" @click.self="showCreateDialog = false">
      <div class="dialog card">
        <h3>新建知识库</h3>
        <input v-model="newKB.name" placeholder="知识库名称" />
        <textarea v-model="newKB.description" placeholder="描述（可选）" rows="3"></textarea>
        <div class="dialog-actions">
          <button class="btn-ghost" @click="showCreateDialog = false">取消</button>
          <button class="btn-primary" @click="handleCreateKB">创建</button>
        </div>
      </div>
    </div>

    <!-- Upload Dialog -->
    <div v-if="showUploadDialog" class="dialog-overlay" @click.self="showUploadDialog = false">
      <div class="dialog card">
        <h3>上传文档</h3>
        <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 12px;">
          支持 PDF、DOCX、Markdown、TXT 格式
        </p>
        <input type="file" ref="fileInputRef" @change="e => uploadFile = e.target.files[0]"
          accept=".pdf,.docx,.md,.txt" style="margin-bottom:12px" />
        <div v-if="uploadFile" style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">
          已选择: {{ uploadFile.name }} ({{ (uploadFile.size / 1024).toFixed(0) }} KB)
        </div>
        <div class="dialog-actions">
          <button class="btn-ghost" @click="showUploadDialog = false">取消</button>
          <button class="btn-primary" @click="handleUpload" :disabled="!uploadFile">开始上传</button>
        </div>
      </div>
    </div>

    <!-- Delete Confirm Dialog -->
    <div v-if="showDeleteConfirm" class="dialog-overlay" @click.self="showDeleteConfirm = false">
      <div class="dialog card">
        <h3>确认删除</h3>
        <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 16px;">
          删除知识库将移除所有文档和索引数据，此操作不可恢复。确定要继续吗？
        </p>
        <div class="dialog-actions">
          <button class="btn-ghost" @click="showDeleteConfirm = false">取消</button>
          <button class="btn-danger" @click="handleDelete">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kb-layout { display: flex; height: 100%; }

.kb-sidebar {
  width: 250px; background: var(--bg-sidebar); border-right: 1px solid var(--border);
  padding: 16px; display: flex; flex-direction: column; flex-shrink: 0;
}
.new-kb-btn { width: 100%; margin-bottom: 12px; }
.kb-list { flex: 1; overflow-y: auto; }
.kb-item {
  display: flex; gap: 10px; padding: 10px; border-radius: var(--radius);
  cursor: pointer; transition: background 0.1s;
}
.kb-item:hover { background: var(--bg-hover); }
.kb-item.active { background: var(--accent-bg); }
.kb-icon { font-size: 20px; flex-shrink: 0; }
.kb-info { min-width: 0; }
.kb-name { font-size: 13px; font-weight: 600; }
.kb-meta { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

.kb-main { flex: 1; overflow-y: auto; padding: 24px; }
.kb-header { margin-bottom: 20px; }
.kb-header h2 { font-size: 20px; margin-bottom: 6px; }
.kb-desc { color: var(--text-secondary); font-size: 13px; margin-bottom: 12px; }
.kb-actions { display: flex; gap: 8px; }

.doc-table { overflow: hidden; }
.doc-table-header, .doc-table-row {
  display: grid; grid-template-columns: 2fr 0.5fr 0.6fr 1fr 0.7fr 0.3fr;
  padding: 10px 16px; align-items: center; font-size: 13px;
}
.doc-table-header {
  background: var(--bg-hover); font-weight: 600; color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
}
.doc-table-row { border-bottom: 1px solid var(--border); }
.doc-table-row:last-child { border-bottom: none; }
.doc-col-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-col-status { }
.ingestion-error { font-size: 11px; color: var(--danger); margin-top: 2px; }

.upload-progress { padding: 16px; margin-top: 16px; }
.progress-header { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 8px; }
.progress-bar { height: 6px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }

.dialog-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.3);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.dialog { width: 420px; padding: 24px; }
.dialog h3 { margin-bottom: 16px; }
.dialog input, .dialog textarea {
  width: 100%; margin-bottom: 12px; display: block;
}
.dialog textarea { resize: vertical; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>
