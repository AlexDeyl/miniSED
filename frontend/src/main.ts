import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './assets/main.css'

const app = createApp(App)
app.use(createPinia())

const auth = useAuthStore()

// Пускаем в приложение только авторизованных; иначе — на /login.
router.beforeEach((to) => {
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'login', query: to.fullPath !== '/' ? { next: to.fullPath } : {} }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return { path: '/svetofor' }
  }
  return true
})

// Сначала восстанавливаем сессию (токен/URL), затем монтируем.
auth.init().finally(() => {
  app.use(router)
  app.mount('#app')
})
