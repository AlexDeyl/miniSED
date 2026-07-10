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
  WORK_POSITION?: string
  EMAIL?: string
}

interface ListResponse<T> {
  results: T[]
}

export const bitrix = {
  status: () => api.get<{ connected: boolean; domain: string | null }>('/bitrix/status/'),

  searchDeals: (q: string) =>
    api.get<ListResponse<BitrixDeal>>(`/bitrix/deals/?q=${encodeURIComponent(q)}`),

  getDeal: (id: number | string) => api.get<BitrixDeal>(`/bitrix/deals/${id}/`),

  searchUsers: (q: string) =>
    api.get<ListResponse<BitrixUser>>(`/bitrix/users/?q=${encodeURIComponent(q)}`),

  addTimelineComment: (dealId: number | string, comment: string) =>
    api.post<{ id: unknown }>('/bitrix/timeline/', { deal_id: dealId, comment }),
}
