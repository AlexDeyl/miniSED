import { defineStore } from 'pinia'
import { ref } from 'vue'

// Вкладки разделов «Комплименты» и «Заявки для исполнения». Кнопки живут в
// сайдбаре (App.vue), списки — во вьюхах, поэтому режимы в сторе.
export type ComplimentsMode = 'todo' | 'draft' | 'in_progress' | 'approved' | 'executed' | 'all'
export type ExecutionMode = 'new' | 'work' | 'archive'

export const COMPLIMENT_TABS: { code: ComplimentsMode; label: string }[] = [
  { code: 'todo', label: 'Требуется действие' },
  { code: 'draft', label: 'Черновики' },
  { code: 'in_progress', label: 'На согласовании' },
  { code: 'approved', label: 'Согласованные' },
  { code: 'executed', label: 'Исполненные' },
  { code: 'all', label: 'Все' },
]

export const EXECUTION_TABS: { code: ExecutionMode; label: string }[] = [
  { code: 'new', label: 'Новые' },
  { code: 'work', label: 'В работе' },
  { code: 'archive', label: 'Исполненные' },
]

export const useComplimentsUiStore = defineStore('complimentsUi', () => {
  const mode = ref<ComplimentsMode>('all')
  const executionMode = ref<ExecutionMode>('new')
  // Бейджи: ждут моего решения / ждут моего исполнения.
  const todoCount = ref(0)
  const executionCount = ref(0)
  return { mode, executionMode, todoCount, executionCount }
})
