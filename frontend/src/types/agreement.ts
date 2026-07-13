// Типы старого движка согласований (approvals app) — «классический светофор».

export type AgreementStatus =
  | 'draft'
  | 'in_progress'
  | 'completed'
  | 'rejected'
  | 'canceled'

export type FlowType = 'parallel' | 'sequential'
export type PartType = 'internal' | 'external'
export type PartStatus = 'waiting' | 'approved' | 'rejected'

export interface AgDocument {
  id: number
  type: 'file' | 'link'
  file: string | null
  url: string
  name: string
}

export interface AgParticipant {
  id: number
  type: PartType
  b24_user_id: number | null
  email: string
  name: string
  status: PartStatus
  comment: string
  decided_at: string | null
  order_index: number
  round_number: number
  prev_status: PartStatus | null
  prev_comment: string
}

export interface DecisionLog {
  id: number
  participant: AgParticipant
  status: PartStatus
  comment: string
  round_number: number
  decided_at: string
}

export interface DocVersion {
  id: number
  version_number: number
  uploaded_at: string
  uploaded_by_b24_id: number | null
  change_comment: string
  is_current: boolean
  download_url: string
}

export interface VersionedDoc {
  id: number
  title: string
  current_version_number: number | null
  versions: DocVersion[]
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
  current_round: number
  created_at: string
  documents: AgDocument[]
  documents_v: VersionedDoc[]
  participants: AgParticipant[]
  decision_logs: DecisionLog[]
}

export interface AgreementTemplate {
  id: number
  name: string
  description: string
  scope: string
  participants: {
    type: PartType
    b24_user_id: number | null
    email: string
    name: string
    order_index: number
  }[]
}

export const AG_STATUS_LABEL: Record<AgreementStatus, string> = {
  draft: 'Черновик',
  in_progress: 'В работе',
  completed: 'Согласован',
  rejected: 'Отклонён',
  canceled: 'Отменено',
}
