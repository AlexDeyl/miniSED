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
  const headers: Record<string, string> = {
    // Пропуск заставки ngrok-free (ERR_NGROK_6024): без него ngrok отдаёт
    // HTML-заглушку вместо JSON на fetch-запросы → JSON.parse падает.
    // На реальном домене заголовок просто игнорируется.
    'ngrok-skip-browser-warning': 'true',
  }

  // Токен MiniSED (вход по email+пароль)
  if (auth.token) {
    headers['Authorization'] = `Token ${auth.token}`
  }
  // Режим Битрикс/дев: личность по X-B24-User
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
  let parseFailed = false
  if (raw) {
    try {
      data = JSON.parse(raw)
    } catch {
      data = raw
      parseFailed = true
    }
  }

  // Успешный ответ, но тело — не JSON (например HTML-заглушка прокси/ngrok).
  // Раньше строка возвращалась как есть и v-for шёл по её символам → «пустые
  // карточки». Лучше явная ошибка, чем молчаливо битые данные.
  if (resp.ok && parseFailed) {
    throw new ApiError('Некорректный ответ сервера (ожидался JSON).', resp.status)
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

// Скачивание файла с заголовками авторизации (обычный <a href> их не шлёт).
// path — полный путь от корня (например «/api/reg/requests/1/anketa_pdf/»).
async function download(path: string, filename?: string): Promise<void> {
  const auth = useAuthStore()
  const headers: Record<string, string> = { 'ngrok-skip-browser-warning': 'true' }
  if (auth.token) headers['Authorization'] = `Token ${auth.token}`
  if (auth.b24UserId) headers['X-B24-User'] = String(auth.b24UserId)

  const resp = await fetch(path, { headers })
  if (!resp.ok) throw new ApiError('Не удалось скачать файл', resp.status)
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'file'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  download,
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', form }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
