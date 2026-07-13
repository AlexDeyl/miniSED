import { api } from './api'
import type { ParticipantInput } from '@/types/approval'
import type {
  RegulatoryRequestDetail,
  RegulatoryRequestListItem,
  RequestCreatePayload,
} from '@/types/request'

const BASE = '/reg/requests'

export interface Organization {
  id: number
  short_name: string
}

export const requests = {
  list: (type?: string) =>
    api.get<RegulatoryRequestListItem[]>(`${BASE}/${type ? `?type=${type}` : ''}`),

  get: (id: number | string) => api.get<RegulatoryRequestDetail>(`${BASE}/${id}/`),

  create: (payload: RequestCreatePayload) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/`, payload),

  submit: (id: number | string, participants: ParticipantInput[], flowType = 'sequential') =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/submit/`, {
      participants,
      flow_type: flowType,
    }),

  decide: (
    id: number | string,
    participantId: number,
    decision: 'approve' | 'reject',
    comment = '',
  ) =>
    api.post<RegulatoryRequestDetail>(`${BASE}/${id}/decide/`, {
      participant_id: participantId,
      decision,
      comment,
    }),

  inWork: (id: number | string) => api.post<RegulatoryRequestDetail>(`${BASE}/${id}/in_work/`),
  issue: (id: number | string) => api.post<RegulatoryRequestDetail>(`${BASE}/${id}/issue/`),
  close: (id: number | string) => api.post<RegulatoryRequestDetail>(`${BASE}/${id}/close/`),

  types: () =>
    api.get<{ types: { code: string; name: string }[]; statuses: { code: string; name: string }[] }>(
      `${BASE}/types/`,
    ),

  organizations: () => api.get<Organization[]>('/core/organizations/'),
}
