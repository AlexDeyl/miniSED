// Выбор сотрудников и сделок Битрикс24. Внутри портала работает нативный
// диалог BX24 (SDK в iframe), снаружи — модалка серверного коннектора.
// Вызывающий передаёт, куда положить результат: одна и та же машинерия нужна
// и форме нового согласования, и правке маршрута в карточке.
import { ref, type Ref } from 'vue'
import type { BitrixDeal, BitrixUser } from '@/services/bitrix'
import type { DirEntry } from './useUserDirectory'

interface BX24User { id: string | number; name?: string; position?: string }
interface BX24CrmItem { id: string | number; title?: string; url?: string }
interface BX24SDK {
  init(cb: () => void): void
  getAuth(): { domain?: string } | false
  selectUsers?(cb: (users: BX24User[]) => void): void
  selectCRM?(
    params: { entityType?: string[]; multiple?: boolean },
    cb: (res: Record<string, BX24CrmItem[]>) => void,
  ): void
}

function bx24(): BX24SDK | undefined {
  return (window as unknown as { BX24?: BX24SDK }).BX24
}

/** Слить выбранные id с уже введёнными («1, 2, 3») без дублей. */
export function mergeIds(current: string, picked: number[]): string {
  const existing = current.split(',').map((s) => s.trim()).filter(Boolean).map(Number)
  return Array.from(new Set([...existing, ...picked])).join(', ')
}

export function useBitrixPicker(
  userDir: Ref<Record<number, DirEntry>>,
  portalDomain: Ref<string>,
) {
  const pickerKind = ref<'users' | 'deals' | null>(null)
  const applyUsers = ref<(ids: number[]) => void>(() => {})
  const applyDeal = ref<(link: string) => void>(() => {})

  /** Выбор сотрудников; apply получает id, ФИО попадают в справочник. */
  function pickUsers(apply: (ids: number[]) => void) {
    const BX24 = bx24()
    if (BX24 && BX24.selectUsers) {
      BX24.init(() => {
        BX24.selectUsers!((users) => {
          const ids: number[] = []
          for (const u of users) {
            const id = Number(u.id)
            if (Number.isNaN(id)) continue
            ids.push(id)
            userDir.value[id] = { fio: u.name || `USER #${id}`, position: u.position || '' }
          }
          apply(ids)
        })
      })
      return
    }
    applyUsers.value = apply
    pickerKind.value = 'users'
  }

  /** Выбор сделки; apply получает готовую ссылку на карточку CRM. */
  function pickDeal(apply: (link: string) => void) {
    const BX24 = bx24()
    if (!BX24 || !BX24.selectCRM) {
      applyDeal.value = apply
      pickerKind.value = 'deals'
      return
    }
    BX24.init(() => {
      BX24.selectCRM!({ entityType: ['deal'], multiple: false }, (res) => {
        const deal = res?.deal?.[0]
        if (!deal) return
        const auth = BX24.getAuth()
        const domain = (auth && auth.domain) || ''
        // deal.url приходит относительным (/crm/deal/show/ID/) — дополняем
        // доменом портала до полной ссылки, как в старом миниседе.
        let link = deal.url || (domain ? `/crm/deal/show/${deal.id}/` : String(deal.id))
        if (link.startsWith('/') && domain) link = `https://${domain}${link}`
        apply(link)
      })
    })
  }

  // --- результат из модалки коннектора ---
  function onPickUser(u: BitrixUser) {
    const id = Number(u.ID)
    if (Number.isNaN(id)) return
    userDir.value[id] = {
      fio: [u.LAST_NAME, u.NAME, u.SECOND_NAME].filter(Boolean).join(' ') || `USER #${id}`,
      position: u.WORK_POSITION || '',
    }
    applyUsers.value([id])
  }
  function onPickDeal(d: BitrixDeal) {
    const dom = portalDomain.value
    applyDeal.value(dom ? `https://${dom}/crm/deal/details/${d.ID}/` : String(d.ID))
    pickerKind.value = null
  }

  return { pickerKind, pickUsers, pickDeal, onPickUser, onPickDeal }
}
