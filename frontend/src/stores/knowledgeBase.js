import { defineStore } from 'pinia'
import { ref } from 'vue'
import { kbApi, uploadApi, workflowApi } from '../api/index.js'

export const useKnowledgeBaseStore = defineStore('knowledgeBase', () => {
  const knowledgeBases = ref([])
  const currentKBId = ref(null)
  const documents = ref([])
  const uploading = ref(false)
  const uploadProgress = ref(0)
  const uploadStatus = ref('')

  const currentKB = ref(null)

  async function loadKnowledgeBases() {
    try {
      const data = await kbApi.list()
      knowledgeBases.value = data.items || data || []
    } catch (e) { console.error('loadKnowledgeBases failed:', e.message || e) }
  }

  async function selectKB(id) {
    currentKBId.value = id
    currentKB.value = knowledgeBases.value.find(kb => kb.id === id)
    if (id) {
      try {
        const data = await kbApi.listDocs(id)
        documents.value = data.items || data || []
      } catch (e) {
        console.error('selectKB failed:', e.message || e)
        documents.value = []
      }
    } else {
      documents.value = []
    }
  }

  async function createKB(name, description) {
    await kbApi.create(name, description)
    await loadKnowledgeBases()
  }

  async function deleteKB(id) {
    await kbApi.delete(id)
    if (currentKBId.value === id) {
      currentKBId.value = null
      currentKB.value = null
      documents.value = []
    }
    await loadKnowledgeBases()
  }

  async function deleteDocument(kbId, docId) {
    await kbApi.deleteDoc(kbId, docId)
    documents.value = documents.value.filter(d => d.id !== docId)
    if (currentKB.value) {
      currentKB.value.doc_count = Math.max(0, (currentKB.value.doc_count || 1) - 1)
    }
  }

  async function rebuildIndex(id) {
    await kbApi.rebuildIndex(id)
    await selectKB(id)
  }

  async function uploadDocument(kbId, file) {
    uploading.value = true
    uploadProgress.value = 0
    uploadStatus.value = 'parsing'

    try {
      // Simulate progress since ingestion is now synchronous in the API
      const progressTimer = setInterval(() => {
        uploadProgress.value = Math.min(uploadProgress.value + 12, 90)
        if (uploadProgress.value > 50) uploadStatus.value = 'embedding'
      }, 500)

      const data = await uploadApi.upload(kbId, file)
      clearInterval(progressTimer)

      if (data.status === 'failed') {
        throw new Error(data.message || '处理失败')
      }

      uploadProgress.value = 100
      uploadStatus.value = 'done'
      if (currentKBId.value) {
        await selectKB(currentKBId.value)
      }
    } catch (e) {
      uploadStatus.value = 'failed'
      throw e
    } finally {
      uploading.value = false
    }
  }

  function reset() {
    knowledgeBases.value = []
    currentKBId.value = null
    documents.value = []
    uploading.value = false
    uploadProgress.value = 0
    uploadStatus.value = ''
    currentKB.value = null
  }

  return {
    knowledgeBases, currentKBId, documents, uploading, uploadProgress,
    uploadStatus, currentKB,
    loadKnowledgeBases, selectKB, createKB, deleteKB, rebuildIndex,
    deleteDocument, uploadDocument, reset,
  }
})
