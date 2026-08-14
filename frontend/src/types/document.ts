// Документы и онлайн-редактирование (ТЗ п.7.1-7.3).

export interface DocumentVersion {
  id: number
  version_number: number
  original_filename: string
  uploaded_by_b24_id: number | null
  uploaded_at: string
  change_comment: string
  is_current: boolean
  file_size: number | null
  mime_type: string
  checksum: string
  download_url: string
}

export interface DocumentItem {
  id: number
  title: string
  document_type: string
  is_confidential: boolean
  created_by_b24_id: number | null
  created_at: string
  deleted_at: string | null
  current_version: number | null
  current_version_number: number | null
  versions: DocumentVersion[]
  // Показывать ли кнопку «Редактировать онлайн» (фича включена + подходящий формат).
  can_edit_online: boolean
}

// Ответ /editor-config/ — всё, что нужно фронту, чтобы смонтировать DocsAPI.
// Провайдер-агностично: serverUrl указывает на OnlyOffice либо Р7-Офис.
export interface EditorConfigResponse {
  serverUrl: string
  provider: string
  session_id: number
  // Конфиг для DocsAPI.DocEditor (структура задаётся сервером документов).
  config: Record<string, unknown>
}
