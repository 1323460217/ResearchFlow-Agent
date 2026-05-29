import axios from 'axios'

const http = axios.create({
  baseURL: '/',
  timeout: 120000,
})

// ── Request interceptor: attach auth token ──────────
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── Response interceptor: unwrap ApiResponse ─────────
http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (typeof body === 'object' && body !== null && 'code' in body) {
      if (body.code === 0) {
        return body.data
      }
      const err = new Error(body.message || 'API error')
      err.code = body.code
      err.detail = body.detail
      throw err
    }
    return body
  },
  (err) => {
    // Handle 401 globally — clear auth state and redirect
    if (err.response?.status === 401) {
      localStorage.removeItem('auth_token')
      // Dynamically import to avoid circular dep
      import('../stores/auth.js').then(({ useAuthStore }) => {
        const authStore = useAuthStore()
        if (authStore.isAuthenticated) {
          authStore.logout()
        }
      })
    }

    const body = err.response?.data
    if (body && typeof body === 'object') {
      // FastAPI 422 validation error format: { detail: [...] }
      if (Array.isArray(body.detail)) {
        const messages = body.detail.map(d => `${d.loc?.join('.')}: ${d.msg}`).join('; ')
        const e = new Error(messages || 'Validation failed')
        e.code = 422
        e.detail = body.detail
        throw e
      }
      if ('code' in body) {
        const e = new Error(body.message || 'Request failed')
        e.code = body.code
        e.detail = body.detail
        throw e
      }
    }
    throw err
  },
)

// ── Auth API ────────────────────────────────────────
export const authApi = {
  register: (username, email, password) =>
    http.post('/api/auth/register', { username, email, password }),
  login: (username, password) =>
    http.post('/api/auth/login', { username, password }),
  me: () => http.get('/api/auth/me'),
}

// ── Chat API (non-streaming) ────────────────────────
export const chatApi = {
  send: (body) => http.post('/api/chat', body),

  /** For SSE streaming – returns raw fetch Response for ReadableStream */
  async stream(body) {
    const token = localStorage.getItem('auth_token')
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))
      const err = new Error(errorBody.message || `请求失败 (HTTP ${response.status})`)
      err.code = errorBody.code || response.status
      throw err
    }

    return response
  },

  listConversations: () => http.get('/api/conversations'),
  getConversation: (id) => http.get(`/api/conversations/${id}`),
  deleteConversation: (id) => http.delete(`/api/conversations/${id}`),
}

// ── Knowledge Base API ──────────────────────────────
export const kbApi = {
  list: () => http.get('/api/knowledge-bases'),
  create: (name, description) =>
    http.post('/api/knowledge-bases', { name, description }),
  get: (kbId) => http.get(`/api/knowledge-bases/${kbId}`),
  delete: (kbId) => http.delete(`/api/knowledge-bases/${kbId}`),
  listDocs: (kbId) => http.get(`/api/knowledge-bases/${kbId}/docs`),
  deleteDoc: (kbId, docId) => http.delete(`/api/knowledge-bases/${kbId}/docs/${docId}`),
  rebuildIndex: (kbId) => http.post(`/api/knowledge-bases/${kbId}/rebuild`),
  search: (kbId, query, topK, strategy) =>
    http.post(`/api/knowledge-bases/${kbId}/search`, {
      query, top_k: topK, strategy,
    }),
}

// ── Upload API ──────────────────────────────────────
export const uploadApi = {
  upload: (kbId, file) => {
    const form = new FormData()
    form.append('file', file)
    if (kbId) form.append('knowledge_base_id', kbId)
    // Let axios auto-set Content-Type with correct boundary for FormData
    return http.post('/api/upload', form)
  },
}

// ── Report API ──────────────────────────────────────
export const reportApi = {
  list: () => http.get('/api/reports'),
  get: (reportId) => http.get(`/api/reports/${reportId}`),
  create: (body) => http.post('/api/reports', body),
  update: (reportId, body) => http.put(`/api/reports/${reportId}`, body),
  delete: (reportId) => http.delete(`/api/reports/${reportId}`),
}

// ── Workflow / Agent API ────────────────────────────
export const workflowApi = {
  listTasks: () => http.get('/api/workflow/tasks'),
  getTaskStatus: (taskId) => http.get(`/api/workflow/status/${taskId}`),
  listExecutions: () => http.get('/api/agent/executions'),
  clearExecutions: () => http.delete('/api/agent/executions'),
}

export default http
