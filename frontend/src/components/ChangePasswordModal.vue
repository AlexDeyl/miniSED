<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/services/api'

// Смена пароля из сайдбара. Кто входил только через Битрикс, пароля ещё не
// имеет — ему текущий не спрашиваем, он задаёт пароль впервые.
const emit = defineEmits<{ close: [] }>()
const auth = useAuthStore()

const hasPassword = computed(() => !!auth.profile?.has_password)
const oldPassword = ref('')
const password = ref('')
const password2 = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const done = ref(false)

async function submit() {
  error.value = null
  if (password.value !== password2.value) {
    error.value = 'Пароли не совпадают.'
    return
  }
  busy.value = true
  try {
    await auth.changePassword(oldPassword.value, password.value, password2.value)
    done.value = true
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить пароль'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="cpm-overlay" @click.self="emit('close')">
    <div class="cpm">
      <div class="cpm-head">
        <strong>{{ hasPassword ? 'Смена пароля' : 'Задать пароль' }}</strong>
        <button type="button" class="cpm-x" @click="emit('close')">×</button>
      </div>

      <div v-if="done" class="cpm-body">
        <p class="cpm-ok">Пароль сохранён.</p>
        <p class="muted cpm-note">
          Теперь можно войти по почте <strong>{{ auth.profile?.email }}</strong> и этому паролю —
          например, если Битрикс24 недоступен.
        </p>
        <button class="btn btn--primary" type="button" style="width:100%" @click="emit('close')">Готово</button>
      </div>

      <form v-else class="cpm-body" @submit.prevent="submit">
        <p v-if="!hasPassword" class="muted cpm-note">
          Пароль нужен для входа по почте <strong>{{ auth.profile?.email }}</strong>,
          если Битрикс24 будет недоступен.
        </p>
        <label v-if="hasPassword" class="form-field">
          <span>Текущий пароль</span>
          <input v-model="oldPassword" type="password" autocomplete="current-password" required />
        </label>
        <label class="form-field">
          <span>Новый пароль</span>
          <input v-model="password" type="password" autocomplete="new-password" required />
        </label>
        <label class="form-field">
          <span>Повторите пароль</span>
          <input v-model="password2" type="password" autocomplete="new-password" required />
        </label>
        <p class="muted cpm-hint">Не короче 8 символов, не только цифры и не слишком простой.</p>

        <p v-if="error" class="state state--error">{{ error }}</p>

        <button class="btn btn--primary" type="submit" :disabled="busy" style="width:100%">
          {{ busy ? 'Сохранение…' : 'Сохранить' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.cpm-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh; z-index: 100; }
.cpm { width: 380px; max-width: 94vw; background: #fff; color: var(--text-main); border-radius: 12px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25); overflow: hidden; }
.cpm-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--gray-border); }
.cpm-x { border: none; background: transparent; font-size: 20px; line-height: 1; cursor: pointer; color: var(--text-muted); }
.cpm-body { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.cpm-note { font-size: 13px; margin: 0; }
.cpm-hint { font-size: 12px; margin: -4px 0 0; }
.cpm-ok { font-weight: 600; color: var(--green-main); margin: 0; }
</style>
