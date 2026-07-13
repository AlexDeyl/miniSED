<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { RegulatoryRequestDetail, RouteSlot } from '@/types/request'
import type { ApprovalParticipant, ParticipantInput } from '@/types/approval'

const props = defineProps<{ id: string }>()
const auth = useAuthStore()

const DELIVERY = [
  { code: 'personally', name: 'Лично' },
  { code: 'courier', name: 'Курьером' },
  { code: 'post', name: 'Почтой' },
  { code: 'edo', name: 'ЭДО / электронно' },
  { code: 'other', name: 'Другое' },
]
const LEGAL_STATUSES = ['to_legal', 'legal_work', 'signing']

const req = ref<RegulatoryRequestDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

// маршрут для отправки (слоты + ручной ввод)
const route = ref<(RouteSlot & { manual: string })[]>([])
// исполнение
const deliveryMethod = ref('personally')
const deliveryComment = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    req.value = await requests.get(props.id)
    if (canSubmit.value) await loadRoute()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

async function loadRoute() {
  const { route: slots } = await requests.routePreview(props.id)
  route.value = slots.map((s) => ({ ...s, manual: '' }))
}

const isInitiator = computed(() => req.value?.initiator_b24_id === auth.b24UserId)
const canSubmit = computed(
  () => isInitiator.value && (req.value?.status === 'draft' || req.value?.status === 'returned'),
)
const isLegalStage = computed(() => req.value && LEGAL_STATUSES.includes(req.value.status))

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
  const participants: ParticipantInput[] = []
  for (const [i, s] of route.value.entries()) {
    const uid = s.resolved ? s.b24_user_id! : parseInt(s.manual, 10)
    if (Number.isNaN(uid)) {
      error.value = `Укажите согласующего для роли «${s.role_name}»`
      return
    }
    participants.push({ type: 'internal', b24_user_id: uid, role: s.role_code, order: i })
  }
  run(async () => {
    const r = await requests.submit(props.id, participants)
    route.value = []
    return r
  })
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
  run(() => requests.decide(props.id, p.id, decision, comment))
}

async function uploadFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  error.value = null
  try {
    await requests.uploadDocument(props.id, file, file.name)
    req.value = await requests.get(props.id)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Не удалось загрузить файл'
  } finally {
    busy.value = false
    input.value = ''
  }
}
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

      <!-- Предпросмотр маршрута + отправка -->
      <div v-if="canSubmit" class="detail-card">
        <div class="detail-card-header">Маршрут согласования (последовательный)</div>
        <table class="round-table">
          <tbody>
            <tr v-for="s in route" :key="s.order">
              <td>{{ s.order + 1 }}. {{ s.role_name }}</td>
              <td>
                <template v-if="s.resolved">
                  USER #{{ s.b24_user_id }} <em v-if="s.user_name">({{ s.user_name }})</em>
                </template>
                <input v-else v-model="s.manual" type="number" placeholder="ID Б24 — выбрать вручную"
                       style="padding:5px 8px;border:1px solid var(--gray-border);border-radius:6px" />
              </td>
              <td>
                <span v-if="s.needs_manual" class="participant-pill" style="background:#ffe0b2">ручной выбор</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div style="margin-top:10px">
          <button class="btn btn--primary" :disabled="busy" @click="submit">Отправить на согласование</button>
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
              <td>{{ p.role || '—' }}</td>
              <td>USER #{{ p.b24_user_id }}</td>
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

      <!-- Документы -->
      <div class="detail-card">
        <div class="detail-card-header">Документы</div>
        <ul v-if="req.documents.length" class="item-tags" style="flex-direction:column;align-items:flex-start;gap:6px;margin-bottom:8px">
          <li v-for="d in req.documents" :key="d.id">
            <a v-if="d.download_url" :href="d.download_url" target="_blank" rel="noopener">
              {{ d.title }} (в{{ d.current_version_number }})
            </a>
          </li>
        </ul>
        <p v-else class="muted" style="margin:0 0 8px">Файлов пока нет.</p>
        <template v-if="isLegalStage">
          <input ref="fileInput" type="file" style="display:none" @change="uploadFile" />
          <button class="btn btn--ghost" :disabled="busy" @click="fileInput?.click()">Прикрепить файл</button>
        </template>
      </div>

      <!-- Раздел юристов: исполнение -->
      <div v-if="isLegalStage" class="detail-card">
        <div class="detail-card-header">Исполнение (юридический отдел)</div>
        <div class="row-actions" style="margin-bottom:10px">
          <button v-if="req.status === 'to_legal'" class="btn btn--primary" :disabled="busy" @click="run(() => requests.take(req!.id))">Взять в работу</button>
          <button v-if="req.status === 'legal_work'" class="btn" :disabled="busy" @click="run(() => requests.toSigning(req!.id))">На подписание</button>
        </div>
        <div v-if="req.status === 'legal_work' || req.status === 'signing'" class="form-row" style="align-items:flex-end">
          <label class="form-field" style="max-width:220px">
            <span>Способ передачи</span>
            <select v-model="deliveryMethod">
              <option v-for="d in DELIVERY" :key="d.code" :value="d.code">{{ d.name }}</option>
            </select>
          </label>
          <label class="form-field">
            <span>Комментарий к передаче</span>
            <input v-model="deliveryComment" type="text" />
          </label>
          <button class="btn btn--primary" :disabled="busy" @click="run(() => requests.execute(req!.id, deliveryMethod, deliveryComment))">
            Исполнена
          </button>
        </div>
        <p class="muted" style="margin:8px 0 0;font-size:12px">Для исполнения нужен прикреплённый файл доверенности и способ передачи.</p>
      </div>

      <!-- Исполнена: подтверждение получения инициатором -->
      <div v-if="req.status === 'executed'" class="detail-card">
        <div class="detail-card-header">Исполнена</div>
        <p class="muted" style="margin:0 0 10px">
          Способ передачи: {{ req.delivery_method_display }}<template v-if="req.delivery_comment"> — {{ req.delivery_comment }}</template>
        </p>
        <button v-if="isInitiator" class="btn btn--primary" :disabled="busy" @click="run(() => requests.confirmReceipt(req!.id))">
          Получил / ознакомился
        </button>
      </div>
    </template>
  </section>
</template>
