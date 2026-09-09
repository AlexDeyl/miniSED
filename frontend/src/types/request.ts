import type { ApprovalDetail } from './approval'
import type { DocumentVersion } from './document'

export type RequestType = 'poa' | 'mchd' | 'ecp' | 'revoke'
export type RequestStatus =
  | 'draft'
  | 'on_approval'
  | 'returned'
  | 'rejected'
  | 'approved'
  | 'to_legal'
  | 'legal_work'
  | 'signing'
  // Исполнение заявки на ЭЦП: её ведёт не юротдел, а ИТ-специалист объекта.
  | 'to_it'
  | 'it_work'
  | 'executed'
  | 'closed'
  | 'canceled'

export interface RouteSlot {
  order: number
  role_code: string
  role_name: string
  required: boolean
  // групповой этап (юротдел): согласует любой юрист, персонально не назначаем
  // и заменять некого
  group: boolean
  // можно ли поставить вместо подобранного матрицей другого сотрудника
  replaceable: boolean
  resolved: boolean
  b24_user_id: number | null
  user_name: string
  needs_manual: boolean
}

// Короткая ссылка на карточку заявки: связка отзыв ↔ отзываемая доверенность.
export interface RequestCardRef {
  id: number
  number: string
  request_type: RequestType
  type_display: string
  status: RequestStatus
  status_display: string
  subject_name: string
}

export interface RequestDocument {
  id: number
  title: string
  document_type?: string
  current_version_number: number | null
  // download_url — актуальная версия; полная история версий — в versions.
  download_url: string | null
  versions: DocumentVersion[]
  can_edit_online: boolean
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
  // Отзываемая доверенность (в заявке на отзыв) и, наоборот, заявки на отзыв
  // этой доверенности (в карточке самой доверенности).
  source_request: number | null
  source_request_info: RequestCardRef | null
  revocations: RequestCardRef[]
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
  comment?: string
  // Заявка на отзыв: карточка отзываемой доверенности, если она есть в системе.
  source_request?: number | null
  data?: Record<string, unknown>
}
