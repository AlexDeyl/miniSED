<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/services/api'

const router = useRouter()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

async function submit() {
  error.value = null
  busy.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    router.push('/tasks')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось войти'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="login-card">
      <div class="login-logo">МиниСЭД 2.0</div>
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
    </div>
  </div>
</template>

<style scoped>
.login { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: var(--gray-bg); padding: 20px; }
.login-card { background: #fff; border: 1px solid var(--gray-border); border-radius: 12px; box-shadow: var(--shadow-soft); padding: 28px; width: 100%; max-width: 360px; }
.login-logo { font-size: 24px; font-weight: 700; color: var(--green-main); }
.login-sub { color: var(--text-muted); font-size: 13px; margin: 4px 0 20px; }
</style>
