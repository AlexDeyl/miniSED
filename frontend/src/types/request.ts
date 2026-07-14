import type { ApprovalDetail } from './approval'

export type RequestType = 'poa' | 'mchd' | 'ecp'
export type RequestStatus =
  | 'draft'
  | 'on_approval'
  | 'returned'
  | 'rejected'
  | 'approved'
  | 'to_legal'
  | 'legal_work'
  | 'signing'
  | 'executed'
  | 'closed'
  | 'canceled'

export interface RouteSlot {
  order: number
  role_code: string
  role_name: string
  required: boolean
  resolved: boolean
  b24_user_id: number | null
  user_name: string
  needs_manual: boolean
}

export interface RequestDocument {
  id: number
  title: string
  current_version_number: number | null
  download_url: string | null
}

export interface RegulatoryRequestListItem {
  id: number
  number: string
  request_type: RequestType
  type_display: string
  status: RequestStatus
  status_display: string
  subject_name: string
  organization: number
  organization_name: string
  created_at: string
}

export interface RegulatoryRequestDetail extends RegulatoryRequestListItem {
  facility: number | null
  cfo: number | null
  initiator_b24_id: number | null
  subject_b24_id: number | null
  position: string
  department: string
  basis: string
  valid_from: string | null
  valid_until: string | null
  comment: string
  data: Record<string, unknown>
  delivery_method: string
  delivery_method_display: string
  delivery_comment: string
  executed_at: string | null
  received_at: string | null
  external_1c_id: string
  external_diadoc_id: string
  updated_at: string
  approval: ApprovalDetail | null
  documents: RequestDocument[]
}

export interface RequestCreatePayload {
  request_type: RequestType
  organization: number
  facility?: number | null
  cfo?: number | null
  subject_name?: string
  position?: string
  department?: string
  basis?: string
}
