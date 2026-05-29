import { defineStore } from 'pinia'
import { ref } from 'vue'
import { reportApi } from '../api/index.js'

export const useReportStore = defineStore('report', () => {
  const reports = ref([])
  const currentReportId = ref(null)
  const currentReport = ref(null)
  const loading = ref(false)
  const error = ref('')

  async function loadReports() {
    loading.value = true
    error.value = ''
    try {
      const data = await reportApi.list()
      reports.value = data.items || data || []
    } catch (e) {
      error.value = e.message || '加载报告失败'
      console.error('loadReports failed:', e.message || e)
    } finally {
      loading.value = false
    }
  }

  async function selectReport(id) {
    currentReportId.value = id
    loading.value = true
    error.value = ''
    try {
      const data = await reportApi.get(id)
      currentReport.value = data
    } catch (e) {
      console.error('selectReport failed:', e.message || e)
      currentReport.value = reports.value.find(r => String(r.id) === String(id)) || null
      if (!currentReport.value) {
        error.value = e.message || '报告未找到'
      }
    } finally {
      loading.value = false
    }
  }

  async function createReport(payload) {
    const data = await reportApi.create(payload)
    await loadReports()
    return data
  }

  async function updateReport(id, payload) {
    const data = await reportApi.update(id, payload)
    await loadReports()
    if (currentReportId.value === id) {
      await selectReport(id)
    }
    return data
  }

  async function refreshCurrentReport() {
    if (currentReportId.value) {
      await selectReport(currentReportId.value)
    }
  }

  async function deleteReport(id) {
    await reportApi.delete(id)
    if (currentReportId.value === id) {
      currentReportId.value = null
      currentReport.value = null
    }
    await loadReports()
  }

  function reset() {
    reports.value = []
    currentReportId.value = null
    currentReport.value = null
    loading.value = false
    error.value = ''
  }

  return {
    reports,
    currentReportId,
    currentReport,
    loading,
    error,
    loadReports,
    selectReport,
    createReport,
    updateReport,
    refreshCurrentReport,
    deleteReport,
    reset,
  }
})
