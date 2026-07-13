import { api } from './api'
import type {
  ApprovalDetail,
  ApprovalListItem,
  FlowType,
  ParticipantInput,
} from '@/types/approval'

const BASE = '/approvalflow/approvals'

export const approvalflow = {
  list: () => api.get<ApprovalListItem[]>(`${BASE}/`),

  get: (id: number | string) => api.get<ApprovalDetail>(`${BASE}/${id}/`),

  create: (payload: { approval_type: string; title: string; flow_type: FlowType }) =>
    api.post<ApprovalDetail>(`${BASE}/`, payload),

  submit: (id: number | string, participants: ParticipantInput[]) =>
    api.post<ApprovalDetail>(`${BASE}/${id}/submit/`, { participants }),

  decide: (
    id: number | string,
    participantId: number,
    decision: 'approve' | 'reject',
    comment = '',
  ) =>
    api.post<ApprovalDetail>(`${BASE}/${id}/decide/`, {
      participant_id: participantId,
      decision,
      comment,
    }),

  returnForRevision: (id: number | string, comment: string) =>
    api.post<ApprovalDetail>(`${BASE}/${id}/return/`, { comment }),

  newRound: (id: number | string, participants: ParticipantInput[]) =>
    api.post<ApprovalDetail>(`${BASE}/${id}/new_round/`, { participants }),

  cancel: (id: number | string) => api.post<ApprovalDetail>(`${BASE}/${id}/cancel/`),

  generateSheet: (id: number | string) =>
    api.post<{ id: number; file_url: string }>(`${BASE}/${id}/generate_sheet/`),

  uploadDocument: (id: number | string, file: File) => {
    const form = new FormData()
    form.append('title', file.name)
    form.append('linked_type', 'approvalflow.approval')
    form.append('linked_id', String(id))
    form.append('file', file)
    return api.postForm('/documents/', form)
  },
}
