import { api } from './api'
import type { ParticipantInput } from '@/types/approval'
import type {
  RegulatoryRequestDetail,
  RegulatoryRequestListItem,
  RequestCreatePayload,
  RouteSlot,
} from '@/types/request'

const BASE = '/reg/requests'

export interface Organization { id: number; short_name: string }
export interface Facility { id: number; name: string; organization: number }
export interface Cfo { id: number; name: string; code: string; organization: number }
export interface UserOption { id: number; fio: string; bitrix_id: number; position_name?: string }

export const requests = {
  list: (type?: string) =>
    api.get<RegulatoryRequestListItem[]>(`${BASE}/${type ? `?type=${type}` : ''}`),
  // Заявки, ждущие моего решения — для общего списка «Требует действия».
  todo: () => api.get<RegulatoryRequestListItem[]>(`${BASE}/todo/`),
  get: (id: number | string) => api.get<RegulatoryRequestDetail>(`${BASE}/${id}/`),
  create: (payload: RequestCreatePayload) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/`, payload),

  routePreview: (id: number | string) =>
    api.get<{ route: RouteSlot[] }>(`${BASE}/${id}/route_preview/`),
  submit: (id: number | string, participants: ParticipantInput[]) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/submit/`, { participants }),
  cancel: (id: number | string) => api.post<RegulatoryRequestDetail>(`${BASE}/${id}/cancel/`),
  remove: (id: number | string) => api.delete<void>(`${BASE}/${id}/`),
  decide: (id: number | string, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/decide/`, {
      participant_id: participantId, decision, comment,
    }),

  legalQueue: (scope?: string) =>
    api.get<RegulatoryRequestListItem[]>(`${BASE}/legal_queue/${scope ? `?scope=${scope}` : ''}`),
  take: (id: number | string) => api.post<RegulatoryRequestDetail>(`${BASE}/${id}/take/`),
  toSigning: (id: number | string) => api.post<RegulatoryRequestDetail>(`${BASE}/${id}/to_signing/`),
  execute: (id: number | string, deliveryMethod: string, deliveryComment = '') =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/execute/`, {
      delivery_method: deliveryMethod, delivery_comment: deliveryComment,
    }),
  confirmReceipt: (id: number | string) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/confirm_receipt/`),

  uploadDocument: (id: number | string, file: File, title: string) => {
    const form = new FormData()
    form.append('title', title)
    form.append('linked_type', 'requests_reg.regulatoryrequest')
    form.append('linked_id', String(id))
    form.append('file', file)
    return api.postForm(`/documents/`, form)
  },

  types: () =>
    api.get<{
      types: { code: string; name: string }[]
      statuses: { code: string; name: string }[]
      delivery_methods: { code: string; name: string }[]
      roles?: { code: string; name: string }[]
    }>(`${BASE}/types/`),

  powerTemplates: () =>
    api.get<{ code: string; name: string; powers: string }[]>(`${BASE}/power_templates/`),
  anketaPdfUrl: (id: number | string) => `/api${BASE}/${id}/anketa_pdf/`,
  sheetPdfUrl: (id: number | string) => `/api${BASE}/${id}/sheet_pdf/`,

  organizations: () => api.get<Organization[]>('/core/organizations/'),
  facilities: (org?: number) => api.get<Facility[]>(`/core/facilities/${org ? `?organization=${org}` : ''}`),
  cfos: () => api.get<Cfo[]>('/core/cfos/'),
  users: () => api.get<UserOption[]>('/core/users/'),
}
