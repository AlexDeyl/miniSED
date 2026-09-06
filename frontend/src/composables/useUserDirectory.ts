// Справочник b24_id → ФИО/должность: карточки показывают людей по именам, а
// в данных согласований лежат только id Битрикса. Наполняется из профилей
// MiniSED и дополняется из самого Битрикса для тех, кого в профилях нет.
//
// Вынесен из SvetoforView: тем же справочником пользуется форма нового
// согласования, переехавшая в раздел «Иное».
import { ref } from 'vue'
import { requests } from '@/services/requests'
import { bitrix } from '@/services/bitrix'

export interface DirEntry { fio: string; position?: string }

export function useUserDirectory() {
  const userDir = ref<Record<number, DirEntry>>({})
  // домен портала — для сборки полной ссылки на сделку при выборе через коннектор
  const portalDomain = ref('')

  async function loadUserDir() {
    try {
      for (const u of await requests.users()) {
        userDir.value[u.bitrix_id] = { fio: u.fio, position: u.position_name || '' }
      }
    } catch { /* не критично */ }
    try { portalDomain.value = (await bitrix.status()).domain || '' } catch { /* не критично */ }
  }

  function udName(id: number | null | undefined): string {
    return (id != null && userDir.value[id]?.fio) || (id != null ? `USER #${id}` : '')
  }
  function udPos(id: number | null | undefined): string {
    return (id != null && userDir.value[id]?.position) || ''
  }
  function udInitials(id: number | null | undefined): string {
    const known = id != null && userDir.value[id]?.fio
    if (!known) return 'U#'
    const parts = known.trim().split(/\s+/).filter(Boolean)
    const s = parts.length >= 2 ? parts[0][0] + parts[1][0] : known.trim().slice(0, 2)
    return s.toUpperCase()
  }

  // Дозагрузка ФИО/должности из Битрикса для id, которых нет в справочнике
  // (реальные сотрудники портала, не заведённые в профилях). Вне Битрикса — no-op.
  async function enrichUsers(ids: (number | null | undefined)[]) {
    const need = [...new Set(ids.filter((x): x is number => x != null && userDir.value[x] === undefined))]
    if (!need.length) return
    try {
      const { results } = await bitrix.usersByIds(need)
      for (const u of results) {
        const id = Number(u.ID)
        if (Number.isNaN(id)) continue
        const fio = [u.LAST_NAME, u.NAME, u.SECOND_NAME].filter(Boolean).join(' ') || `USER #${id}`
        userDir.value[id] = { fio, position: u.WORK_POSITION || '' }
      }
    } catch { /* вне Битрикса недоступно */ }
  }

  return { userDir, portalDomain, loadUserDir, udName, udPos, udInitials, enrichUsers }
}
