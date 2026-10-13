import { defineStore } from 'pinia'
import { ref } from 'vue'

// Реестр доверенностей и МЧД: вкладки по виду живут в сайдбаре (App.vue),
// таблица — в PoaRegistryView.
export type RegistryTab = '' | 'poa' | 'mchd'

export const REGISTRY_TABS: { code: RegistryTab; label: string }[] = [
  { code: '', label: 'Все' },
  { code: 'poa', label: 'Доверенности' },
  { code: 'mchd', label: 'МЧД' },
]

export const useRegistryUiStore = defineStore('registryUi', () => {
  const kind = ref<RegistryTab>('')
  return { kind }
})
