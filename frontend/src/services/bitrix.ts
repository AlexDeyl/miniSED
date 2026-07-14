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
  usersByIds: (ids: number[]) =>
    api.get<ListResponse<BitrixUser>>(`/bitrix/users/?ids=${ids.join(',')}`),

  addTimelineComment: (dealId: number | string, comment: string) =>
    api.post<{ id: unknown }>('/bitrix/timeline/', { deal_id: dealId, comment }),
}
