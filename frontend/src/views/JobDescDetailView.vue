<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { bitrix } from '@/services/bitrix'
import { DOC_TYPE_FINAL, jobdesc } from '@/services/jobdesc'
import { documents as documentsApi } from '@/services/documents'
import { requests, type UserOption } from '@/services/requests'
import { api, ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { JobDescDetail, JobDescRouteSlot } from '@/types/jobdesc'
import type { ApprovalParticipant, ParticipantInput } from '@/types/approval'
import { fmtDateTime, isGroupLegal, useApprovalCard } from '@/composables/useApprovalCard'
import DocumentEditor from '@/components/DocumentEditor.vue'
import DocumentsCard from '@/components/DocumentsCard.vue'
import UserSearchSelect from '@/components/UserSearchSelect.vue'
import DecisionCard from '@/components/approval/DecisionCard.vue'
import HistoryCard from '@/components/approval/HistoryCard.vue'
import RoundsCards from '@/components/approval/RoundsCards.vue'
import SummaryCard from '@/components/approval/SummaryCard.vue'

const props = defineProps<{ id: string }>()
const auth = useAuthStore()
const router = useRouter()

const jd = ref<JobDescDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

// Маршрут строится по ЦФО/юрлицу/флажку; вручную выбирают тех, у кого роль
// не назначена, необязательные этапы и тех, кого инициатор решил заменить.
type RouteRow = JobDescRouteSlot & { manual: string; replacing: boolean }
const route = ref<RouteRow[]>([])
const extras = ref<{ uid: string; after: number }[]>([])
const users = ref<UserOption[]>([])
// Сотрудники отдела персонала — для первого этапа маршрута.
const hrUsers = ref<UserOption[]>([])
const roleNames = ref<Record<string, string>>({})
const transferMethods = ref<{ code: string; name: string }[]>([])
const isHr = ref(false)

function roleName(code: string | undefined): string {
  if (!code) return 'Доп. согласующий'
  return roleNames.value[code] || code
}

const fileInput = ref<HTMLInputElement | null>(null)
const finalInput = ref<HTMLInputElement | null>(null)
const versionInput = ref<HTMLInputElement | null>(null)
const versionDocId = ref<number | null>(null)
const editingDocId = ref<number | null>(null)

const status = computed(() => jd.value?.status || '')
const isInitiator = computed(() => jd.value?.initiator_b24_id === auth.b24UserId)
const canSubmit = computed(() => isInitiator.value && ['draft', 'returned', 'rejected'].includes(status.value))
const canEdit = canSubmit
const canCancel = computed(() => isInitiator.value && ['draft', 'on_approval', 'returned', 'rejected'].includes(status.value))
const canDelete = computed(() => isInitiator.value && status.value === 'canceled')
const canReturn = computed(() => isInitiator.value && status.value === 'on_approval')

// Исполнение — у отдела персонала.
const inHrPhase = computed(() => ['to_hr', 'hr_work', 'signing'].includes(status.value))
const canWork = computed(() => (isHr.value || auth.canViewAll) && inHrPhase.value)
const canAcknowledge = computed(() => isInitiator.value && status.value === 'executed')
const finalDocs = computed(() => (jd.value?.documents || []).filter((d) => d.document_type === DOC_TYPE_FINAL))
const workDocs = computed(() => (jd.value?.documents || []).filter((d) => d.document_type !== DOC_TYPE_FINAL))
const transferMethod = ref('')
const executionComment = ref('')

function startReplace(s: RouteRow) {
  s.replacing = true
  s.manual = ''
}
function cancelReplace(s: RouteRow) {
  s.replacing = false
  s.manual = ''
}

async function load() {
  loading.value = true
  error.value = null
  try {
    jd.value = await jobdesc.get(props.id)
    if (!users.value.length) {
      try { users.value = await requests.users() } catch { /* не критично */ }
    }
    if (!Object.keys(roleNames.value).length) {
      try {
        const m = await jobdesc.meta()
        roleNames.value = Object.fromEntries(m.roles.map((r) => [r.code, r.name]))
        transferMethods.value = m.transfer_methods
        isHr.value = m.is_hr_staff
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
  const [{ route: slots }, staff] = await Promise.all([
    jobdesc.routePreview(props.id),
    jobdesc.hrStaff().catch(() => []),
  ])
  hrUsers.value = staff.map((s) => ({ id: s.bitrix_id, bitrix_id: s.bitrix_id, fio: s.fio, position_name: s.position }))
  route.value = slots.map((s) => ({ ...s, manual: '', replacing: false }))
  extras.value = []
}

function addApprover() {
  const last = route.value[route.value.length - 1]
  extras.value.push({ uid: '', after: last ? last.order : -1 })
}
function removeExtra(i: number) {
  extras.value.splice(i, 1)
}

function nameByBid(bid: number | null | undefined): string {
  const u = users.value.find((x) => x.bitrix_id === bid) || hrUsers.value.find((x) => x.bitrix_id === bid)
  return u ? u.fio : ''
}
function onPickUser(u: UserOption) {
  if (!users.value.some((x) => x.bitrix_id === u.bitrix_id)) users.value.push(u)
}

// Согласующего могли выбрать поиском по Битриксу — его нет в матрице
// сотрудников; дотягиваем ФИО из портала, иначе будет «USER #id».
async function enrichUnknownUsers() {
  const need = new Set<number>()
  for (const r of jd.value?.approval?.rounds || []) {
    for (const p of r.participants) {
      if (p.type === 'internal' && p.b24_user_id && !nameByBid(p.b24_user_id)) need.add(p.b24_user_id)
    }
  }
  for (const bid of [jd.value?.executor_b24_id, jd.value?.initiator_b24_id]) {
    if (bid && !nameByBid(bid)) need.add(bid)
  }
  if (!need.size) return
  try {
    users.value = users.value.concat(await bitrix.userOptionsByIds([...need]))
  } catch { /* портал недоступен */ }
}

async function run(fn: () => Promise<JobDescDetail>) {
  busy.value = true
  error.value = null
  try {
    jd.value = await fn()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

// Участники в итоговом порядке: этапы маршрута + добавленные инициатором.
// Пустой необязательный этап («при наличии») просто пропускаем.
function buildParticipants(): ParticipantInput[] | null {
  const list: { b24_user_id: number | null; role: string }[] = []
  let failed = false

  const pushExtras = (after: number) => {
    for (const e of extras.value.filter((x) => x.after === after)) {
      const uid = parseInt(e.uid, 10)
      if (Number.isNaN(uid)) {
        error.value = 'Выберите сотрудника для добавленного согласующего.'
        failed = true
        return
      }
      list.push({ b24_user_id: uid, role: '' })
    }
  }

  pushExtras(-1)
  for (const s of route.value) {
    if (s.group) {
      list.push({ b24_user_id: null, role: s.role_code })
    } else {
      const uid = s.resolved && !s.replacing ? s.b24_user_id! : parseInt(s.manual, 10)
      if (Number.isNaN(uid)) {
        if (!s.optional) {
          error.value = s.replacing
            ? `Выберите, кем заменить согласующего в роли «${s.role_name}».`
            : `Укажите согласующего для роли «${s.role_name}».`
          return null
        }
      } else {
        list.push({ b24_user_id: uid, role: s.role_code })
      }
    }
    pushExtras(s.order)
    if (failed) return null
  }
  return list.map((x, i) => ({ type: 'internal', b24_user_id: x.b24_user_id, role: x.role, order: i }))
}

const submitComment = ref('')
function submit() {
  const participants = buildParticipants()
  if (!participants) return
  run(async () => {
    const r = await jobdesc.submit(props.id, participants, submitComment.value.trim())
    route.value = []
    extras.value = []
    submitComment.value = ''
    return r
  })
}

function partLabel(p: ApprovalParticipant): string {
  if (isGroupLegal(p)) return 'Юридический отдел'
  if (p.type === 'external') return p.email || p.name || 'внешний участник'
  return nameByBid(p.b24_user_id) || `USER #${p.b24_user_id}`
}

const { rounds, currentRound, pendingPart, myPart, myDecided, iAmParticipant, progress, history, waitingParts } =
  useApprovalCard(() => jd.value?.approval, () => status.value === 'on_approval', partLabel)

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject', comment: string) {
  run(() => jobdesc.decide(props.id, p.id, decision, comment))
}
function returnForRevision() {
  const comment = window.prompt('Причина возврата на доработку:') || ''
  if (!comment.trim()) return
  run(() => jobdesc.returnForRevision(props.id, comment.trim()))
}
function cancelJd() {
  if (!confirm('Отменить заявку?')) return
  run(() => jobdesc.cancel(props.id))
}
async function removeJd() {
  if (!confirm('Удалить отменённую заявку безвозвратно?')) return
  busy.value = true
  try {
    await jobdesc.remove(props.id)
    router.push('/jobdesc')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить'
    busy.value = false
  }
}

// --- исполнение ---
function take() {
  run(() => jobdesc.take(props.id))
}
function setStatus(s: 'hr_work' | 'signing') {
  run(() => jobdesc.setStatus(props.id, s))
}
function execute() {
  if (!finalDocs.value.length) return void (error.value = 'Прикрепите файл или скан готовой ДИ.')
  if (!transferMethod.value) return void (error.value = 'Укажите способ передачи ДИ.')
  run(() => jobdesc.execute(props.id, transferMethod.value, executionComment.value.trim()))
}
function acknowledge() {
  if (!confirm('Подтвердить, что ДИ получена и вы с ней ознакомились? Заявка будет закрыта.')) return
  run(() => jobdesc.acknowledge(props.id))
}

const summaryExtras = computed(() => {
  const rows: { label: string; value: string }[] = []
  const d = jd.value
  if (d?.taken_at) rows.push({ label: 'Взята в работу', value: fmtDateTime(d.taken_at) })
  if (d?.executor_b24_id) {
    rows.push({ label: 'Исполнитель', value: nameByBid(d.executor_b24_id) || `USER #${d.executor_b24_id}` })
  }
  if (d?.executed_at) rows.push({ label: 'Исполнена', value: fmtDateTime(d.executed_at) })
  if (d?.received_at) rows.push({ label: 'Получена инициатором', value: fmtDateTime(d.received_at) })
  return rows
})

function dl(url: string | null, name: string) {
  if (url) api.download(url, name).catch((e) => (error.value = e.message))
}
function downloadSheet() {
  if (jd.value) {
    api.download(jobdesc.sheetPdfUrl(props.id), `Лист_согласования_${jd.value.number}.pdf`)
      .catch((e) => (error.value = e.message))
  }
}
const hasApproval = computed(() => (jd.value?.approval?.rounds?.length || 0) > 0)

async function upload(e: Event, documentType = '') {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return
  busy.value = true
  error.value = null
  try {
    for (const f of files) await jobdesc.uploadDocument(props.id, f, f.name, documentType)
    jd.value = await jobdesc.get(props.id)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Не удалось загрузить файл'
  } finally {
    busy.value = false
    input.value = ''
  }
}
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
    jd.value = await jobdesc.get(props.id)
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
    <RouterLink to="/jobdesc" class="back-link">← К должностным инструкциям</RouterLink>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error && !jd" class="state state--error">{{ error }}</p>

    <template v-else-if="jd">
      <div class="detail-header-main">
        <div>
          <h1 class="detail-title">{{ jd.number }} · {{ jd.position_name }}</h1>
          <div class="detail-meta">
            {{ [jd.organization_name, jd.cfo_name, jd.facility_name].filter(Boolean).join(' · ') }}
            · инициатор {{ nameByBid(jd.initiator_b24_id) || `#${jd.initiator_b24_id}` }}
          </div>
          <div v-if="jd.is_nonstandard" class="detail-meta">
            <span class="tag-chip">нестандартная форма</span>
          </div>
        </div>
        <span class="status-pill" :class="jd.status">{{ jd.status_display }}</span>
      </div>

      <p v-if="error" class="state state--error">{{ error }}</p>

      <!-- Инициатору: ДИ исполнена — подтвердить получение -->
      <div v-if="canAcknowledge" class="detail-card ack-card">
        <div class="detail-card-header">Должностная инструкция готова</div>
        <div class="detail-meta" style="margin-bottom:8px">
          Способ передачи: <b>{{ jd.transfer_display }}</b>.
          <template v-if="jd.execution_comment"> {{ jd.execution_comment }}</template>
        </div>
        <button class="btn btn--primary" :disabled="busy" @click="acknowledge">Получил / ознакомился</button>
      </div>

      <!-- Суть заявки -->
      <div class="detail-card">
        <div class="detail-card-header">Заявка</div>
        <table class="round-table">
          <tbody>
            <tr><td>Должность</td><td>{{ jd.position_name }}</td></tr>
            <tr><td>Организация</td><td>{{ jd.organization_name }}</td></tr>
            <tr><td>ЦФО</td><td>{{ jd.cfo_name }}</td></tr>
            <tr v-if="jd.facility_name"><td>Объект / проект</td><td>{{ jd.facility_name }}</td></tr>
            <tr><td>Форма</td><td>{{ jd.is_nonstandard ? 'нестандартная / изменены шаблонные условия' : 'стандартный шаблон' }}</td></tr>
            <tr v-if="jd.description">
              <td>Комментарий</td><td style="white-space:pre-line">{{ jd.description }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Предпросмотр маршрута + отправка -->
      <div v-if="canSubmit" class="detail-card">
        <div class="detail-card-header">Маршрут согласования (последовательный)</div>
        <table class="round-table">
          <tbody>
            <tr v-for="s in route" :key="s.order">
              <td>
                {{ s.order + 1 }}. {{ s.role_name }}
                <div v-if="s.merged_roles.length" class="detail-meta">также: {{ s.merged_roles.join(', ') }}</div>
              </td>
              <td>
                <template v-if="s.group">Юридический отдел (любой юрист)</template>
                <template v-else-if="s.resolved && !s.replacing">
                  {{ s.user_name || nameByBid(s.b24_user_id) || `USER #${s.b24_user_id}` }}
                  <button v-if="s.replaceable" type="button" class="link-btn" @click="startReplace(s)">заменить</button>
                </template>
                <template v-else>
                  <UserSearchSelect
                    v-model="s.manual" :users="s.hr_pick ? hrUsers : users"
                    :placeholder="s.optional ? 'если есть — найти…' : s.hr_pick ? 'сотрудник отдела персонала…' : 'найти согласующего…'"
                    @pick="onPickUser"
                  />
                  <button v-if="s.resolved" type="button" class="link-btn" @click="cancelReplace(s)">вернуть автоподбор</button>
                </template>
              </td>
              <td>
                <span v-if="s.auto_by_initiator && !s.replacing" class="participant-pill" style="background:#c8e6c9">согласуется при отправке</span>
                <span v-else-if="s.optional && !s.manual" class="participant-pill" style="background:#eceff1">при наличии</span>
                <span v-else-if="s.needs_manual" class="participant-pill" style="background:#ffe0b2">ручной выбор</span>
                <span v-else-if="s.replacing" class="participant-pill" style="background:#e3f2fd">замена</span>
              </td>
            </tr>
            <!-- Исполнение показываем, чтобы был виден весь путь до конца -->
            <tr>
              <td>Исполнение · Отдел по работе с персоналом</td>
              <td>готовая ДИ, способ передачи, ваше «Получил / ознакомился»</td>
              <td><span class="participant-pill" style="background:#e0f2f1">после утверждения</span></td>
            </tr>
          </tbody>
        </table>

        <div class="extras">
          <div class="extras-title">Дополнительные согласующие</div>
          <div v-for="(e, i) in extras" :key="i" class="extra-row">
            <div class="extra-select">
              <UserSearchSelect v-model="e.uid" :users="users" placeholder="найти сотрудника…" @pick="onPickUser" />
            </div>
            <label class="extra-after">
              вставить
              <select v-model.number="e.after">
                <option :value="-1">в начале</option>
                <option v-for="s in route" :key="s.order" :value="s.order">после «{{ s.role_name }}»</option>
              </select>
            </label>
            <button type="button" class="extra-x" title="Убрать" @click="removeExtra(i)">×</button>
          </div>
          <button type="button" class="btn btn--ghost" style="font-size:13px" @click="addApprover">＋ Добавить согласующего</button>
        </div>

        <div style="margin-top:12px">
          <div class="detail-meta" style="margin-bottom:4px">
            {{ rounds.length
              ? 'Комментарий согласующим — что изменилось после доработки (необязательно)'
              : 'Комментарий согласующим (необязательно)' }}
          </div>
          <textarea v-model="submitComment" rows="2" class="submit-comment"
                    placeholder="Например: учтены правки юротдела, приложена новая редакция"></textarea>
        </div>

        <div style="margin-top:12px">
          <button class="btn btn--primary" :disabled="busy" @click="submit">
            {{ rounds.length ? 'Направить повторно (новый круг)' : 'Отправить на согласование' }}
          </button>
        </div>
      </div>

      <!-- Управление -->
      <div v-if="canCancel || canDelete || canReturn || canEdit" class="detail-card">
        <div class="detail-card-header">Управление</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <RouterLink v-if="canEdit" :to="`/jobdesc/${jd.id}/edit`" class="btn btn--primary">Редактировать заявку</RouterLink>
          <button v-if="canReturn" class="btn btn--soft" :disabled="busy" @click="returnForRevision">Вернуть на доработку</button>
          <button v-if="canCancel" class="btn btn--soft" :disabled="busy" @click="cancelJd">Отменить заявку</button>
          <button v-if="canDelete" class="btn btn--danger" :disabled="busy" @click="removeJd">Удалить заявку</button>
        </div>
        <div class="detail-meta" style="margin-top:6px">
          Согласующий, которому нужны правки, отклоняет заявку с комментарием — после
          правок (в т.ч. в документе онлайн) направьте её повторно, новым кругом.
        </div>
      </div>

      <!-- Исполнение отделом по работе с персоналом -->
      <div v-if="canWork" class="detail-card">
        <div class="detail-card-header">Исполнение · отдел по работе с персоналом</div>
        <div v-if="status === 'to_hr'" style="margin-bottom:10px">
          <button class="btn btn--soft" :disabled="busy" @click="take">Взять в работу</button>
        </div>
        <div v-else class="status-switch">
          <span class="detail-meta">Статус:</span>
          <button class="btn" :class="status === 'hr_work' ? 'btn--primary' : 'btn--ghost'" :disabled="busy"
                  @click="setStatus('hr_work')">В работе</button>
          <button class="btn" :class="status === 'signing' ? 'btn--primary' : 'btn--ghost'" :disabled="busy"
                  @click="setStatus('signing')">На подписании</button>
        </div>

        <div class="exec-block">
          <div class="extras-title">Готовая ДИ (файл или скан) *</div>
          <ul v-if="finalDocs.length" class="final-list">
            <li v-for="d in finalDocs" :key="d.id">
              <a href="#" @click.prevent="dl(d.download_url, d.title)">{{ d.title }}</a>
            </li>
          </ul>
          <button class="btn btn--ghost" style="font-size:13px" :disabled="busy" @click="finalInput?.click()">
            ＋ Прикрепить готовую ДИ
          </button>
        </div>

        <div class="exec-block">
          <label class="form-field">
            <span>Способ передачи *</span>
            <select v-model="transferMethod">
              <option value="">— выберите —</option>
              <option v-for="m in transferMethods" :key="m.code" :value="m.code">{{ m.name }}</option>
            </select>
          </label>
          <input v-model="executionComment" type="text" class="exec-comment"
                 placeholder="Комментарий для инициатора (необязательно)" />
          <div style="margin-top:8px">
            <button class="btn btn--primary" :disabled="busy" @click="execute">Исполнена</button>
          </div>
        </div>
      </div>

      <!-- Итог исполнения -->
      <div v-if="['executed', 'closed'].includes(status)" class="detail-card">
        <div class="detail-card-header">Исполнение</div>
        <table class="round-table">
          <tbody>
            <tr><td>Исполнена</td><td>{{ fmtDateTime(jd.executed_at) }}</td></tr>
            <tr><td>Способ передачи</td><td>{{ jd.transfer_display }}</td></tr>
            <tr v-if="jd.execution_comment"><td>Комментарий</td><td>{{ jd.execution_comment }}</td></tr>
            <tr>
              <td>Готовая ДИ</td>
              <td>
                <div v-for="d in finalDocs" :key="d.id">
                  <a href="#" @click.prevent="dl(d.download_url, d.title)">{{ d.title }}</a>
                </div>
              </td>
            </tr>
            <tr v-if="jd.received_at"><td>Получил / ознакомился</td><td>{{ fmtDateTime(jd.received_at) }}</td></tr>
          </tbody>
        </table>
      </div>

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

      <RoundsCards :rounds="rounds" :pending-id="pendingPart?.id ?? null" :role-name="roleName" :label="partLabel" />

      <HistoryCard :history="history" />

      <SummaryCard
        v-if="rounds.length"
        :round-number="currentRound?.round_number ?? null"
        :progress="progress"
        :waiting-for="pendingPart ? partLabel(pendingPart) : ''"
        :created-at="jd.created_at"
        :submitted-at="jd.approval?.submitted_at"
        :completed-at="jd.approval?.completed_at"
        :extra-rows="summaryExtras"
      />

      <DocumentsCard
        :docs="workDocs" :busy="busy"
        @download="dl" @upload="fileInput?.click()"
        @add-version="pickVersion" @edit="(id) => (editingDocId = id)"
      />
      <input ref="fileInput" type="file" multiple style="display:none" @change="upload($event)" />
      <input ref="finalInput" type="file" multiple style="display:none" @change="upload($event, DOC_TYPE_FINAL)" />
      <input ref="versionInput" type="file" style="display:none" @change="uploadVersion" />
    </template>

    <DocumentEditor v-if="editingDocId" :doc-id="editingDocId" @close="onEditorClose" />
  </section>
</template>

<style scoped>
.submit-comment {
  width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #d0d0d0;
  border-radius: 6px; font: inherit; font-size: 13px; resize: vertical;
}
.exec-comment {
  width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #d0d0d0;
  border-radius: 6px; font: inherit; font-size: 13px; margin-top: 8px;
}
.link-btn {
  background: none; border: none; padding: 0; margin-left: 8px;
  color: var(--green-main); cursor: pointer; font: inherit; font-size: 12px; text-decoration: underline;
}
.extras { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--gray-border); }
.extras-title { font-size: 13px; font-weight: 600; color: var(--text-muted); margin-bottom: 8px; }
.extra-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.extra-select { flex: 1; min-width: 240px; }
.extra-after { font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 6px; }
.extra-after select { padding: 5px 8px; border: 1px solid var(--gray-border); border-radius: 6px; }
.extra-x {
  border: none; background: #ffcdd2; color: #b71c1c; border-radius: 50%;
  width: 22px; height: 22px; cursor: pointer; line-height: 1; font-size: 15px;
}
.status-switch { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.exec-block { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--gray-border); }
.exec-block .form-field { max-width: 360px; }
.final-list { margin: 0 0 8px; padding-left: 18px; font-size: 13px; }
.ack-card { border-left: 3px solid var(--green-main); }
</style>
