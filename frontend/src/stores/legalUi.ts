import { defineStore } from 'pinia'
import { ref } from 'vue'

// Раздел работы юристов делится на Новые / В работе / Архив. Вкладки живут
// в сайдбаре (App.vue), список — в LegalQueueView.
export type LegalScope = 'new' | 'work' | 'archive'

export const LEGAL_TABS: { code: LegalScope; label: string }[] = [
  { code: 'new', label: 'Новые' },
  { code: 'work', label: 'В работе' },
  { code: 'archive', label: 'Архив' },
]

export const useLegalUiStore = defineStore('legalUi', () => {
  const scope = ref<LegalScope>('new')
  return { scope }
})
