import { defineStore } from 'pinia'
import { ref } from 'vue'

// Раздел «Иное» — то, что не относится к визированию: создание свободного
// согласования и шаблоны маршрутов для него. Вкладки живут в сайдбаре
// (App.vue), содержимое — в OtherView, поэтому режим в сторе.
export type OtherMode = 'create' | 'templates'

export const OTHER_TABS: { code: OtherMode; label: string }[] = [
  { code: 'create', label: 'Новое согласование' },
  { code: 'templates', label: 'Шаблоны' },
]

export const useOtherUiStore = defineStore('otherUi', () => {
  const mode = ref<OtherMode>('create')
  return { mode }
})
