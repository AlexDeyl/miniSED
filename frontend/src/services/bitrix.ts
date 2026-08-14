import { api } from './api'

// Клиент к серверному Bitrix Connector (/api/bitrix/*).
// Раньше поиск шёл через клиентский BX24.selectCRM/selectUsers и работал
// только в iframe. Теперь всё через backend — работает и с домена.

export interface BitrixDeal {
  ID: string
  TITLE: string
  OPPORTUNITY?: string
  CURRENCY_ID?: string
  COMPANY_ID?: string
}

export interface BitrixUser {
  ID: string
  NAME?: string
  LAST_NAME?: string
  SECOND_NAME?: string
  WORK_POSITION?: string
  EMAIL?: string
}

interface ListResponse<T> {
  results: T[]
}

// Запись справочника сотрудников (структурно совместима с UserOption
// из services/contracts.ts и services/requests.ts).
export interface BitrixUserOption {
  id: number
  bitrix_id: number
  fio: string
  position_name: string
}

const usersByIds = (ids: number[]) =>
  api.get<ListResponse<BitrixUser>>(`/bitrix/users/?ids=${ids.join(',')}`)

export const bitrix = {
  status: () => api.get<{ connected: boolean; domain: string | null }>('/bitrix/status/'),

  // Сохранить токены портала (из BX24.getAuth внутри iframe) для серверного Connector.
  storeAuth: (a: {
    domain: string
    member_id?: string
    access_token: string
    refresh_token?: string
    expires_in?: number
  }) => api.post<{ domain: string; connected: boolean }>('/bitrix/auth/', a),

  searchDeals: (q: string) =>
    api.get<ListResponse<BitrixDeal>>(`/bitrix/deals/?q=${encodeURIComponent(q)}`),

  getDeal: (id: number | string) => api.get<BitrixDeal>(`/bitrix/deals/${id}/`),

  searchUsers: (q: string) =>
    api.get<ListResponse<BitrixUser>>(`/bitrix/users/?q=${encodeURIComponent(q)}`),

  // Сотрудники по списку b24-id (ФИО/должность) — для показа имён в согласованиях.
  usersByIds,

  // То же, но сразу в формате справочника сотрудников: участник, выбранный
  // поиском по Битриксу, может отсутствовать в матрице UserProfile — без этой
  // дозагрузки он показывается как «USER #id».
  userOptionsByIds: async (ids: number[]): Promise<BitrixUserOption[]> => {
    if (!ids.length) return []
    const { results } = await usersByIds(ids)
    return results
      .map((u) => ({
        id: Number(u.ID),
        bitrix_id: Number(u.ID),
        fio: [u.LAST_NAME, u.NAME, u.SECOND_NAME].filter(Boolean).join(' '),
        position_name: u.WORK_POSITION || '',
      }))
      .filter((u) => u.bitrix_id && u.fio)
  },

  addTimelineComment: (dealId: number | string, comment: string) =>
    api.post<{ id: unknown }>('/bitrix/timeline/', { deal_id: dealId, comment }),
}
