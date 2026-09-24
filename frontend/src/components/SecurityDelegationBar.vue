<script setup lang="ts">
// Передача функций службы безопасности юристам (ТЗ, примечание к исполнению
// проверки лица): пока СБ нет на месте, юрист одной кнопкой открывает себе и
// коллегам раздел «Работа службы безопасности», потом возвращает. Кто и когда
// переключал — в журнале на сервере, кто исполнил заявку — в её карточке.
import { onMounted, ref } from 'vue'
import { requests, type SecurityDelegation } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { fmtDateTime } from '@/composables/useApprovalCard'

const auth = useAuthStore()
const state = ref<SecurityDelegation | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)

async function load() {
  try { state.value = await requests.securityDelegation() } catch { state.value = null }
}

async function toggle(active: boolean) {
  const comment = active
    ? window.prompt('Причина передачи (отпуск, больничный…), необязательно:') ?? null
    : ''
  if (comment === null) return
  if (!active && !confirm('Вернуть функции службе безопасности? Раздел СБ закроется для юристов.')) return
  busy.value = true
  error.value = null
  try {
    state.value = await requests.setSecurityDelegation(active, comment)
    await auth.refreshProfile() // сайдбар: появится/исчезнет раздел СБ
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось переключить'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="state" class="deleg" :class="{ on: state.active }">
    <div class="deleg-text">
      <template v-if="state.active">
        <b>Функции службы безопасности переданы юридическому отделу</b>
        <span>
          с {{ fmtDateTime(state.started_at) }}<template v-if="state.comment"> · {{ state.comment }}</template>
          — юристы работают в разделе «Работа службы безопасности».
        </span>
      </template>
      <template v-else>
        <b>Служба безопасности на месте</b>
        <span>Если СБ отсутствует (отпуск, больничный), юрист может принять её функции.</span>
      </template>
    </div>
    <button
      v-if="!state.active && auth.isLawyer" class="btn btn--soft" :disabled="busy"
      @click="toggle(true)"
    >Принять функции СБ</button>
    <button
      v-if="state.active && (auth.isLawyer || state.can_work)" class="btn btn--ghost" :disabled="busy"
      @click="toggle(false)"
    >Вернуть функции СБ</button>
  </div>
  <p v-if="error" class="state state--error">{{ error }}</p>
</template>

<style scoped>
.deleg {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  margin-bottom: 12px; padding: 9px 12px; border: 1px solid var(--gray-border);
  border-radius: 8px; background: #fff;
}
.deleg.on { border-color: var(--orange-main); background: #fff8e1; }
.deleg-text { font-size: 13px; }
.deleg-text b { display: block; font-size: 13.5px; }
.deleg-text span { color: var(--text-muted); font-size: 12.5px; }
</style>
