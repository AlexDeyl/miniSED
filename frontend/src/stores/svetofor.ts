import { defineStore } from 'pinia'
import { ref } from 'vue'

// Режим списка согласований (вкладки). Вынесен в стор, потому что кнопки
// живут в сайдбаре (App.vue), а список — в SvetoforView.
export type SvetoforMode = 'todo' | 'my' | 'all' | 'templates'

export const SVETOFOR_TABS: { code: SvetoforMode; label: string }[] = [
  { code: 'todo', label: 'Требуется действие' },
  { code: 'my', label: 'Созданные мной' },
  { code: 'all', label: 'Все' },
  { code: 'templates', label: 'Шаблоны' },
]

export const useSvetoforStore = defineStore('svetofor', () => {
  const mode = ref<SvetoforMode>('todo')
  return { mode }
})
