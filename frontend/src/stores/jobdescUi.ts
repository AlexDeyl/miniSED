import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { HrScope } from '@/services/jobdesc'

// Вкладки разделов «Должностные инструкции» и «Заявки для отдела по работе с
// персоналом». Кнопки живут в сайдбаре (App.vue), списки — во вьюхах.
export type JobDescMode = 'todo' | 'draft' | 'in_progress' | 'hr' | 'done' | 'all'

export const JOBDESC_TABS: { code: JobDescMode; label: string }[] = [
  { code: 'todo', label: 'Требуется действие' },
  { code: 'draft', label: 'Черновики' },
  { code: 'in_progress', label: 'На согласовании' },
  { code: 'hr', label: 'У отдела персонала' },
  { code: 'done', label: 'Исполненные' },
  { code: 'all', label: 'Все' },
]

export const HR_TABS: { code: HrScope; label: string }[] = [
  { code: 'new', label: 'Новые' },
  { code: 'work', label: 'В работе' },
  { code: 'signing', label: 'На подписании' },
  { code: 'done', label: 'Исполненные' },
]

export const useJobDescUiStore = defineStore('jobdescUi', () => {
  const mode = ref<JobDescMode>('all')
  const hrScope = ref<HrScope>('new')
  // Бейджи: ждут моего действия / новые в разделе отдела персонала.
  const todoCount = ref(0)
  const hrNewCount = ref(0)
  return { mode, hrScope, todoCount, hrNewCount }
})
