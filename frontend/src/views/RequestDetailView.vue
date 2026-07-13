<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { RegulatoryRequestDetail } from '@/types/request'
import type { ApprovalParticipant } from '@/types/approval'

const props = defineProps<{ id: string }>()
const auth = useAuthStore()

const req = ref<RegulatoryRequestDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

// строки маршрута для отправки на согласование
const rows = ref<{ b24_user_id: string; role: string }[]>([{ b24_user_id: '', role: '' }])

async function load() {
  loading.value = true
  error.value = null
  try {
    req.value = await requests.get(props.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

const isInitiator = computed(() => req.value?.initiator_b24_id === auth.b24UserId)
const canSubmit = computed(
  () => isInitiator.value && (req.value?.status === 'draft' || req.value?.status === 'returned'),
)

async function run(fn: () => Promise<RegulatoryRequestDetail>) {
  busy.value = true
  error.value = null
  try {
    req.value = await fn()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

function submit() {
  const participants = rows.value
    .map((r, i) => ({ type: 'internal' as const, b24_user_id: parseInt(r.b24_user_id, 10), role: r.role.trim(), order: i }))
    .filter((p) => !Number.isNaN(p.b24_user_id))
  if (participants.length === 0) {
    error.value = 'Добавьте согласующих (ID Б24)'
    return
  }
  run(() => requests.submit(req.value!.id, participants))
}

function canDecide(p: ApprovalParticipant): boolean {
  return (
    req.value?.status === 'on_approval' &&
    p.decision === 'waiting' &&
    p.type === 'internal' &&
    p.b24_user_id === auth.b24UserId
  )
}

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject') {
  let comment = ''
  if (decision === 'reject') {
    comment = window.prompt('Комментарий (обязателен при отклонении):') || ''
    if (!comment.trim()) return
  }
  run(() => requests.decide(req.value!.id, p.id, decision, comment))
}

onMounted(load)
</script>

<template>
  <section>
    <RouterLink to="/requests" class="back-link">← К заявкам</RouterLink>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error && !req" class="state state--error">{{ error }}</p>

    <template v-else-if="req">
      <div class="detail-header-main">
        <div>
          <h1 class="detail-title">{{ req.number }} · {{ req.type_display }}</h1>
          <div class="detail-meta">
            {{ req.subject_name || '—' }} · {{ req.organization_name }} · инициатор #{{ req.initiator_b24_id }}
          </div>
        </div>
        <span class="status-pill" :class="req.status">{{ req.status_display }}</span>
      </div>

      <p v-if="error" class="state state--error">{{ error }}</p>

      <!-- Основные поля -->
      <div class="detail-card">
        <div class="detail-card-header">Данные заявки</div>
        <div class="item-tags">
          <span v-if="req.position" class="tag-chip">Должность: {{ req.position }}</span>
          <span v-if="req.department" class="tag-chip">Подразделение: {{ req.department }}</span>
          <span v-if="req.basis" class="tag-chip">Основание: {{ req.basis }}</span>
        </div>
      </div>

      <!-- Отправка на согласование -->
      <div v-if="canSubmit" class="detail-card">
        <div class="detail-card-header">Отправить на согласование</div>
        <div v-for="(row, i) in rows" :key="i" class="form-participant">
          <input v-model="row.b24_user_id" type="number" placeholder="ID Б24" />
          <input v-model="row.role" type="text" placeholder="роль (опц.)" />
          <button type="button" class="btn btn--ghost" :disabled="rows.length === 1" @click="rows.splice(i, 1)">✕</button>
        </div>
        <button type="button" class="btn btn--ghost" @click="rows.push({ b24_user_id: '', role: '' })">+ участник</button>
        <div style="margin-top:10px">
          <button class="btn btn--primary" :disabled="busy" @click="submit">Отправить</button>
        </div>
      </div>

      <!-- Круги согласования -->
      <div v-for="rnd in req.approval?.rounds || []" :key="rnd.id" class="detail-card">
        <div class="detail-card-header">
          Круг {{ rnd.round_number }}
          <span class="participant-pill" :class="rnd.result">{{ rnd.result }}</span>
        </div>
        <table class="round-table">
          <tbody>
            <tr v-for="p in rnd.participants" :key="p.id">
              <td>{{ p.type === 'internal' ? `USER #${p.b24_user_id}` : p.email }}</td>
              <td>{{ p.role || '—' }}</td>
              <td>
                <span class="participant-pill" :class="p.decision">{{ p.decision }}</span>
                <em v-if="p.decision_comment"> — {{ p.decision_comment }}</em>
              </td>
              <td class="row-actions">
                <template v-if="canDecide(p)">
                  <button class="btn btn--ok" :disabled="busy" @click="decide(p, 'approve')">✓</button>
                  <button class="btn btn--no" :disabled="busy" @click="decide(p, 'reject')">✕</button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Жизненный цикл выпуска -->
      <div v-if="isInitiator" class="detail-card">
        <div class="detail-card-header">Выпуск</div>
        <div class="row-actions">
          <button v-if="req.status === 'approved'" class="btn" :disabled="busy" @click="run(() => requests.inWork(req!.id))">В работу</button>
          <button v-if="req.status === 'approved' || req.status === 'in_work'" class="btn btn--primary" :disabled="busy" @click="run(() => requests.issue(req!.id))">Выпущена / оформлена</button>
          <button v-if="req.status !== 'closed'" class="btn btn--ghost" :disabled="busy" @click="run(() => requests.close(req!.id))">Закрыть</button>
        </div>
      </div>
    </template>
  </section>
</template>
