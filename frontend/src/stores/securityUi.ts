import { defineStore } from 'pinia'
import { ref } from 'vue'

// Раздел «Работа службы безопасности» — исполнение заявок на проверку лица.
// Устроен как разделы юристов и ИТ: вкладки в сайдбаре (App.vue), список —
// в SecurityQueueView.
export type SecurityScope = 'new' | 'work' | 'archive' | 'all'

export const SECURITY_TABS: { code: SecurityScope; label: string }[] = [
  { code: 'new', label: 'Новые' },
  { code: 'work', label: 'В работе' },
  { code: 'archive', label: 'Архив' },
  { code: 'all', label: 'Все' },
]

export const useSecurityUiStore = defineStore('securityUi', () => {
  const scope = ref<SecurityScope>('new')
  // Бейдж в сайдбаре: сколько согласованных заявок ждут, чтобы их взяли.
  const newCount = ref(0)
  return { scope, newCount }
})
