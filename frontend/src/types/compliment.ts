import type { ApprovalDetail } from './approval'
import type { DocumentVersion } from './document'

export type ComplimentStatus =
  | 'draft'
  | 'on_approval'
  | 'returned'
  | 'rejected'
  | 'approved'
  | 'in_work'
  | 'executed'
  | 'canceled'

// Категория определяет весь маршрут: и согласующих, и исполнителя.
export type ComplimentCategory = 'confectionery' | 'restaurant' | 'stay'

export interface ComplimentRouteSlot {
  order: number
  role_code: string
  role_name: string
  role_class: 'approver' | 'executor'
  required: boolean
  resolved: boolean
  b24_user_id: number | null
  user_name: string
  needs_manual: boolean
}

export interface ComplimentDocument {
  id: number
  title: string
  document_type?: string
  current_version_number: number | null
  download_url: string | null
  versions: DocumentVersion[]
  can_edit_online: boolean
}

export interface ComplimentListItem {
  id: number
  number: string
  title: string
  category: ComplimentCategory
  category_display: string
  company: string
  event_at: string | null
  facility: number | null
  facility_name: string | null
  status: ComplimentStatus
  status_display: string
  initiator_b24_id: number | null
  executor_b24_id: number | null
  created_at: string
}

export interface ComplimentDetail extends ComplimentListItem {
  category_details: string
  guest_name: string
  description: string
  department: string
  organization: number | null
  needs_ceo: boolean
  data: Record<string, unknown>
  taken_at: string | null
  executed_at: string | null
  execution_comment: string
  updated_at: string
  approval: ApprovalDetail | null
  documents: ComplimentDocument[]
}

export interface ComplimentCreatePayload {
  title: string
  category: ComplimentCategory
  company: string
  category_details?: string
  guest_name?: string
  event_at?: string | null
  facility?: number | null
  organization?: number | null
  description?: string
  department?: string
  needs_ceo?: boolean
}
