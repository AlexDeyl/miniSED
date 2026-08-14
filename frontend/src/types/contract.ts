import type { ApprovalDetail } from './approval'
import type { DocumentVersion } from './document'

export type ContractStatus =
  | 'draft'
  | 'on_approval'
  | 'returned'
  | 'rejected'
  | 'approved'
  | 'canceled'

export interface ContractRouteSlot {
  order: number
  role_code: string
  role_name: string
  role_class: 'approver' | 'signer'
  required: boolean
  group: boolean
  resolved: boolean
  b24_user_id: number | null
  user_name: string
  needs_manual: boolean
}

export interface ContractDocument {
  id: number
  title: string
  document_type?: string
  current_version_number: number | null
  // download_url — актуальная версия; полная история версий — в versions.
  download_url: string | null
  versions: DocumentVersion[]
  can_edit_online: boolean
}

export interface ContractListItem {
  id: number
  number: string
  title: string
  amount: string | null
  status: ContractStatus
  status_display: string
  organization: number
  organization_name: string
  cfo: number | null
  cfo_name: string | null
  created_at: string
}

export interface ContractDetail extends ContractListItem {
  is_nonstandard: boolean
  has_disagreement_protocol: boolean
  initiator_b24_id: number | null
  crm_link: string
  comment: string
  data: Record<string, unknown>
  updated_at: string
  approval: ApprovalDetail | null
  documents: ContractDocument[]
}

export interface ContractCreatePayload {
  title: string
  organization: number
  cfo?: number | null
  amount?: string | null
  is_nonstandard?: boolean
  has_disagreement_protocol?: boolean
  crm_link?: string
  comment?: string
}
