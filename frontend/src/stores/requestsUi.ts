import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { RequestType } from '@/types/request'

// Фильтр типа регламентных заявок. В сторе, т.к. кнопки-вкладки живут в
// сайдбаре (App.vue), а список — в RequestsView (как у светофора).
export type RequestTypeFilter = '' | RequestType

export const REQUEST_TYPE_TABS: { code: RequestTypeFilter; label: string }[] = [
  { code: '', label: 'Все' },
  { code: 'ecp', label: 'ЭЦП' },
  { code: 'mchd', label: 'МЧД' },
  { code: 'poa', label: 'Доверенности' },
  { code: 'revoke', label: 'Отзывы' },
]

export const useRequestsUiStore = defineStore('requestsUi', () => {
  const typeFilter = ref<RequestTypeFilter>('')
  return { typeFilter }
})
