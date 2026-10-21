import { api } from './api'

export interface AuthProfile {
  authenticated: boolean
  id?: number
  fio?: string
  email?: string
  bitrix_id?: number | null
  is_active?: boolean
  roles?: string[]
  permissions?: string[]
  organizations?: number[]
  // Исполнитель комплиментов — ему показываем раздел «Заявки для исполнения».
  is_compliment_executor?: boolean
  /** Исполнитель заявок на ЭЦП — виден раздел «Работа ИТ». */
  is_it_specialist?: boolean
  /** Служба безопасности (или юрист на время передачи её функций) —
   *  виден раздел «Работа службы безопасности». */
  is_security?: boolean
  /** Отдел по работе с персоналом — виден раздел «Заявки для отдела по работе с персоналом». */
  is_hr_staff?: boolean
  /** Задан ли пароль для входа по почте (на случай недоступности Битрикса). */
  has_password?: boolean
}

export interface LoginResult extends AuthProfile {
  token: string
}

export const authApi = {
  login: (email: string, password: string) =>
    api.post<LoginResult>('/auth/login/', { email, password }),
  bitrixLogin: (accessToken: string, domain: string) =>
    api.post<LoginResult>('/auth/bitrix/', { access_token: accessToken, domain }),
  me: () => api.get<AuthProfile>('/auth/me/'),
  logout: () => api.post<void>('/auth/logout/'),
  changePassword: (oldPassword: string, newPassword: string, newPassword2: string) =>
    api.post<{ detail: string; has_password: boolean }>('/auth/password/change/', {
      old_password: oldPassword, new_password: newPassword, new_password2: newPassword2,
    }),
  requestReset: (email: string) =>
    api.post<{ detail: string }>('/auth/password/reset/', { email }),
  confirmReset: (uid: string, token: string, newPassword: string, newPassword2: string) =>
    api.post<LoginResult>('/auth/password/reset/confirm/', {
      uid, token, new_password: newPassword, new_password2: newPassword2,
    }),
}
