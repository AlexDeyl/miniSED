import { api } from './api'
import type { DocumentItem, EditorConfigResponse } from '@/types/document'

const BASE = '/documents'

export const documents = {
  get: (id: number | string) => api.get<DocumentItem>(`${BASE}/${id}/`),

  // Конфиг онлайн-редактора. 409, если фича выключена или формат не поддержан —
  // на этот случай на карточке скрываем кнопку по флагу can_edit_online.
  editorConfig: (id: number | string) =>
    api.get<EditorConfigResponse>(`${BASE}/${id}/editor-config/`),

  addVersion: (id: number | string, file: File, changeComment = '') => {
    const form = new FormData()
    form.append('file', file)
    if (changeComment) form.append('change_comment', changeComment)
    return api.postForm<DocumentItem>(`${BASE}/${id}/versions/`, form)
  },
}
