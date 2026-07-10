import { useAuthStore } from '@/stores/auth'

/**
 * Тонкая обёртка над fetch для общения с Django API.
 *
 * Пока сохраняем текущий контракт бэкенда: личность пользователя
 * передаётся заголовком X-B24-User (см. get_current_b24_id во views.py).
 * На следующих этапах это заменится на нормальную сессию/токен MiniSED —
 * тогда правки будут только здесь, в одном месте.
 */

const BASE = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  // multipart-форма (файлы) вместо JSON
  form?: FormData
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const auth = useAuthStore()
  const headers: Record<string, string> = {}

  if (auth.b24UserId) {
    headers['X-B24-User'] = String(auth.b24UserId)
  }

  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  const resp = await fetch(`${BASE}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body,
  })

  const raw = await resp.text()
  let data: unknown = null
  if (raw) {
    try {
      data = JSON.parse(raw)
    } catch {
      data = raw
    }
  }

  if (!resp.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : 'Ошибка запроса'
    throw new ApiError(detail, resp.status)
  }

  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', form }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
