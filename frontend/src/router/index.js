import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Chat', component: () => import('../views/ChatView.vue') },
  { path: '/knowledge-bases', name: 'KnowledgeBases', component: () => import('../views/KnowledgeBaseView.vue'), meta: { requiresAuth: true } },
  { path: '/knowledge-bases/:id', name: 'KnowledgeBaseDetail', component: () => import('../views/KnowledgeBaseView.vue'), props: true, meta: { requiresAuth: true } },
  { path: '/reports', name: 'Reports', component: () => import('../views/ReportsView.vue'), meta: { requiresAuth: true } },
  { path: '/reports/:id', name: 'ReportDetail', component: () => import('../views/ReportsView.vue'), props: true, meta: { requiresAuth: true } },
  { path: '/workflow', name: 'Workflow', component: () => import('../views/WorkflowMonitor.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to, _from, next) => {
  if (to.meta.requiresAuth) {
    const { useAuthStore } = await import('../stores/auth.js')
    const authStore = useAuthStore()
    if (!authStore.isAuthenticated) {
      next({ path: '/', query: { login: 'required' } })
      return
    }
  }
  next()
})

export default router
