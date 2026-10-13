import { api } from './api'
import type { ParticipantInput } from '@/types/approval'
import type {
  HrStaffOption,
  JobDescDetail,
  JobDescListItem,
  JobDescMeta,
  JobDescPayload,
  JobDescRouteSlot,
} from '@/types/jobdesc'

const BASE = '/jobdesc'

// Тип документа «готовая ДИ» — без него заявку нельзя отметить исполненной.
export const DOC_TYPE_FINAL = 'jd_final'

export type HrScope = 'new' | 'work' | 'signing' | 'done'

export const jobdesc = {
  // scope: mine — мои заявки, participant — где я согласующий, all — всё
  // доступное (отделу персонала — все отправленные заявки).
  list: (scope: 'mine' | 'participant' | 'all' = 'mine', q?: string) => {
    const p = new URLSearchParams({ scope })
    if (q) p.set('q', q)
    return api.get<JobDescListItem[]>(`${BASE}/?${p.toString()}`)
  },
  // Ждут моего решения либо моего «Получил / ознакомился».
  todo: () => api.get<JobDescListItem[]>(`${BASE}/todo/`),
  get: (id: number | string) => api.get<JobDescDetail>(`${BASE}/${id}/`),
  create: (payload: JobDescPayload) => api.post<JobDescDetail>(`${BASE}/`, payload),
  update: (id: number | string, payload: Partial<JobDescPayload>) =>
    api.patch<JobDescDetail>(`${BASE}/${id}/`, payload),

  routePreview: (id: number | string) =>
    api.get<{ route: JobDescRouteSlot[] }>(`${BASE}/${id}/route_preview/`),
  submit: (id: number | string, participants: ParticipantInput[], comment = '') =>
    api.post<JobDescDetail>(`${BASE}/${id}/submit/`, { participants, comment }),
  decide: (id: number | string, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<JobDescDetail>(`${BASE}/${id}/decide/`, { participant_id: participantId, decision, comment }),
  returnForRevision: (id: number | string, comment: string) =>
    api.post<JobDescDetail>(`${BASE}/${id}/return/`, { comment }),
  cancel: (id: number | string) => api.post<JobDescDetail>(`${BASE}/${id}/cancel/`),
  remove: (id: number | string) => api.delete<void>(`${BASE}/${id}/`),

  // --- исполнение отделом по работе с персоналом ---
  hrQueue: (scope: HrScope = 'new', q?: string) => {
    const p = new URLSearchParams({ scope })
    if (q) p.set('q', q)
    return api.get<JobDescListItem[]>(`${BASE}/hr_queue/?${p.toString()}`)
  },
  take: (id: number | string) => api.post<JobDescDetail>(`${BASE}/${id}/take/`),
  setStatus: (id: number | string, status: 'hr_work' | 'signing') =>
    api.post<JobDescDetail>(`${BASE}/${id}/set_status/`, { status }),
  execute: (id: number | string, transferMethod: string, comment = '') =>
    api.post<JobDescDetail>(`${BASE}/${id}/execute/`, { transfer_method: transferMethod, comment }),
  acknowledge: (id: number | string) => api.post<JobDescDetail>(`${BASE}/${id}/acknowledge/`),

  hrStaff: () => api.get<HrStaffOption[]>(`${BASE}/hr_staff/`),
  syncHrStaff: () =>
    api.post<{ departments: string[]; total: number; added: number; removed: number; staff: HrStaffOption[] }>(
      `${BASE}/hr_staff/sync/`,
    ),

  sheetPdfUrl: (id: number | string) => `/api${BASE}/${id}/sheet_pdf/`,

  uploadDocument: (id: number | string, file: File, title: string, documentType = '') => {
    const form = new FormData()
    form.append('title', title)
    form.append('linked_type', 'jobdesc.jobdescription')
    form.append('linked_id', String(id))
    if (documentType) form.append('document_type', documentType)
    form.append('file', file)
    return api.postForm(`/documents/`, form)
  },

  meta: () => api.get<JobDescMeta>(`${BASE}/meta/`),
}
