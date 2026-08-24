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
  // Раздел юристов — юристам и администратору со сквозным просмотром.
  if (to.meta.lawyerOnly && !auth.isLawyer && !auth.canViewAll) {
    return { path: '/svetofor' }
  }
  return true
})

// Куда открыть приложение: ссылка из уведомления («Перейти к согласованию»)
// приходит как /app/?to=/contracts/5. Сервер кладёт маршрут в __MINISED_BOOT__,
// но читаем и сам адрес — на случай прямой ссылки мимо обработчика.
function deepLinkRoute(): string {
  const boot = (window as unknown as { __MINISED_BOOT__?: { route?: string } }).__MINISED_BOOT__
  const raw = boot?.route || new URLSearchParams(window.location.search).get('to') || ''
  return raw.startsWith('/') && !raw.startsWith('//') ? raw : ''
}

// Читаем ДО auth.init(): он удаляет __MINISED_BOOT__, забрав оттуда токен.
const deepLink = deepLinkRoute()

// Сначала восстанавливаем сессию (токен/URL), затем монтируем.
auth.init().finally(() => {
  const target = deepLink
  app.use(router)
  // Гость попадёт на /login и вернётся сюда после входа (guard кладёт next).
  if (target) router.replace(target).catch(() => {})
  app.mount('#app')
})
