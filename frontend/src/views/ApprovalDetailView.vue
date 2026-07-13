<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { approvalflow } from '@/services/approvalflow'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import {
  type ApprovalDetail,
  type ApprovalParticipant,
  APPROVAL_STATUS_CLASS,
} from '@/types/approval'

const props = defineProps<{ id: string }>()
const auth = useAuthStore()

const approval = ref<ApprovalDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    approval.value = await approvalflow.get(props.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

const currentRound = computed(() => {
  if (!approval.value) return null
  return (
    approval.value.rounds.find(
      (r) => r.round_number === approval.value!.current_round,
    ) ?? null
  )
})

function canDecide(p: ApprovalParticipant): boolean {
  return (
    approval.value?.status === 'in_progress' &&
    p.decision === 'waiting' &&
    p.type === 'internal' &&
    p.b24_user_id === auth.b24UserId
  )
}

async function run(fn: () => Promise<ApprovalDetail>) {
  busy.value = true
  error.value = null
  try {
    approval.value = await fn()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject') {
  let comment = ''
  if (decision === 'reject') {
    comment = window.prompt('Комментарий (обязателен при отклонении):') || ''
    if (!comment.trim()) return
  }
  run(() => approvalflow.decide(approval.value!.id, p.id, decision, comment))
}

async function generateSheet() {
  busy.value = true
  error.value = null
  try {
    await approvalflow.generateSheet(approval.value!.id)
    approval.value = await approvalflow.get(props.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сформировать лист'
  } finally {
    busy.value = false
  }
}

const isInitiator = computed(
  () => approval.value?.initiator_b24_id === auth.b24UserId,
)

onMounted(load)
</script>

<template>
  <section class="flow">
    <RouterLink to="/flow" class="flow__back">← К списку</RouterLink>

    <p v-if="loading" class="flow__state">Загрузка…</p>
    <p v-else-if="error && !approval" class="flow__state--error">{{ error }}</p>

    <template v-else-if="approval">
      <header class="detail__head">
        <h1>#{{ approval.id }} {{ approval.title || '(без названия)' }}</h1>
        <span class="badge" :data-status="APPROVAL_STATUS_CLASS[approval.status]">
          {{ approval.status_display }}
        </span>
      </header>
      <p class="muted">
        {{ approval.approval_type }} ·
        {{ approval.flow_type === 'parallel' ? 'параллельное' : 'последовательное' }}
        · инициатор #{{ approval.initiator_b24_id }}
      </p>

      <p v-if="error" class="flow__state--error">{{ error }}</p>

      <!-- Круги -->
      <div v-for="rnd in approval.rounds" :key="rnd.id" class="round">
        <h3 class="round__title">
          Круг {{ rnd.round_number }}
          <span class="badge" :data-round="rnd.result">{{ rnd.result }}</span>
        </h3>
        <table class="round__table">
          <thead>
            <tr><th>Согласующий</th><th>Роль</th><th>Решение</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="p in rnd.participants" :key="p.id">
              <td>{{ p.type === 'internal' ? `USER #${p.b24_user_id}` : p.email }}</td>
              <td>{{ p.role || '—' }}</td>
              <td>
                <span class="badge" :data-pstatus="p.decision">{{ p.decision }}</span>
                <em v-if="p.decision_comment"> — {{ p.decision_comment }}</em>
              </td>
              <td class="round__actions">
                <template v-if="canDecide(p)">
                  <button class="btn btn--ok" :disabled="busy" @click="decide(p, 'approve')">✓</button>
                  <button class="btn btn--no" :disabled="busy" @click="decide(p, 'reject')">✕</button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="rnd.comment" class="muted">Комментарий круга: {{ rnd.comment }}</p>
      </div>

      <!-- Лист согласования -->
      <div class="sheet">
        <h3 class="round__title">Лист согласования</h3>
        <ul v-if="approval.sheets.length" class="sheet__list">
          <li v-for="s in approval.sheets" :key="s.id">
            <a :href="s.file_url" target="_blank" rel="noopener">
              Лист от {{ new Date(s.generated_at).toLocaleString('ru') }} (PDF)
            </a>
          </li>
        </ul>
        <button
          v-if="isInitiator"
          class="btn btn--ghost"
          :disabled="busy"
          @click="generateSheet"
        >
          Сформировать лист (PDF)
        </button>
      </div>
    </template>
  </section>
</template>
