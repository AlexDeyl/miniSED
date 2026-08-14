import { defineStore } from 'pinia'
import { ref } from 'vue'

// Вкладки раздела «Договоры». Как у согласований и заявок, кнопки живут в
// сайдбаре (App.vue), а список — в ContractsView, поэтому режим в сторе.
export type ContractsMode = 'todo' | 'draft' | 'in_progress' | 'completed' | 'rejected' | 'all'

export const CONTRACT_TABS: { code: ContractsMode; label: string }[] = [
  { code: 'todo', label: 'Требуется действие' },
  { code: 'draft', label: 'Черновики' },
  { code: 'in_progress', label: 'На согласовании' },
  { code: 'completed', label: 'Согласованные' },
  { code: 'rejected', label: 'Отклонённые' },
  { code: 'all', label: 'Все' },
]

export const useContractsUiStore = defineStore('contractsUi', () => {
  const mode = ref<ContractsMode>('all')
  // Сколько договоров ждут моего решения — бейдж на вкладке «Требуется действие».
  const todoCount = ref(0)
  return { mode, todoCount }
})
