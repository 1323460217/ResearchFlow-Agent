<script setup>
import { ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth.js'
import { useChatStore } from './stores/chat.js'
import { useKnowledgeBaseStore } from './stores/knowledgeBase.js'
import { useReportStore } from './stores/report.js'
import { useWorkflowStore } from './stores/workflow.js'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const chatStore = useChatStore()
const kbStore = useKnowledgeBaseStore()
const reportStore = useReportStore()
const workflowStore = useWorkflowStore()

const showAuthModal = ref(false)
const authTab = ref('login')
const authForm = ref({ username: '', email: '', password: '' })
const authError = ref('')
const authLoading = ref(false)

// Watch auth state: on logout, clear all stores; on login, reload data
watch(() => authStore.isAuthenticated, (newVal, oldVal) => {
  if (!newVal && oldVal) {
    // User logged out — reset all stores to clear previous user's data
    chatStore.reset()
    kbStore.reset()
    reportStore.reset()
    workflowStore.reset()
  }
  if (newVal && !oldVal) {
    // User logged in — reload data for the new user
    chatStore.loadConversations()
    kbStore.loadKnowledgeBases()
    reportStore.loadReports()
    workflowStore.loadTasks()
    workflowStore.loadExecutions()
  }
})


const navItems = [
  { path: '/', label: '对话', icon: '💬' },
  { path: '/knowledge-bases', label: '知识库', icon: '📚' },
  { path: '/reports', label: '研究报告', icon: '📝' },
  { path: '/workflow', label: '任务监控', icon: '⚙️' },
]

function isActive(path) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function openAuth(tab) {
  authTab.value = tab
  authForm.value = { username: '', email: '', password: '' }
  authError.value = ''
  showAuthModal.value = true
}

async function submitAuth() {
  authError.value = ''
  authLoading.value = true
  try {
    if (authTab.value === 'login') {
      await authStore.login(authForm.value.username, authForm.value.password)
    } else {
      await authStore.register(authForm.value.username, authForm.value.email, authForm.value.password)
    }
    showAuthModal.value = false
  } catch (e) {
    authError.value = e.message || e.response?.data?.message || '认证失败'
  } finally {
    authLoading.value = false
  }
}
</script>

<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <span class="logo">🔬</span>
        <span class="app-title">ResearchFlow</span>
      </div>
      <nav class="nav-list">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <template v-if="authStore.isAuthenticated">
          <div class="user-info">
            <span class="user-avatar">👤</span>
            <span class="user-name">{{ authStore.username }}</span>
          </div>
          <button class="btn-logout" @click="authStore.logout()">退出</button>
        </template>
        <template v-else>
          <button class="btn-login" @click="openAuth('login')">登录</button>
          <button class="btn-register-link" @click="openAuth('register')">注册</button>
        </template>
      </div>
    </aside>
    <main class="main-content">
      <router-view />
    </main>

    <!-- Auth Modal -->
    <Teleport to="body">
      <div v-if="showAuthModal" class="modal-overlay" @click.self="showAuthModal = false">
        <div class="auth-modal">
          <h2 class="modal-title">{{ authTab === 'login' ? '登录' : '注册' }}</h2>
          <div class="modal-tabs">
            <button :class="{ active: authTab === 'login' }" @click="authTab = 'login'">登录</button>
            <button :class="{ active: authTab === 'register' }" @click="authTab = 'register'">注册</button>
          </div>
          <form class="auth-form" @submit.prevent="submitAuth">
            <input v-model="authForm.username" placeholder="用户名" required />
            <input v-if="authTab === 'register'" v-model="authForm.email" type="email" placeholder="邮箱" required />
            <input v-model="authForm.password" type="password" placeholder="密码" required minlength="6" />
            <p v-if="authError" class="auth-error">{{ authError }}</p>
            <button type="submit" class="btn-submit" :disabled="authLoading">
              {{ authLoading ? '请稍候...' : (authTab === 'login' ? '登录' : '注册') }}
            </button>
          </form>
          <button class="modal-close" @click="showAuthModal = false">✕</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.app-layout { display: flex; height: 100vh; background: var(--bg-primary); }

.sidebar {
  width: 220px; background: var(--bg-sidebar); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; flex-shrink: 0;
}
.sidebar-header {
  display: flex; align-items: center; gap: 10px; padding: 20px 18px;
  border-bottom: 1px solid var(--border);
}
.logo { font-size: 24px; }
.app-title { font-size: 16px; font-weight: 700; color: var(--text-primary); }

.nav-list { flex: 1; padding: 12px 8px; display: flex; flex-direction: column; gap: 2px; }
.nav-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  border-radius: 8px; text-decoration: none; color: var(--text-secondary);
  font-size: 14px; transition: all 0.15s;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.nav-item.active { background: var(--accent-bg); color: var(--accent); font-weight: 600; }
.nav-icon { font-size: 18px; width: 24px; text-align: center; }

.sidebar-footer {
  padding: 12px 18px; border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 6px;
}
.user-info { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.user-avatar { font-size: 18px; }
.user-name { font-size: 13px; color: var(--text-primary); font-weight: 500; }

.btn-login, .btn-logout, .btn-register-link, .btn-submit {
  width: 100%; padding: 8px 0; border-radius: 6px; border: none;
  font-size: 13px; cursor: pointer; transition: all 0.15s;
}
.btn-login { background: var(--accent); color: #fff; }
.btn-login:hover { opacity: 0.9; }
.btn-register-link { background: transparent; color: var(--text-secondary); }
.btn-register-link:hover { background: var(--bg-hover); }
.btn-logout { background: var(--bg-hover); color: var(--text-secondary); }
.btn-logout:hover { background: #fee2e2; color: #dc2626; }

.main-content { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

/* Modal */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.auth-modal {
  background: var(--bg-primary); border-radius: 12px; padding: 24px;
  width: 360px; max-width: 90vw; position: relative;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.modal-title { font-size: 18px; margin: 0 0 12px; color: var(--text-primary); }
.modal-tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.modal-tabs button {
  flex: 1; padding: 6px 0; border: none; border-radius: 6px;
  font-size: 13px; cursor: pointer; background: var(--bg-hover); color: var(--text-secondary);
}
.modal-tabs button.active { background: var(--accent-bg); color: var(--accent); font-weight: 600; }

.auth-form { display: flex; flex-direction: column; gap: 10px; }
.auth-form input {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px;
  font-size: 14px; background: var(--bg-sidebar); color: var(--text-primary);
  outline: none;
}
.auth-form input:focus { border-color: var(--accent); }
.auth-error { color: #dc2626; font-size: 12px; margin: 0; }
.btn-submit { background: var(--accent); color: #fff; }
.btn-submit:disabled { opacity: 0.6; cursor: not-allowed; }
.modal-close {
  position: absolute; top: 12px; right: 12px;
  background: none; border: none; font-size: 16px; cursor: pointer;
  color: var(--text-muted);
}
</style>
