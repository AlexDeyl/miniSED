import { api } from './api'
import type { ParticipantInput } from '@/types/approval'
import type {
  ContractCreatePayload,
  ContractDetail,
  ContractListItem,
  ContractRouteSlot,
} from '@/types/contract'

const BASE = '/contracts'

export interface Organization { id: number; short_name: string }
export interface Cfo { id: number; name: string; code: string; category?: string; organization: number | null }
export interface UserOption { id: number; fio: string; bitrix_id: number; position_name?: string }

export const contracts = {
  organizations: () => api.get<Organization[]>('/core/organizations/'),
  cfos: () => api.get<Cfo[]>('/core/cfos/'),
  users: () => api.get<UserOption[]>('/core/users/'),

  // scope: mine — созданные мной (по умолчанию), participant — где я согласующий,
  // all — и то, и другое (вкладки раздела).
  // q — поиск по номеру, названию, юрлицу/ЦФО и именам вложенных файлов.
  list: (scope: 'mine' | 'participant' | 'all' = 'mine', q?: string) => {
    const p = new URLSearchParams({ scope })
    if (q) p.set('q', q)
    return api.get<ContractListItem[]>(`${BASE}/?${p.toString()}`)
  },
  // Договоры, ждущие моего решения — для общего «Требует действия».
  todo: () => api.get<ContractListItem[]>(`${BASE}/todo/`),
  get: (id: number | string) => api.get<ContractDetail>(`${BASE}/${id}/`),
  create: (payload: ContractCreatePayload) =>
    api.post<ContractDetail>(`${BASE}/`, payload),
  // Правка карточки инициатором (черновик / возвращён / отклонён).
  update: (id: number | string, payload: Partial<ContractCreatePayload>) =>
    api.patch<ContractDetail>(`${BASE}/${id}/`, payload),

  routePreview: (id: number | string) =>
    api.get<{ route: ContractRouteSlot[] }>(`${BASE}/${id}/route_preview/`),
  // comment — пояснение инициатора согласующим (что изменилось после доработки).
  submit: (id: number | string, participants: ParticipantInput[], comment = '') =>
    api.post<ContractDetail>(`${BASE}/${id}/submit/`, { participants, comment }),
  decide: (id: number | string, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<ContractDetail>(`${BASE}/${id}/decide/`, {
      participant_id: participantId, decision, comment,
    }),
  returnForRevision: (id: number | string, comment: string) =>
    api.post<ContractDetail>(`${BASE}/${id}/return/`, { comment }),
  cancel: (id: number | string) => api.post<ContractDetail>(`${BASE}/${id}/cancel/`),
  sheetPdfUrl: (id: number | string) => `/api${BASE}/${id}/sheet_pdf/`,
  remove: (id: number | string) => api.delete<void>(`${BASE}/${id}/`),

  uploadDocument: (id: number | string, file: File, title: string) => {
    const form = new FormData()
    form.append('title', title)
    form.append('linked_type', 'contracts.contract')
    form.append('linked_id', String(id))
    form.append('file', file)
    return api.postForm(`/documents/`, form)
  },

  meta: () =>
    api.get<{
      statuses: { code: string; name: string }[]
      roles: { code: string; name: string }[]
      cfo_categories: { code: string; name: string }[]
    }>(`${BASE}/meta/`),
}
