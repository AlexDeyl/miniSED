<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/services/api'

// Страница из письма «Забыли пароль?»: новый пароль + подтверждение.
// Сервер проверяет ссылку при сохранении и сразу впускает в приложение.
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const password = ref('')
const password2 = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

async function submit() {
  error.value = null
  if (password.value !== password2.value) {
    error.value = 'Пароли не совпадают.'
    return
  }
  busy.value = true
  try {
    await auth.confirmReset(
      String(route.params.uid), String(route.params.token), password.value, password2.value,
    )
    router.replace('/svetofor')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить пароль'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="login-card">
      <div class="login-logo">МиниСЭД 2.0</div>
      <p class="login-sub">Задайте новый пароль для входа по почте</p>

      <form @submit.prevent="submit">
        <label class="form-field">
          <span>Новый пароль</span>
          <input v-model="password" type="password" autocomplete="new-password" required />
        </label>
        <label class="form-field" style="margin-top:12px">
          <span>Повторите пароль</span>
          <input v-model="password2" type="password" autocomplete="new-password" required />
        </label>
        <p class="hint">Не короче 8 символов, не только цифры и не слишком простой.</p>

        <p v-if="error" class="state state--error">{{ error }}</p>

        <button class="btn btn--primary" type="submit" :disabled="busy" style="width:100%;margin-top:12px">
          {{ busy ? 'Сохранение…' : 'Сохранить и войти' }}
        </button>
      </form>

      <RouterLink to="/login" class="back">← Ко входу</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.login { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: var(--gray-bg); padding: 20px; }
.login-card { background: #fff; border: 1px solid var(--gray-border); border-radius: 12px; box-shadow: var(--shadow-soft); padding: 28px; width: 100%; max-width: 360px; }
.login-logo { font-size: 24px; font-weight: 700; color: var(--green-main); }
.login-sub { color: var(--text-muted); font-size: 13px; margin: 4px 0 20px; }
.hint { color: var(--text-muted); font-size: 12px; margin: 8px 0 0; }
.back { display: inline-block; margin-top: 16px; font-size: 13px; }
</style>
