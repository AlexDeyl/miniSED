// Типы под сериализаторы approvalflow (Django).

export type ApprovalStatus =
  | 'draft'
  | 'in_progress'
  | 'returned'
  | 'completed'
  | 'rejected'
  | 'canceled'
  | 'closed'

export type FlowType = 'parallel' | 'sequential'
export type ParticipantType = 'internal' | 'external'
export type Decision = 'waiting' | 'approved' | 'rejected'
export type RoundResult = 'pending' | 'approved' | 'rejected' | 'returned'

export interface ApprovalParticipant {
  id: number
  type: ParticipantType
  b24_user_id: number | null
  email: string
  name: string
  role: string
  order: number
  is_required: boolean
  decision: Decision
  decision_comment: string
  decided_at: string | null
  /** Решение проставил администратор за этого согласующего (его ID Б24). */
  admin_override_by_b24_id: number | null
}

export interface ApprovalRound {
  id: number
  round_number: number
  result: RoundResult
  // чем круг закрыли (причина возврата) и с чем инициатор его открыл
  comment: string
  opening_comment: string
  started_at: string
  completed_at: string | null
  participants: ApprovalParticipant[]
}

export interface ApprovalSheet {
  id: number
  format: string
  generated_at: string
  generated_by_b24_id: number | null
  file_url: string
}

export interface ApprovalListItem {
  id: number
  approval_type: string
  title: string
  flow_type: FlowType
  status: ApprovalStatus
  status_display: string
  current_round: number
  initiator_b24_id: number | null
  created_at: string
}

export interface ApprovalDocument {
  id: number
  title: string
  current_version_number: number | null
  download_url: string | null
  can_edit_online: boolean
}

export interface ApprovalDetail extends ApprovalListItem {
  submitted_at: string | null
  completed_at: string | null
  object_id: number | null
  linked_type: string | null
  rounds: ApprovalRound[]
  sheets: ApprovalSheet[]
  route_changes: unknown[]
  documents: ApprovalDocument[]
}

export interface ParticipantInput {
  type: ParticipantType
  b24_user_id?: number | null
  email?: string
  name?: string
  role?: string
  order: number
  is_required?: boolean
}

export const APPROVAL_STATUS_CLASS: Record<ApprovalStatus, string> = {
  draft: '',
  in_progress: 'in_progress',
  returned: 'returned',
  completed: 'completed',
  rejected: 'rejected',
  canceled: '',
  closed: 'completed',
}
