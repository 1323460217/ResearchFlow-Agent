import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router/index.js'
import { useAuthStore } from './stores/auth.js'
import './style.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia).use(router)

const authStore = useAuthStore()
await authStore.init()

app.mount('#app')
