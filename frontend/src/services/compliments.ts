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
  list: (scope: 'mine' | 'participant' | 'all' = 'mine') =>
    api.get<ComplimentListItem[]>(`${BASE}/?scope=${scope}`),
  // Заявки, ждущие моего решения — в общий «Требует действия».
  todo: () => api.get<ComplimentListItem[]>(`${BASE}/todo/`),
  get: (id: number | string) => api.get<ComplimentDetail>(`${BASE}/${id}/`),
  create: (payload: ComplimentCreatePayload) =>
    api.post<ComplimentDetail>(`${BASE}/`, payload),

  routePreview: (id: number | string) =>
    api.get<{ route: ComplimentRouteSlot[] }>(`${BASE}/${id}/route_preview/`),
  submit: (id: number | string, participants: ParticipantInput[]) =>
    api.post<ComplimentDetail>(`${BASE}/${id}/submit/`, { participants }),
  decide: (id: number | string, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<ComplimentDetail>(`${BASE}/${id}/decide/`, {
      participant_id: participantId, decision, comment,
    }),
  returnForRevision: (id: number | string, comment: string) =>
    api.post<ComplimentDetail>(`${BASE}/${id}/return/`, { comment }),
  cancel: (id: number | string) => api.post<ComplimentDetail>(`${BASE}/${id}/cancel/`),
  remove: (id: number | string) => api.delete<void>(`${BASE}/${id}/`),

  // --- исполнение ---
  executionQueue: (scope: 'new' | 'work' | 'archive' = 'new') =>
    api.get<ComplimentListItem[]>(`${BASE}/execution_queue/?scope=${scope}`),
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
