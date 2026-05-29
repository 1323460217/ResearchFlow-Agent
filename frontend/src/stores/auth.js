import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api/index.js'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const token = ref(null)
  const initialized = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const username = computed(() => user.value?.username ?? '')

  function _setToken(t) {
    token.value = t
    if (t) {
      localStorage.setItem('auth_token', t)
    } else {
      localStorage.removeItem('auth_token')
    }
  }

  async function fetchMe() {
    try {
      const data = await authApi.me()
      user.value = data
    } catch {
      user.value = null
      _setToken(null)
    }
  }

  async function init() {
    const saved = localStorage.getItem('auth_token')
    if (saved) {
      _setToken(saved)
      await fetchMe()
    }
    initialized.value = true
  }

  async function login(username_, password) {
    const data = await authApi.login(username_, password)
    _setToken(data.access_token || data.token)
    await fetchMe()
  }

  async function register(username_, email, password) {
    await authApi.register(username_, email, password)
    await login(username_, password)
  }

  function logout() {
    user.value = null
    _setToken(null)
  }

  return {
    user, token, initialized,
    isAuthenticated, username,
    init, login, register, logout, fetchMe,
  }
})
