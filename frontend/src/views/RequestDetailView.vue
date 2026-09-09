<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { bitrix } from '@/services/bitrix'
import { requests, type UserOption } from '@/services/requests'
import { documents as documentsApi } from '@/services/documents'
import { api, ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { RegulatoryRequestDetail, RouteSlot } from '@/types/request'
import type { ApprovalParticipant, ParticipantInput } from '@/types/approval'
import { fmtDateTime, isGroupLegal, useApprovalCard } from '@/composables/useApprovalCard'
import UserSearchSelect from '@/components/UserSearchSelect.vue'
import DocumentEditor from '@/components/DocumentEditor.vue'
import PdfPreview from '@/components/PdfPreview.vue'
import DocumentsCard from '@/components/DocumentsCard.vue'
import DecisionCard from '@/components/approval/DecisionCard.vue'
import HistoryCard from '@/components/approval/HistoryCard.vue'
import RoundsCards from '@/components/approval/RoundsCards.vue'
import SummaryCard from '@/components/approval/SummaryCard.vue'

const props = defineProps<{ id: string }>()
const auth = useAuthStore()
const router = useRouter()

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

// Маршрут для отправки: слот + выбранный вручную согласующий (manual) и
// признак, что автоподобранного согласующего инициатор решил заменить.
type RouteRow = RouteSlot & { manual: string; replacing: boolean }
const route = ref<RouteRow[]>([])
// справочник сотрудников для выбора согласующих по ФИО
const users = ref<UserOption[]>([])
// названия процессных ролей (код → человекочитаемое)
const roleNames = ref<Record<string, string>>({})
function roleName(code: string | undefined): string {
  return (code && roleNames.value[code]) || code || '—'
}
// исполнение
const deliveryMethod = ref('personally')
const deliveryComment = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const versionInput = ref<HTMLInputElement | null>(null)
const versionDocId = ref<number | null>(null)
const editingDocId = ref<number | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    req.value = await requests.get(props.id)
    if (!users.value.length) {
      try { users.value = await requests.users() } catch { /* не критично */ }
    }
    if (!Object.keys(roleNames.value).length) {
      try {
        const t = await requests.types()
        roleNames.value = Object.fromEntries(t.roles?.map((r) => [r.code, r.name]) || [])
      } catch { /* не критично */ }
    }
    await enrichUnknownUsers()
    if (canSubmit.value) await loadRoute()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

async function loadRoute() {
  const { route: slots } = await requests.routePreview(props.id)
  route.value = slots.map((s) => ({ ...s, manual: '', replacing: false }))
  routeLoaded.value = true
}

// Замена согласующего, которого подобрала матрица ролей: руководитель в
// отпуске, роль сменила хозяина, назначение устарело. Делается явным
// действием — иначе один промах по списку молча переписал бы маршрут.
function startReplace(s: RouteRow) {
  s.replacing = true
  s.manual = ''
}
function cancelReplace(s: RouteRow) {
  s.replacing = false
  s.manual = ''
}

// ФИО согласующего по его bitrix_id (для отображения авто-выбранных слотов)
function nameByBid(bid: number | null | undefined): string {
  const u = users.value.find((x) => x.bitrix_id === bid)
  return u ? u.fio : ''
}

// Выбрали сотрудника в поиске — добавим его в локальный справочник, чтобы
// дальше (в кругах согласования) он резолвился в ФИО, а не «USER #id».
function onPickUser(u: UserOption) {
  if (!users.value.some((x) => x.bitrix_id === u.bitrix_id)) users.value.push(u)
}

// Участника могли выбрать поиском по Битриксу — в матрице сотрудников
// (/core/users/) его нет, и он показался бы как «USER #id». Дотягиваем ФИО
// из портала; вне Битрикса — тихий no-op.
async function enrichUnknownUsers() {
  const need = new Set<number>()
  for (const r of req.value?.approval?.rounds || []) {
    for (const p of r.participants) {
      if (p.type === 'internal' && p.b24_user_id && !nameByBid(p.b24_user_id)) {
        need.add(p.b24_user_id)
      }
    }
  }
  if (!need.size) return
  try {
    users.value = users.value.concat(await bitrix.userOptionsByIds([...need]))
  } catch { /* портал недоступен — останется «USER #id» */ }
}

const isInitiator = computed(() => req.value?.initiator_b24_id === auth.b24UserId)
// Отправка/перезапуск: черновик, возвращённая или ОТКЛОНЁННАЯ (2-й круг).
const canSubmit = computed(
  () => isInitiator.value &&
    ['draft', 'returned', 'rejected'].includes(req.value?.status || ''),
)
// Править поля можно там же, где отправлять: черновик, возвращённая и
// отклонённая (requests_reg EDITABLE_STATUSES). Вернули на доработку —
// значит есть что дорабатывать.
const canEdit = canSubmit
const isLegalStage = computed(() => req.value && LEGAL_STATUSES.includes(req.value.status))
// Отмена доступна до передачи юристам; удаление — только у отменённой.
const canCancel = computed(
  () => isInitiator.value &&
    ['draft', 'on_approval', 'returned', 'rejected'].includes(req.value?.status || ''),
)
const canDelete = computed(() => isInitiator.value && req.value?.status === 'canceled')

function cancelRequest() {
  if (!confirm('Отменить заявку?')) return
  run(() => requests.cancel(props.id))
}
async function removeRequest() {
  if (!confirm('Удалить отменённую заявку безвозвратно?')) return
  busy.value = true
  error.value = null
  try {
    await requests.remove(props.id)
    router.push('/requests')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить'
    busy.value = false
  }
}

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

// Пояснение инициатора согласующим при направлении круга (в т.ч. повторном).
const submitComment = ref('')

// Пустой маршрут бывает только у отзыва, поданного руководителем ЦФО: он сам
// единственный согласующий, круга не будет — заявка уйдёт прямо юристам.
// routeLoaded отличает «маршрут пуст» от «маршрут ещё не приехал».
const routeLoaded = ref(false)
const noApprovalNeeded = computed(() => routeLoaded.value && route.value.length === 0)

function submit() {
  const participants: ParticipantInput[] = []
  for (const [i, s] of route.value.entries()) {
    // Групповой этап (юротдел) уходит без персонального согласующего —
    // b24_user_id null там не ошибка, а норма.
    const uid = s.resolved && !s.replacing ? s.b24_user_id! : parseInt(s.manual, 10)
    if (Number.isNaN(uid)) {
      error.value = s.replacing
        ? `Выберите, кем заменить согласующего в роли «${s.role_name}»`
        : `Укажите согласующего для роли «${s.role_name}»`
      return
    }
    participants.push({ type: 'internal', b24_user_id: uid, role: s.role_code, order: i })
  }
  run(async () => {
    const r = await requests.submit(props.id, participants, submitComment.value.trim())
    route.value = []
    routeLoaded.value = false
    submitComment.value = ''
    return r
  })
}

// Как участник подписан в кругах и в истории.
function partLabel(p: ApprovalParticipant): string {
  if (isGroupLegal(p)) return 'Юридический отдел'
  if (p.type === 'external') return p.email || p.name || 'внешний участник'
  return nameByBid(p.b24_user_id) || `USER #${p.b24_user_id}`
}

// Общая логика карточки согласования (та же, что у договоров).
const { rounds, currentRound, pendingPart, myPart, myDecided, iAmParticipant, progress, history, waitingParts,
} =
  useApprovalCard(
    () => req.value?.approval,
    () => req.value?.status === 'on_approval',
    partLabel,
  )

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject', comment: string) {
  run(() => requests.decide(props.id, p.id, decision, comment))
}

