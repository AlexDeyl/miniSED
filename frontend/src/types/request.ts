import type { ApprovalDetail } from './approval'

export type RequestType = 'ecp' | 'mchd' | 'poa'
export type RequestStatus =
  | 'draft'
  | 'on_approval'
  | 'returned'
  | 'approved'
  | 'in_work'
  | 'issued'
  | 'rejected'
  | 'closed'

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
  external_1c_id: string
  external_diadoc_id: string
  updated_at: string
  approval: ApprovalDetail | null
}

export interface RequestCreatePayload {
  request_type: RequestType
  organization: number
  subject_name?: string
  position?: string
  department?: string
  basis?: string
}
