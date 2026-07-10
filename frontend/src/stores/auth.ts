import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * Хранилище текущего пользователя.
 *
 * ВРЕМЕННО: личность = b24_user_id, как в текущем бэкенде.
 * Источники (по приоритету):
 *   1) ?b24_user_id=... в URL (удобно для локальной отладки с домена);
 *   2) BX24.user.current() — когда приложение открыто внутри iframe Битрикс24.
 *
 * Этап 2 (Bitrix Connector) и нормальная авторизация MiniSED заменят это
 * на серверную сессию/токен — правки будут в этом сторе.
 */
export const useAuthStore = defineStore('auth', () => {
  const b24UserId = ref<number | null>(null)
  const ready = ref(false)

  function initFromUrl(): boolean {
    const params = new URLSearchParams(window.location.search)
    const raw = params.get('b24_user_id')
    if (raw) {
      const id = parseInt(raw, 10)
      if (!Number.isNaN(id)) {
        b24UserId.value = id
        return true
      }
    }
    return false
  }

  function initFromBitrix(): Promise<boolean> {
    return new Promise((resolve) => {
      const BX24 = (window as unknown as { BX24?: BitrixSDK }).BX24
      if (!BX24 || !BX24.init) {
        resolve(false)
        return
      }
      BX24.init(() => {
        BX24.callMethod('user.current', {}, (res) => {
          if (res.error()) {
            resolve(false)
            return
          }
          const user = res.data()
          const id = parseInt(String(user.ID), 10)
          if (!Number.isNaN(id)) {
            b24UserId.value = id
            resolve(true)
          } else {
            resolve(false)
          }
        })
      })
    })
  }

  async function init() {
    if (!initFromUrl()) {
      await initFromBitrix()
    }
    ready.value = true
  }

  return { b24UserId, ready, init }
})

// Минимальные типы BX24 SDK (только то, что используем на переходный период).
interface BitrixSDK {
  init(cb: () => void): void
  callMethod(
    method: string,
    params: Record<string, unknown>,
    cb: (res: { error(): unknown; data(): { ID: string | number } }) => void,
  ): void
}
