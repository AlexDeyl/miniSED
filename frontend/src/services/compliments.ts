import { api } from './api'
import type { ParticipantInput } from '@/types/approval'
import type {
  ComplimentCreatePayload,
  ComplimentDetail,
  ComplimentListItem,
  ComplimentRouteSlot,
} from '@/types/compliment'

const BASE = '/compliments'

export interface Facility { id: number; name: string; organization: number | null }

export const compliments = {
  facilities: () => api.get<Facility[]>('/core/facilities/'),

  // scope: mine — мои заявки (по умолчанию), participant — где я согласующий,
  // all — всё, что мне доступно (руководителю продаж — все заявки).
  // q — поиск по компании, гостю, отелю и именам вложенных файлов.
  list: (scope: 'mine' | 'participant' | 'all' = 'mine', q?: string) => {
    const p = new URLSearchParams({ scope })
    if (q) p.set('q', q)
    return api.get<ComplimentListItem[]>(`${BASE}/?${p.toString()}`)
  },
  // Заявки, ждущие моего решения — в общий «Требует действия».
  todo: () => api.get<ComplimentListItem[]>(`${BASE}/todo/`),
  get: (id: number | string) => api.get<ComplimentDetail>(`${BASE}/${id}/`),
  create: (payload: ComplimentCreatePayload) =>
    api.post<ComplimentDetail>(`${BASE}/`, payload),
  // Правка полей заявки инициатором (черновик / возвращена / отклонена).
  update: (id: number | string, payload: Partial<ComplimentCreatePayload>) =>
    api.patch<ComplimentDetail>(`${BASE}/${id}/`, payload),

  routePreview: (id: number | string) =>
    api.get<{ route: ComplimentRouteSlot[] }>(`${BASE}/${id}/route_preview/`),
  // comment — пояснение инициатора согласующим (что изменилось после доработки).
  submit: (id: number | string, participants: ParticipantInput[], comment = '') =>
    api.post<ComplimentDetail>(`${BASE}/${id}/submit/`, { participants, comment }),
  decide: (id: number | string, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<ComplimentDetail>(`${BASE}/${id}/decide/`, {
      participant_id: participantId, decision, comment,
    }),
  returnForRevision: (id: number | string, comment: string) =>
    api.post<ComplimentDetail>(`${BASE}/${id}/return/`, { comment }),
  cancel: (id: number | string) => api.post<ComplimentDetail>(`${BASE}/${id}/cancel/`),
  remove: (id: number | string) => api.delete<void>(`${BASE}/${id}/`),

  // --- исполнение ---
  // q — поиск по очереди исполнения; при непустом запросе вкладка не сужает
  // выборку (заявку ищут, не зная её статуса).
  executionQueue: (scope: 'new' | 'work' | 'archive' = 'new', q?: string) => {
    const p = new URLSearchParams({ scope })
    if (q) p.set('q', q)
    return api.get<ComplimentListItem[]>(`${BASE}/execution_queue/?${p.toString()}`)
  },
  take: (id: number | string) => api.post<ComplimentDetail>(`${BASE}/${id}/take/`),
  execute: (id: number | string, comment = '') =>
    api.post<ComplimentDetail>(`${BASE}/${id}/execute/`, { comment }),

  // --- документы на выходе ---
  formPdfUrl: (id: number | string, withSheet = true) =>
    `/api${BASE}/${id}/form_pdf/${withSheet ? '?with_sheet=1' : ''}`,
  sheetPdfUrl: (id: number | string) => `/api${BASE}/${id}/sheet_pdf/`,

  uploadDocument: (id: number | string, file: File, title: string) => {
    const form = new FormData()
    form.append('title', title)
    form.append('linked_type', 'compliments.compliment')
    form.append('linked_id', String(id))
    form.append('file', file)
    return api.postForm(`/documents/`, form)
  },

  meta: () =>
    api.get<{
      statuses: { code: string; name: string }[]
      categories: { code: string; name: string }[]
      roles: { code: string; name: string }[]
    }>(`${BASE}/meta/`),
}
