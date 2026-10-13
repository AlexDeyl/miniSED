import type { ApprovalDetail } from './approval'
import type { DocumentVersion } from './document'

export type JobDescStatus =
  | 'draft'
  | 'on_approval'
  | 'returned'
  | 'rejected'
  | 'to_hr'
  | 'hr_work'
  | 'signing'
  | 'executed'
  | 'closed'
  | 'canceled'

export interface JobDescRouteSlot {
  order: number
  role_code: string
  role_name: string
  role_class: 'approver' | 'signer'
  required: boolean
  // «при наличии»: пустой выбор = этапа нет
  optional: boolean
  // юротдел — согласует любой юрист
  group: boolean
  resolved: boolean
  b24_user_id: number | null
  user_name: string
  needs_manual: boolean
  replaceable: boolean
  // инициатор из отдела персонала — его этап закроется сам при отправке
  auto_by_initiator: boolean
  // выбирать из сотрудников отдела персонала
  hr_pick: boolean
  // роли, которые этот же человек закрывает на этом этапе
  merged_roles: string[]
}

export interface JobDescDocument {
  id: number
  title: string
  document_type?: string
  current_version_number: number | null
  download_url: string | null
  versions: DocumentVersion[]
  can_edit_online: boolean
}

export interface JobDescListItem {
  id: number
  number: string
  position_name: string
  organization: number
  organization_name: string
  cfo: number
  cfo_name: string
  facility: number | null
  facility_name: string | null
  is_nonstandard: boolean
  status: JobDescStatus
  status_display: string
  initiator_b24_id: number | null
  executor_b24_id: number | null
  created_at: string
}

export interface JobDescDetail extends JobDescListItem {
  description: string
  data: Record<string, unknown>
  taken_at: string | null
  executed_at: string | null
  transfer_method: string
  transfer_display: string
  execution_comment: string
  received_at: string | null
  updated_at: string
  approval: ApprovalDetail | null
  documents: JobDescDocument[]
}

export interface JobDescPayload {
  position_name: string
  organization: number | null
  cfo: number | null
  facility?: number | null
  is_nonstandard?: boolean
  description?: string
}

export interface HrStaffOption {
  bitrix_id: number
  fio: string
  position: string
}

export interface JobDescMeta {
  statuses: { code: string; name: string }[]
  transfer_methods: { code: string; name: string }[]
  roles: { code: string; name: string }[]
  organizations: { id: number; name: string }[]
  facilities: { id: number; name: string; organization: number | null }[]
  cfos: { id: number; name: string; organization: number | null; category: string; category_name: string }[]
  is_hr_staff: boolean
}
