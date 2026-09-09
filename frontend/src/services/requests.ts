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
export interface Cfo { id: number; name: string; code: string; organization: number | null }
export interface UserOption { id: number; fio: string; bitrix_id: number; position_name?: string }

export const requests = {
  // q — поиск по номеру, ФИО, организации и анкете доверенности.
  // scope: mine — созданные мной (по умолчанию), participant — где я
  // согласующий (этим живёт рабочее место визирования), all — и то, и другое.
  list: (type?: string, q?: string, scope?: 'mine' | 'participant' | 'all') => {
    const p = new URLSearchParams()
    if (type) p.set('type', type)
    if (q) p.set('q', q)
    if (scope) p.set('scope', scope)
    const qs = p.toString()
    return api.get<RegulatoryRequestListItem[]>(`${BASE}/${qs ? `?${qs}` : ''}`)
  },
  // Доверенности и МЧД, которые можно отозвать — для привязки к заявке на
  // отзыв. Отдаёт только выданные, и только видимые мне (свои, где я
  // согласующий, и — руководителю ЦФО — доверенности его ЦФО).
  revocable: (q?: string) =>
    api.get<RegulatoryRequestListItem[]>(
      `${BASE}/revocable/${q ? `?q=${encodeURIComponent(q)}` : ''}`,
    ),
  // Заявки, ждущие моего решения — для общего списка «Требует действия».
  todo: () => api.get<RegulatoryRequestListItem[]>(`${BASE}/todo/`),
  get: (id: number | string) => api.get<RegulatoryRequestDetail>(`${BASE}/${id}/`),
  create: (payload: RequestCreatePayload) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/`, payload),
  // Правка полей заявки инициатором: сервер пускает только черновик,
  // возвращённую на доработку и отклонённую (requests_reg EDITABLE_STATUSES).
  update: (id: number | string, payload: Partial<RequestCreatePayload>) =>
    api.patch<RegulatoryRequestDetail>(`${BASE}/${id}/`, payload),

  routePreview: (id: number | string) =>
    api.get<{ route: RouteSlot[] }>(`${BASE}/${id}/route_preview/`),
  // comment — пояснение инициатора согласующим (что изменилось после доработки).
  submit: (id: number | string, participants: ParticipantInput[], comment = '') =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/submit/`, { participants, comment }),
  cancel: (id: number | string) => api.post<RegulatoryRequestDetail>(`${BASE}/${id}/cancel/`),
  returnForRevision: (id: number | string, comment: string) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/return/`, { comment }),
  remove: (id: number | string) => api.delete<void>(`${BASE}/${id}/`),
  decide: (id: number | string, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/decide/`, {
      participant_id: participantId, decision, comment,
    }),

  // При непустом q сервер ищет по ВСЕМ статусам, игнорируя вкладку (ищут дубли).
  legalQueue: (scope?: string, q?: string) => {
    const p = new URLSearchParams()
    if (scope) p.set('scope', scope)
    if (q) p.set('q', q)
    const qs = p.toString()
    return api.get<RegulatoryRequestListItem[]>(`${BASE}/legal_queue/${qs ? `?${qs}` : ''}`)
  },
  // --- исполнение заявок на ЭЦП (ИТ-специалист объекта) ---
  itQueue: (scope?: string, q?: string) => {
    const p = new URLSearchParams()
    if (scope) p.set('scope', scope)
    if (q) p.set('q', q)
    const qs = p.toString()
    return api.get<RegulatoryRequestListItem[]>(`${BASE}/it_queue/${qs ? `?${qs}` : ''}`)
  },
  itTake: (id: number | string) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/it_take/`),
  itExecute: (id: number | string, comment = '') =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/it_execute/`, { comment }),

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
      revoke_reasons?: { code: string; name: string }[]
      revoke_kinds?: { code: string; name: string }[]
    }>(`${BASE}/types/`),

  powerTemplates: () =>
    api.get<{ code: string; name: string; powers: string }[]>(`${BASE}/power_templates/`),
  anketaPdfUrl: (id: number | string) => `/api${BASE}/${id}/anketa_pdf/`,
  sheetPdfUrl: (id: number | string) => `/api${BASE}/${id}/sheet_pdf/`,

  organizations: () => api.get<Organization[]>('/core/organizations/'),
  facilities: (org?: number) => api.get<Facility[]>(`/core/facilities/${org ? `?organization=${org}` : ''}`),
  cfos: () => api.get<Cfo[]>('/core/cfos/'),
  users: () => api.get<UserOption[]>('/core/users/'),

  // Справочник подразделений ФМС по коду (XXX-XXX) → «кем выдан».
  fmsUnit: (code: string) =>
    api
      .get<{ results: { value: string; code: string }[] }>(`/reg/fms-unit/?code=${encodeURIComponent(code)}`)
      .then((r) => r.results),

  // Подсказки по адресу (DaData) для автокомплита.
  addressSuggest: (q: string) =>
    api
      .get<{ results: { value: string; postal_code: string }[] }>(`/reg/address-suggest/?q=${encodeURIComponent(q)}`)
      .then((r) => r.results),
}
