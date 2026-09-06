import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { readAdminMode, writeAdminMode } from '@/utils/adminMode'

// Режим администратора: включается кнопкой в шапке, доступен только тем, у кого
// есть право сквозного просмотра (роль «Системный администратор»). Пока включён,
// сотрудник видит ВСЕ карточки и может принять решение за любого согласующего;
// каждое такое решение помечается как принятое администратором.
//
// Состояние держим в localStorage: режим должен пережить переход между
// разделами и перезагрузку, иначе им невозможно пользоваться. Право при этом
// проверяет сервер на каждом запросе — заголовок сам по себе ничего не даёт.
export const useAdminModeStore = defineStore('adminMode', () => {
  const auth = useAuthStore()
  const enabled = ref(readAdminMode())

  // Доступен ли переключатель этому пользователю.
  const available = computed(() => auth.canViewAll)
  // Фактически включён: право могли отобрать, пока флаг лежал в localStorage.
  const active = computed(() => available.value && enabled.value)

  watch(enabled, writeAdminMode)

  function toggle() {
    if (available.value) enabled.value = !enabled.value
  }

  return { enabled, available, active, toggle }
})
