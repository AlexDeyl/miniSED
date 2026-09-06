import { defineStore } from 'pinia'
import { ref } from 'vue'

// Раздел «Работа ИТ» — исполнение заявок на ЭЦП. Устроен как раздел юристов:
// вкладки живут в сайдбаре (App.vue), список — в ItQueueView.
export type ItScope = 'new' | 'work' | 'archive' | 'all'

export const IT_TABS: { code: ItScope; label: string }[] = [
  { code: 'new', label: 'Новые' },
  { code: 'work', label: 'В работе' },
  { code: 'archive', label: 'Архив' },
  { code: 'all', label: 'Все' },
]

export const useItUiStore = defineStore('itUi', () => {
  const scope = ref<ItScope>('new')
  // Бейдж в сайдбаре: сколько заявок ждёт, чтобы их взяли в работу.
  const newCount = ref(0)
  return { scope, newCount }
})
