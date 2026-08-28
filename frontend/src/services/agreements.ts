import { api } from './api'
import type { Agreement, AgreementTemplate } from '@/types/agreement'

// Старый движок согласований (approvals app). Личность — из профиля/заголовка.
export const agreements = {
  todo: () => api.get<Agreement[]>('/agreements/todo/'),
  my: () => api.get<Agreement[]>('/agreements/my/'),
  // Всё, к чему я имею отношение (автор, участник, юр-дела своего отдела).
  // status — фильтр вкладок, чтобы не тянуть весь архив на каждую.
  // q — поиск по названию, описанию, сделке, участникам и именам вложенных
  // файлов; при непустом запросе сервер игнорирует вкладку (status).
  all: (status?: string, q?: string) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    if (q) p.set('q', q)
    const qs = p.toString()
    return api.get<Agreement[]>(`/agreements/${qs ? `?${qs}` : ''}`)
  },
  get: (id: number) => api.get<Agreement>(`/agreements/${id}/`),

  // Счётчики для бейджей вкладок (отклонённые/завершённые — непросмотренные мной).
  badgeCounts: () =>
    api.get<{ rejected_unseen: number; completed_unseen: number; in_progress: number }>(
      '/agreements/badge_counts/',
    ),
  // Отметить согласование просмотренным (сбрасывает «непросмотрено»).
  markSeen: (id: number) =>
    api.post('/core/seen/', { linked_type: 'approvals.agreement', linked_id: id }),

  decide: (id: number, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<{ status: string }>(`/agreements/${id}/decide/`, {
      participant_id: participantId, decision, comment,
    }),
  restart: (id: number) => api.post<Agreement & { internal_to_notify: number[] }>(`/agreements/${id}/restart/`),
  // comment — пояснение инициатора согласующим (что изменилось после доработки).
  resubmit: (
    id: number,
    participants?: { type: string; b24_user_id: number | null; email: string; order_index: number }[],
    comment = '',
  ) =>
    api.post<Agreement>(`/agreements/${id}/resubmit/`, {
      ...(participants ? { participants } : {}), comment,
    }),
  setRoute: (id: number, participants: { type: string; b24_user_id: number | null; email: string; order_index: number }[]) =>
    api.post<Agreement>(`/agreements/${id}/set_route/`, { participants }),
  cancel: (id: number) => api.post<Agreement>(`/agreements/${id}/cancel/`),
  remove: (id: number) => api.delete<void>(`/agreements/${id}/`),

  updateDocuments: (id: number, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return api.postForm<Agreement>(`/agreements/${id}/update_document/`, form)
  },

  create: (payload: {
    title: string
    description?: string
    amount?: string
    deadline?: string
    crm_link?: string
    flow_type?: string
    internal_users?: string
    external_emails?: string
    files?: File[]
  }) => {
    const form = new FormData()
    form.append('title', payload.title)
    if (payload.description) form.append('description', payload.description)
    if (payload.amount) form.append('amount', payload.amount)
    if (payload.deadline) form.append('deadline', payload.deadline)
    if (payload.crm_link) form.append('crm_link', payload.crm_link)
    if (payload.flow_type) form.append('flow_type', payload.flow_type)
    if (payload.internal_users) form.append('internal_users', payload.internal_users)
    if (payload.external_emails) form.append('external_emails', payload.external_emails)
    ;(payload.files || []).forEach((f) => form.append('files', f))
    return api.postForm<Agreement>('/agreements/create_simple/', form)
  },

  sheetPdfUrl: (id: number) => `/api/agreements/${id}/sheet_pdf/`,

  // версионируемые документы через приложение documents
  addDocument: (agreementId: number, file: File, title: string) => {
    const form = new FormData()
    form.append('title', title)
    form.append('linked_type', 'approvals.agreement')
    form.append('linked_id', String(agreementId))
    form.append('file', file)
    return api.postForm('/documents/', form)
  },
  addVersion: (docId: number, file: File, comment = '') => {
    const form = new FormData()
    form.append('file', file)
    if (comment) form.append('change_comment', comment)
    return api.postForm(`/documents/${docId}/versions/`, form)
  },

  templates: () => api.get<AgreementTemplate[]>('/templates/'),
  createTemplate: (payload: {
    name: string
    scope: string
    participants: { type: string; b24_user_id: number | null; email: string; name: string; order_index: number }[]
  }) => api.post<AgreementTemplate>('/templates/', payload),
}
