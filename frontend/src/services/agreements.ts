import { api } from './api'
import type { Agreement, AgreementTemplate } from '@/types/agreement'

// Старый движок согласований (approvals app). Личность — из профиля/заголовка.
export const agreements = {
  todo: () => api.get<Agreement[]>('/agreements/todo/'),
  my: () => api.get<Agreement[]>('/agreements/my/'),
  all: () => api.get<Agreement[]>('/agreements/'),
  get: (id: number) => api.get<Agreement>(`/agreements/${id}/`),

  decide: (id: number, participantId: number, decision: 'approve' | 'reject', comment = '') =>
    api.post<{ status: string }>(`/agreements/${id}/decide/`, {
      participant_id: participantId, decision, comment,
    }),
  restart: (id: number) => api.post<Agreement & { internal_to_notify: number[] }>(`/agreements/${id}/restart/`),
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

  templates: () => api.get<AgreementTemplate[]>('/templates/'),
  createTemplate: (payload: {
    name: string
    scope: string
    participants: { type: string; b24_user_id: number | null; email: string; name: string; order_index: number }[]
  }) => api.post<AgreementTemplate>('/templates/', payload),
}