// Инициатор может отозвать заявку с круга и доработать (потом — новый круг).
const canReturn = computed(() => isInitiator.value && req.value?.status === 'on_approval')
function returnForRevision() {
  const comment = window.prompt('Причина возврата на доработку:') || ''
  if (!comment.trim()) return
  run(() => requests.returnForRevision(props.id, comment.trim()))
}

// Строки сводки, специфичные для доверенности: исполнение и получение.
const summaryExtras = computed(() => {
  const rows: { label: string; value: string }[] = []
  if (req.value?.executed_at) rows.push({ label: 'Исполнена', value: fmtDateTime(req.value.executed_at) })
  if (req.value?.received_at) rows.push({ label: 'Получена инициатором', value: fmtDateTime(req.value.received_at) })
  return rows
})

function dl(url: string | null, name: string) {
  if (url) api.download(url, name).catch((e) => (error.value = e.message))
}
function downloadAnketa() {
  if (req.value) api.download(requests.anketaPdfUrl(req.value.id), `Заявление_${req.value.number}.pdf`)
    .catch((e) => (error.value = e.message))
}
function downloadSheet() {
  if (req.value) api.download(requests.sheetPdfUrl(req.value.id), `Лист_согласования_${req.value.number}.pdf`)
    .catch((e) => (error.value = e.message))
}
// лист согласования доступен, когда есть хотя бы один круг
const hasApproval = computed(() => (req.value?.approval?.rounds?.length || 0) > 0)
// доверенность — приложенные документы (скан), кроме автозаявления-анкеты
const doverennostDocs = computed(
  () => (req.value?.documents || []).filter((d) => d.document_type !== 'anketa' && d.download_url),
)
const isAnketaType = computed(() => req.value && (req.value.request_type === 'poa' || req.value.request_type === 'mchd'))
const isRevoke = computed(() => req.value?.request_type === 'revoke')
// У отзыва своё заявление (что отзываем, почему, с какой даты) — юрист
// работает именно с ним, поэтому показываем его так же, как анкету.
const hasAnketaPdf = computed(() => isAnketaType.value || isRevoke.value)

