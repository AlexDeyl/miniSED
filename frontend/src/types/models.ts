// Типы, отражающие текущие сериализаторы Django (approvals/serializers.py).
// По мере рефактора Этапа 4 (Approval/ApprovalRound/...) будут расширяться.

export type AgreementStatus =
  | 'draft'
  | 'in_progress'
  | 'completed'
  | 'rejected'
  | 'canceled'

export type FlowType = 'parallel' | 'sequential'

export type ParticipantType = 'internal' | 'external'
export type ParticipantStatus = 'waiting' | 'approved' | 'rejected'

export interface AgreementDocument {
  id: number
  type: 'file' | 'link'
  file: string | null
  url: string
  name: string
}

export interface Participant {
  id: number
  type: ParticipantType
  b24_user_id: number | null
  email: string
  name: string
  status: ParticipantStatus
  comment: string
  decided_at: string | null
  order_index: number
  prev_status: ParticipantStatus | null
  prev_comment: string
}

export interface Agreement {
  id: number
  title: string
  description: string
  amount: string | null
  author_b24_id: number
  deadline: string | null
  crm_link: string
  flow_type: FlowType
  status: AgreementStatus
  created_at: string
  documents: AgreementDocument[]
  participants: Participant[]
}

export const STATUS_LABELS: Record<AgreementStatus, string> = {
  draft: 'Черновик',
  in_progress: 'В работе',
  completed: 'Согласован',
  rejected: 'Отклонён',
  canceled: 'Отменено',
}
