<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/services/api'
import { bitrix } from '@/services/bitrix'

const router = useRouter()
const auth = useAuthStore()

// Куда вести после входа: ?next из guard-а (ссылка из уведомления на карточку)
// либо главная. Иначе deep link терялся на экране входа.
function afterLogin(): string {
  const next = router.currentRoute.value.query.next
  const raw = typeof next === 'string' ? next : ''
  return raw.startsWith('/') && !raw.startsWith('//') ? raw : '/svetofor'
}

const email = ref('')
const password = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

interface BX24Auth {
  access_token?: string
  refresh_token?: string
  domain?: string
  member_id?: string
  expires_in?: number
}
interface BX24SDK {
  init(cb: () => void): void
  getAuth(): BX24Auth | false
}
function bx24(): BX24SDK | undefined {
  return (window as unknown as { BX24?: BX24SDK }).BX24
}

async function submit() {
  error.value = null
  busy.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    router.push(afterLogin())
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось войти'
  } finally {
    busy.value = false
  }
}

// OAuth-редирект: Битрикс вернёт код на обработчик /app (там выпустится токен).
function oauthRedirect() {
  // next тащим с собой через OAuth: после возврата попадём в нужную карточку.
  const back = new URL(window.location.origin + '/login')
  const target = afterLogin()
  if (target !== '/svetofor') back.searchParams.set('next', target)
  window.location.href = `/api/auth/bitrix/start/?next=${encodeURIComponent(back.toString())}`
}

// Вход через Битрикс24: внутри портала — BX24.getAuth(); иначе — OAuth-редирект.
function loginViaBitrix() {
  error.value = null
  const BX24 = bx24()
  if (BX24 && BX24.init) {
    busy.value = true
    BX24.init(async () => {
      try {
        const a = BX24.getAuth()
        if (a && a.access_token && a.domain) {
          // 1) вход в МиниСЭД (тот же аккаунт по bitrix_id/почте)
          await auth.bitrixLogin(a.access_token, a.domain)
          // 2) сохраняем токены портала для серверного Connector (поиск сделок и т.п.)
          try {
            await bitrix.storeAuth({
              domain: a.domain,
              member_id: a.member_id,
              access_token: a.access_token,
              refresh_token: a.refresh_token,
              expires_in: a.expires_in,
            })
          } catch {
            /* не критично для входа */
          }
          router.push(afterLogin())
        } else {
          // SDK есть, но контекст портала недоступен — уходим на OAuth
          oauthRedirect()
        }
      } catch {
        oauthRedirect()
      }
    })
    return
  }
  oauthRedirect()
}

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const t = params.get('bitrix_token')
  if (t) {
    busy.value = true
    try {
      await auth.applyToken(t)
      // чистим URL от токена
      window.history.replaceState({}, '', window.location.pathname)
      router.push(afterLogin())
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : 'Не удалось войти через Битрикс24'
    } finally {
      busy.value = false
    }
  } else if (params.get('bitrix_error')) {
    error.value = 'Вход через Битрикс24 не удался. Попробуйте ещё раз.'
  } else if (bx24()) {
    // Открыто из портала Битрикс24 (в iframe есть BX24 SDK) — входим автоматически.
    loginViaBitrix()
  }
})
</script>

<template>
  <div class="login">
    <div class="login-card">
      <div class="login-logo">Минин-СЭД 2.0</div>
      <p class="login-sub">Электронный документооборот</p>

      <form @submit.prevent="submit">
        <label class="form-field">
          <span>Email</span>
          <input v-model="email" type="email" autocomplete="username" placeholder="ivanov@nord.ru" />
        </label>
        <label class="form-field" style="margin-top:12px">
          <span>Пароль</span>
          <input v-model="password" type="password" autocomplete="current-password" />
        </label>

        <p v-if="error" class="state state--error" style="margin-top:12px">{{ error }}</p>

        <button class="btn btn--primary" type="submit" :disabled="busy" style="width:100%;margin-top:16px">
          {{ busy ? 'Вход…' : 'Войти' }}
        </button>
      </form>

      <div class="login-or"><span>или</span></div>

      <button class="btn login-bitrix" type="button" :disabled="busy" @click="loginViaBitrix">
        Войти через Битрикс24
      </button>
    </div>
  </div>
</template>

<style scoped>
.login { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: var(--gray-bg); padding: 20px; }
.login-card { background: #fff; border: 1px solid var(--gray-border); border-radius: 12px; box-shadow: var(--shadow-soft); padding: 28px; width: 100%; max-width: 360px; }
.login-logo { font-size: 24px; font-weight: 700; color: var(--green-main); }
.login-sub { color: var(--text-muted); font-size: 13px; margin: 4px 0 20px; }
.login-or { display: flex; align-items: center; gap: 10px; margin: 16px 0; color: var(--text-muted); font-size: 12px; }
.login-or::before, .login-or::after { content: ''; flex: 1; height: 1px; background: var(--gray-border); }
.login-bitrix { width: 100%; background: #2f6fd6; color: #fff; border-color: #2f6fd6; }
.login-bitrix:hover { background: #2860bd; }
</style>