// Человекочитаемая причина отзыва из анкеты.
const REVOKE_REASON_NAMES: Record<string, string> = {
  dismissal: 'Увольнение / перевод представителя',
  powers_changed: 'Изменение полномочий или должности',
  task_done: 'Задача выполнена, доверенность больше не нужна',
  lost: 'Утрата бланка доверенности',
  trust_lost: 'Утрата доверия к представителю',
  other: 'Иная причина',
}
const revokeData = computed(() => (req.value?.data || {}) as Record<string, string>)
const revokeSource = computed(
  () => (revokeData.value.source || {}) as unknown as Record<string, string>,
)
// Тот же адрес, что у кнопки «Скачать заявление» — PDF собирается на лету,
// поэтому просмотр всегда показывает актуальную анкету.
const anketaUrl = computed(() => (req.value ? requests.anketaPdfUrl(req.value.id) : ''))

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

// Новая версия существующего документа: старая остаётся в истории.
function pickVersion(docId: number) {
  versionDocId.value = docId
  versionInput.value?.click()
}
async function uploadVersion(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  const docId = versionDocId.value
  if (!file || !docId) return
  const comment = window.prompt('Комментарий к версии (что изменено, необязательно):') || ''
  busy.value = true
  error.value = null
  try {
    await documentsApi.addVersion(docId, file, comment)
    req.value = await requests.get(props.id)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Не удалось загрузить версию'
  } finally {
    busy.value = false
    versionDocId.value = null
    input.value = ''
  }
}

