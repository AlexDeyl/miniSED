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
}
