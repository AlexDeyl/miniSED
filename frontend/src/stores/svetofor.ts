import { defineStore } from 'pinia'
import { ref } from 'vue'

// Режим списка рабочего места визирования (вкладки). Вынесен в стор, потому
// что кнопки живут в сайдбаре (App.vue), а список — в SvetoforView.
export type SvetoforMode =
  | 'todo'
  | 'in_progress'
  | 'rejected'
  | 'completed'
  | 'all'

export const SVETOFOR_TABS: { code: SvetoforMode; label: string }[] = [
  { code: 'todo', label: 'Требуется действие' },
  { code: 'in_progress', label: 'В работе' },
  { code: 'rejected', label: 'Отклонённые' },
  { code: 'completed', label: 'Завершённые' },
  { code: 'all', label: 'Все' },
]

export const useSvetoforStore = defineStore('svetofor', () => {
  const mode = ref<SvetoforMode>('todo')
  // Счётчики для бейджей в сайдбаре (обновляются в SvetoforView, видны независимо
  // от активной вкладки):
  //  - todoCount    — ждут моего решения (согласования + заявки + договоры
  //    + комплименты);
  //  - rejectedUnseen / completedUnseen — мои согласования, которые я ещё не
  //    открывал после того, как их отклонили / завершили.
  const todoCount = ref(0)
  const rejectedUnseen = ref(0)
  const completedUnseen = ref(0)
  return { mode, todoCount, rejectedUnseen, completedUnseen }
})