function onEditorClose(changed: boolean) {
  editingDocId.value = null
  if (changed) load()
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

      <div class="req-layout">
        <!-- Заявление (анкета) прямо на странице: раньше её приходилось
             скачивать каждый раз, чтобы просто посмотреть. -->
        <PdfPreview
          v-if="hasAnketaPdf" class="req-preview"
          :src="anketaUrl" title="Заявление (анкета)"
          :filename="`Заявление_${req.number}.pdf`"
        />

        <div class="req-cards">
      <!-- Отзыв: что именно отзываем и на каком основании -->
      <div v-if="isRevoke" class="detail-card">
        <div class="detail-card-header">Отзываемая доверенность</div>
        <table class="round-table">
          <tbody>
            <tr v-if="req.source_request_info">
              <td>Документ</td>
              <td>
                <RouterLink :to="`/requests/${req.source_request_info.id}`" class="src-link">
                  {{ req.source_request_info.number }} · {{ req.source_request_info.type_display }}
                </RouterLink>
                <span class="ag-muted"> — {{ req.source_request_info.subject_name || '—' }}
                  ({{ req.source_request_info.status_display }})</span>
              </td>
            </tr>
            <!-- Бумажная доверенность до MiniSED: карточки нет, есть реквизиты -->
            <template v-else>
              <tr><td>Номер</td><td>{{ revokeSource.number || '—' }}</td></tr>
              <tr><td>Дата выдачи</td><td>{{ revokeSource.issued_at || '—' }}</td></tr>
              <tr v-if="revokeSource.subject_name">
                <td>Выдана на имя</td><td>{{ revokeSource.subject_name }}</td>
              </tr>
              <tr v-if="revokeSource.note"><td>Примечание</td><td>{{ revokeSource.note }}</td></tr>
            </template>
            <tr>
              <td>Причина</td>
              <td>{{ REVOKE_REASON_NAMES[revokeData.revoke_reason] || '—' }}</td>
            </tr>
            <tr v-if="revokeData.revoke_reason_text">
              <td>Обоснование</td>
              <td style="white-space:pre-line">{{ revokeData.revoke_reason_text }}</td>
            </tr>
            <tr v-if="revokeData.revoke_date">
              <td>Отозвать с даты</td><td>{{ revokeData.revoke_date }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Обратная связка: открыв доверенность, видно, что её отзывают -->
      <div v-if="req.revocations && req.revocations.length" class="detail-card">
        <div class="detail-card-header">Заявки на отзыв этой доверенности</div>
        <table class="round-table">
          <tbody>
            <tr v-for="r in req.revocations" :key="r.id">
              <td>
                <RouterLink :to="`/requests/${r.id}`" class="src-link">{{ r.number }}</RouterLink>
              </td>
              <td>{{ r.status_display }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Суть заявки: основание и комментарий инициатора -->
      <div v-if="req.basis || req.comment || req.position || req.department" class="detail-card">
        <div class="detail-card-header">Заявка</div>
        <table class="round-table">
          <tbody>
            <tr v-if="req.position"><td>Должность</td><td>{{ req.position }}</td></tr>
            <tr v-if="req.department"><td>Подразделение</td><td>{{ req.department }}</td></tr>
            <tr v-if="req.valid_from || req.valid_until">
              <td>Срок</td>
              <td>{{ req.valid_from || '—' }} — {{ req.valid_until || '—' }}</td>
            </tr>
            <tr v-if="req.basis"><td>Основание</td><td style="white-space:pre-line">{{ req.basis }}</td></tr>
            <tr v-if="req.comment"><td>Комментарий</td><td style="white-space:pre-line">{{ req.comment }}</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Предпросмотр маршрута + отправка -->
      <div v-if="canSubmit" class="detail-card">
        <div class="detail-card-header">
          {{ noApprovalNeeded ? 'Согласование не требуется' : 'Маршрут согласования (последовательный)' }}
        </div>
        <p v-if="noApprovalNeeded" class="detail-meta" style="margin:0 0 4px">
          Отзыв согласует руководитель ЦФО — а заявку подали вы. Согласовывать
          нечего: заявка уйдёт сразу юристам на исполнение.
        </p>
        <table v-else class="round-table">
          <tbody>
            <tr v-for="s in route" :key="s.order">
              <td>{{ s.order + 1 }}. {{ s.role_name }}</td>
              <td>
                <!-- Юротдел — групповой этап: согласует любой юрист, менять некого -->
                <template v-if="s.group">{{ s.user_name || 'Юридический отдел' }}</template>
                <template v-else-if="s.resolved && !s.replacing">
                  {{ s.user_name || nameByBid(s.b24_user_id) || `USER #${s.b24_user_id}` }}
                  <button
                    v-if="s.replaceable" type="button" class="link-btn"
                    @click="startReplace(s)"
                  >заменить</button>
                </template>
                <template v-else>
                  <UserSearchSelect
                    v-model="s.manual" :users="users"
                    placeholder="найти согласующего…" @pick="onPickUser"
                  />
                  <button v-if="s.resolved" type="button" class="link-btn" @click="cancelReplace(s)">
                    вернуть автоподбор
                  </button>
                </template>
              </td>
              <td>
                <span v-if="s.needs_manual" class="participant-pill" style="background:#ffe0b2">ручной выбор</span>
                <span v-else-if="s.replacing" class="participant-pill" style="background:#e3f2fd">замена</span>
              </td>
            </tr>
          </tbody>
        </table>
        <!-- Пояснение согласующим: с чем направляем круг (что изменилось
             после доработки). Необязательное — перезапуск в один клик сохранён. -->
        <div v-if="!noApprovalNeeded" style="margin-top:12px">
          <div class="detail-meta" style="margin-bottom:4px">
            {{ rounds.length
              ? 'Комментарий согласующим — что изменилось после доработки (необязательно)'
              : 'Комментарий согласующим (необязательно)' }}
          </div>
          <textarea
            v-model="submitComment" rows="2" class="submit-comment"
            placeholder="Например: снизили сумму, приложена новая редакция"
          ></textarea>
        </div>

        <div style="margin-top:10px">
          <button class="btn btn--primary" :disabled="busy" @click="submit">
            {{ noApprovalNeeded
              ? 'Передать юристам'
              : req.status === 'rejected'
                ? 'Перезапустить согласование (новый круг)'
                : 'Отправить на согласование' }}
          </button>
        </div>
      </div>

      <!-- Управление: правка / возврат / отмена / удаление -->
      <div v-if="canCancel || canDelete || canReturn || canEdit" class="detail-card">
        <div class="detail-card-header">Управление</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <RouterLink v-if="canEdit" :to="`/requests/${req.id}/edit`" class="btn btn--primary">
            Редактировать заявку
          </RouterLink>
          <button v-if="canReturn" class="btn btn--soft" :disabled="busy" @click="returnForRevision">Вернуть на доработку</button>
          <button v-if="canCancel" class="btn btn--soft" :disabled="busy" @click="cancelRequest">Отменить заявку</button>
          <button v-if="canDelete" class="btn btn--danger" :disabled="busy" @click="removeRequest">Удалить заявку</button>
        </div>
        <div class="detail-meta" style="margin-top:6px">
          <template v-if="canDelete">Заявка отменена — её можно удалить безвозвратно.</template>
          <template v-else-if="canEdit">
            Поля заявки открыты для правки, пока она не на согласовании. После
            правок отправьте её на согласование заново.
          </template>
          <template v-else>Отменить можно до передачи юристам. Отменённую заявку затем можно удалить.</template>
        </div>
      </div>

      <!-- Лист согласования (PDF) -->
      <div v-if="hasApproval" class="detail-card">
        <div class="detail-card-header">Лист согласования</div>
        <button class="btn btn--soft" :disabled="busy" @click="downloadSheet">Скачать лист согласования (PDF)</button>
      </div>

      <DecisionCard
        :pending="pendingPart" :my-part="myPart" :my-decided="myDecided"
        :is-participant="iAmParticipant" :waiting="waitingParts" :busy="busy"
        :role-name="roleName" :label="partLabel"
        @decide="decide" @error="(m) => (error = m)"
      />

      <RoundsCards
        :rounds="rounds" :pending-id="pendingPart?.id ?? null"
        :role-name="roleName" :label="partLabel"
      />

      <HistoryCard :history="history" />

      <SummaryCard
        v-if="rounds.length"
        :round-number="currentRound?.round_number ?? null"
        :progress="progress"
        :waiting-for="pendingPart ? partLabel(pendingPart) : ''"
        :created-at="req.created_at"
        :submitted-at="req.approval?.submitted_at"
        :completed-at="req.approval?.completed_at"
        :extra-rows="summaryExtras"
      />

      <DocumentsCard
        :docs="req.documents" :busy="busy"
        :upload-label="isLegalStage ? 'Прикрепить скан доверенности' : 'Прикрепить документ'"
        hint="Правки: скачайте версию, измените локально и загрузите как «новую версию» — старая останется в истории. Файлы Word/Excel можно править прямо в браузере."
        @download="dl" @upload="fileInput?.click()"
        @add-version="pickVersion" @edit="(id) => (editingDocId = id)"
      >
        <template #actions>
          <button v-if="hasAnketaPdf" class="btn btn--ghost" @click="downloadAnketa">Скачать заявление (PDF)</button>
        </template>
      </DocumentsCard>
      <input ref="fileInput" type="file" style="display:none" @change="uploadFile" />
      <input ref="versionInput" type="file" style="display:none" @change="uploadVersion" />

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
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button
            v-for="d in doverennostDocs" :key="d.id"
            class="btn btn--soft" :disabled="busy"
            @click="dl(d.download_url, d.title)"
          >Скачать доверенность{{ doverennostDocs.length > 1 ? ` (${d.title})` : '' }}</button>
          <button v-if="isInitiator" class="btn btn--primary" :disabled="busy" @click="run(() => requests.confirmReceipt(req!.id))">
            Получил / ознакомился
          </button>
        </div>
      </div>
        </div>
      </div>
    </template>

    <!-- Оверлей онлайн-редактора -->
    <DocumentEditor v-if="editingDocId" :doc-id="editingDocId" @close="onEditorClose" />
  </section>
</template>

<style scoped>
.src-link { color: #1976d2; text-decoration: none; font-weight: 500; }
.src-link:hover { text-decoration: underline; }
/* Две колонки на широком экране: слева анкета, справа карточки заявки.
   Узкий экран (в т.ч. iframe Битрикса) — одна колонка, анкета уходит вниз:
   сначала суть заявки и действия, просмотр — следом. */
.req-layout { display: grid; grid-template-columns: 1fr; gap: 14px; }
.req-preview { order: 2; }
.req-cards { order: 1; min-width: 0; }
@media (min-width: 1180px) {
  /* Документу — вся оставшаяся ширина, карточкам хватает 520px:
     анкета плотная, читать её в узкой колонке неудобно. */
  .req-layout { grid-template-columns: minmax(0, 1fr) minmax(320px, 520px); align-items: start; }
  .req-preview { order: 0; position: sticky; top: 0; }
  .req-cards { order: 0; }
}

.submit-comment {
  width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #d0d0d0;
  border-radius: 6px; font: inherit; font-size: 13px; resize: vertical;
}
.link-btn {
  background: none; border: none; padding: 0; margin-left: 8px;
  color: var(--green-main); cursor: pointer; font: inherit; font-size: 12px;
  text-decoration: underline;
}
</style>
