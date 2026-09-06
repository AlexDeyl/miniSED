import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi, type AuthProfile } from '@/services/auth'

/**
 * Авторизация MiniSED.
 *
 * Два режима:
 *   1) Вход по email+пароль → токен (хранится в localStorage) → профиль.
 *   2) Битрикс/дев: ?b24_user_id=<id> в URL (сохраняется в localStorage),
 *      либо BX24 внутри портала.
 * Личность для API — b24UserId (из профиля или из режима Битрикс).
 */
export const useAuthStore = defineStore('auth', () => {
  const TOKEN_KEY = 'minised_token'
  const B24_KEY = 'minised_b24_user_id'

  const token = ref<string | null>(null)
  const profile = ref<AuthProfile | null>(null)
  const b24UserId = ref<number | null>(null)
  const ready = ref(false)

  const isAuthenticated = computed(() => !!token.value || !!b24UserId.value)
  const displayName = computed(
    () => profile.value?.fio || (b24UserId.value ? `Пользователь #${b24UserId.value}` : ''),
  )
  // Юрист — по праву legal_manage (раздел «Заявки для юристов», групповой юрэтап).
  const isLawyer = computed(() => !!profile.value?.permissions?.includes('legal_manage'))
  // Сквозной просмотр (администратор): видит все согласования, заявки,
  // договоры и комплименты — но действует только там, где он в маршруте.
  const canViewAll = computed(() => !!profile.value?.permissions?.includes('view_all'))
  // Исполнитель комплиментов — ему виден раздел «Заявки для исполнения».
  const isComplimentExecutor = computed(() => !!profile.value?.is_compliment_executor)
  // ИТ-специалист — ему виден раздел «Работа ИТ» (исполнение заявок на ЭЦП).
  const isItSpecialist = computed(() => !!profile.value?.is_it_specialist)

  function ls(key: string, value?: string | null): string | null {
    try {
      if (value === undefined) return window.localStorage.getItem(key)
      if (value === null) window.localStorage.removeItem(key)
      else window.localStorage.setItem(key, value)
    } catch {
      /* localStorage недоступен */
    }
    return null
  }

  function applyProfile(p: AuthProfile) {
    profile.value = p
    if (p.bitrix_id) {
      b24UserId.value = p.bitrix_id
      ls(B24_KEY, String(p.bitrix_id))
    }
  }

  async function login(email: string, password: string) {
    const res = await authApi.login(email, password)
    token.value = res.token
    ls(TOKEN_KEY, res.token)
    applyProfile(res)
  }

  // вход через Битрикс из iframe (BX24.getAuth → access_token+domain)
  async function bitrixLogin(accessToken: string, domain: string) {
    const res = await authApi.bitrixLogin(accessToken, domain)
    token.value = res.token
    ls(TOKEN_KEY, res.token)
    applyProfile(res)
  }

  // применить токен, полученный OAuth-редиректом (?bitrix_token=...)
  async function applyToken(t: string) {
    token.value = t
    ls(TOKEN_KEY, t)
    applyProfile(await authApi.me())
  }

  async function logout() {
    try {
      if (token.value) await authApi.logout()
    } catch {
      /* игнорируем сетевые ошибки при выходе */
    }
    token.value = null
    profile.value = null
    b24UserId.value = null
    ls(TOKEN_KEY, null)
    ls(B24_KEY, null)
  }

  function initB24FromUrl(): boolean {
    const raw = new URLSearchParams(window.location.search).get('b24_user_id')
    if (raw) {
      const id = parseInt(raw, 10)
      if (!Number.isNaN(id)) {
        b24UserId.value = id
        ls(B24_KEY, String(id))
        return true
      }
    }
    return false
  }

  async function init() {
    // 0) токен, вложенный сервером при открытии из Битрикс24 (window.__MINISED_BOOT__)
    const boot = (window as unknown as { __MINISED_BOOT__?: { token?: string } })
      .__MINISED_BOOT__
    if (boot?.token) {
      try {
        await applyToken(boot.token)
      } catch {
        /* не удалось — упадём в обычный поток ниже */
      }
      try {
        delete (window as unknown as { __MINISED_BOOT__?: unknown }).__MINISED_BOOT__
      } catch {
        /* игнорируем */
      }
    }

    // 1) явное переключение через URL (дев/Битрикс)
    initB24FromUrl()

    // 2) токен из хранилища → подтягиваем профиль
    const savedToken = ls(TOKEN_KEY)
    if (!token.value && savedToken) {
      token.value = savedToken
      try {
        applyProfile(await authApi.me())
      } catch {
        // токен протух — сбрасываем
        token.value = null
        ls(TOKEN_KEY, null)
      }
    }

    // 3) восстановить b24 из хранилища (если ещё не задан)
    if (!b24UserId.value) {
      const saved = ls(B24_KEY)
      if (saved) {
        const id = parseInt(saved, 10)
        if (!Number.isNaN(id)) b24UserId.value = id
      }
    }

    ready.value = true
  }

  return {
    token, profile, b24UserId, ready, isAuthenticated, displayName, isLawyer,
    canViewAll, isComplimentExecutor, isItSpecialist,
    login, bitrixLogin, applyToken, logout, init,
  }
})
