<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { bitrix } from '@/services/bitrix'
import { compliments } from '@/services/compliments'
import { documents as documentsApi } from '@/services/documents'
import { requests, type UserOption } from '@/services/requests'
import { api, ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { ComplimentDetail, ComplimentRouteSlot } from '@/types/compliment'
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

const compliment = ref<ComplimentDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

// Маршрут строится по категории; вручную выбирают только тех, у кого роль не
// назначена. Слот исполнения показываем, но в участники не отправляем.
const route = ref<(ComplimentRouteSlot & { manual: string })[]>([])
const extras = ref<{ uid: string; after: number }[]>([])
const users = ref<UserOption[]>([])
const roleNames = ref<Record<string, string>>({})
function roleName(code: string | undefined): string {
  if (!code) return 'Доп. согласующий'
  return roleNames.value[code] || code
}

const fileInput = ref<HTMLInputElement | null>(null)
const versionInput = ref<HTMLInputElement | null>(null)
const versionDocId = ref<number | null>(null)
const editingDocId = ref<number | null>(null)
const executionComment = ref('')

const isInitiator = computed(() => compliment.value?.initiator_b24_id === auth.b24UserId)
const canSubmit = computed(
  () => isInitiator.value && ['draft', 'returned', 'rejected'].includes(compliment.value?.status || ''),
)
const canCancel = computed(
  () => isInitiator.value && ['draft', 'on_approval', 'returned', 'rejected'].includes(compliment.value?.status || ''),
)
const canDelete = computed(() => isInitiator.value && compliment.value?.status === 'canceled')
const canReturn = computed(() => isInitiator.value && compliment.value?.status === 'on_approval')

// Исполнение: заявка согласована и закреплена за мной (либо ещё ни за кем).
const isExecutor = computed(() => {
  const c = compliment.value
  if (!c) return false
  return !c.executor_b24_id || c.executor_b24_id === auth.b24UserId
})
const canTake = computed(() => compliment.value?.status === 'approved' && isExecutor.value)
const canExecute = computed(
  () => ['approved', 'in_work'].includes(compliment.value?.status || '') && isExecutor.value,
)

async function load() {
  loading.value = true
  error.value = null
  try {
    compliment.value = await compliments.get(props.id)
    if (!users.value.length) {
      try { users.value = await requests.users() } catch { /* не критично */ }
    }
    if (!Object.keys(roleNames.value).length) {
      try {
        const m = await compliments.meta()
        roleNames.value = Object.fromEntries(m.roles.map((r) => [r.code, r.name]))
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
  const { route: slots } = await compliments.routePreview(props.id)
  route.value = slots.map((s) => ({ ...s, manual: '' }))
  extras.value = []
}

const approverSlots = computed(() => route.value.filter((s) => s.role_class === 'approver'))
const executorSlot = computed(() => route.value.find((s) => s.role_class === 'executor') || null)

function addApprover() {
  const last = approverSlots.value[approverSlots.value.length - 1]
  extras.value.push({ uid: '', after: last ? last.order : -1 })
}
function removeExtra(i: number) {
  extras.value.splice(i, 1)
}

function nameByBid(bid: number | null | undefined): string {
  const u = users.value.find((x) => x.bitrix_id === bid)
  return u ? u.fio : ''
}
function onPickUser(u: UserOption) {
  if (!users.value.some((x) => x.bitrix_id === u.bitrix_id)) users.value.push(u)
}

// Согласующего могли выбрать поиском по Битриксу — его нет в матрице
// сотрудников; дотягиваем ФИО из портала, иначе будет «USER #id».
async function enrichUnknownUsers() {
  const need = new Set<number>()
  for (const r of compliment.value?.approval?.rounds || []) {
    for (const p of r.participants) {
      if (p.type === 'internal' && p.b24_user_id && !nameByBid(p.b24_user_id)) need.add(p.b24_user_id)
    }
  }
  const ex = compliment.value?.executor_b24_id
  if (ex && !nameByBid(ex)) need.add(ex)
  if (!need.size) return
  try {
    users.value = users.value.concat(await bitrix.userOptionsByIds([...need]))
  } catch { /* портал недоступен */ }
}

async function run(fn: () => Promise<ComplimentDetail>) {
  busy.value = true
  error.value = null
  try {
    compliment.value = await fn()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

// Участники = только согласующие маршрута + добавленные инициатором.
// Исполнение живёт отдельной фазой на самой заявке.
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
  for (const s of approverSlots.value) {
    const uid = s.resolved ? s.b24_user_id! : parseInt(s.manual, 10)
    if (Number.isNaN(uid)) {
      error.value = `Укажите согласующего для роли «${s.role_name}».`
      return null
    }
    list.push({ b24_user_id: uid, role: s.role_code })
    pushExtras(s.order)
    if (failed) return null
  }
  if (failed) return null

  return list.map((x, i) => ({
    type: 'internal', b24_user_id: x.b24_user_id, role: x.role, order: i,
  }))
}

// Пояснение инициатора согласующим при направлении круга (в т.ч. повторном).
const submitComment = ref('')

function submit() {
  const participants = buildParticipants()
  if (!participants) return
  run(async () => {
    const r = await compliments.submit(props.id, participants, submitComment.value.trim())
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

const { rounds, currentRound, pendingPart, myPart, myDecided, iAmParticipant, progress, history, waitingParts,
} =
  useApprovalCard(
    () => compliment.value?.approval,
    () => compliment.value?.status === 'on_approval',
    partLabel,
  )

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject', comment: string) {
  run(() => compliments.decide(props.id, p.id, decision, comment))
}

function returnForRevision() {
  const comment = window.prompt('Причина возврата на доработку:') || ''
  if (!comment.trim()) return
  run(() => compliments.returnForRevision(props.id, comment.trim()))
}
function cancelCompliment() {
  if (!confirm('Отменить заявку?')) return
  run(() => compliments.cancel(props.id))
}
async function removeCompliment() {
  if (!confirm('Удалить отменённую заявку безвозвратно?')) return
  busy.value = true
  try {
    await compliments.remove(props.id)
    router.push('/compliments')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить'
    busy.value = false
  }
}

function take() {
  run(() => compliments.take(props.id))
}
function execute() {
  run(async () => {
    const r = await compliments.execute(props.id, executionComment.value.trim())
    executionComment.value = ''
    return r
  })
}

const summaryExtras = computed(() => {
  const rows: { label: string; value: string }[] = []
  const c = compliment.value
  if (c?.taken_at) rows.push({ label: 'Взята в работу', value: fmtDateTime(c.taken_at) })
  if (c?.executed_at) rows.push({ label: 'Исполнена', value: fmtDateTime(c.executed_at) })
  if (c?.executor_b24_id) {
    rows.push({
      label: 'Исполнитель',
      value: nameByBid(c.executor_b24_id) || `USER #${c.executor_b24_id}`,
    })
  }
  return rows
})

function dl(url: string | null, name: string) {
  if (url) api.download(url, name).catch((e) => (error.value = e.message))
}
function downloadForm() {
  if (compliment.value) {
    api.download(compliments.formPdfUrl(props.id), `Заявка_${compliment.value.number}.pdf`)
      .catch((e) => (error.value = e.message))
  }
}
function downloadSheet() {
  if (compliment.value) {
    api.download(compliments.sheetPdfUrl(props.id), `Лист_согласования_${compliment.value.number}.pdf`)
      .catch((e) => (error.value = e.message))
  }
}
const hasApproval = computed(() => (compliment.value?.approval?.rounds?.length || 0) > 0)

async function uploadFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  error.value = null
  try {
    await compliments.uploadDocument(props.id, file, file.name)
    compliment.value = await compliments.get(props.id)
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
    compliment.value = await compliments.get(props.id)
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
    <RouterLink to="/compliments" class="back-link">← К заявкам на комплименты</RouterLink>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error && !compliment" class="state state--error">{{ error }}</p>

    <template v-else-if="compliment">
      <div class="detail-header-main">
        <div>
          <h1 class="detail-title">{{ compliment.number }} · {{ compliment.title }}</h1>
          <div class="detail-meta">
            {{ compliment.category_display }} · {{ compliment.company }}
            <template v-if="compliment.facility_name"> · {{ compliment.facility_name }}</template>
            · инициатор #{{ compliment.initiator_b24_id }}
          </div>
          <div v-if="compliment.needs_ceo" class="detail-meta">
            <span class="tag-chip">согласование с ГД</span>
          </div>
        </div>
        <span class="status-pill" :class="compliment.status">{{ compliment.status_display }}</span>
      </div>

      <p v-if="error" class="state state--error">{{ error }}</p>

      <!-- Суть заявки -->
      <div class="detail-card">
        <div class="detail-card-header">Заявка</div>
        <table class="round-table">
          <tbody>
            <tr><td>Категория</td><td>{{ compliment.category_display }}</td></tr>
            <tr v-if="compliment.category_details">
              <td>Что предоставляем</td>
              <td style="white-space:pre-line">{{ compliment.category_details }}</td>
            </tr>
            <tr><td>Компания</td><td>{{ compliment.company }}</td></tr>
            <tr v-if="compliment.guest_name"><td>Гость</td><td>{{ compliment.guest_name }}</td></tr>
            <tr><td>Дата и время</td><td>{{ fmtDateTime(compliment.event_at) }}</td></tr>
            <tr v-if="compliment.facility_name"><td>Отель</td><td>{{ compliment.facility_name }}</td></tr>
            <tr v-if="compliment.department"><td>Подразделение</td><td>{{ compliment.department }}</td></tr>
            <tr v-if="compliment.description">
              <td>Описание</td>
              <td style="white-space:pre-line">{{ compliment.description }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Предпросмотр маршрута + отправка -->
      <div v-if="canSubmit" class="detail-card">
        <div class="detail-card-header">Маршрут (по категории, последовательный)</div>
        <table class="round-table">
          <tbody>
            <tr v-for="s in approverSlots" :key="s.order">
              <td>{{ s.order + 1 }}. {{ s.role_name }}</td>
              <td>
                <template v-if="s.resolved">
                  {{ s.user_name || nameByBid(s.b24_user_id) || `USER #${s.b24_user_id}` }}
                </template>
                <UserSearchSelect
                  v-else v-model="s.manual" :users="users"
                  placeholder="найти согласующего…" @pick="onPickUser"
                />
              </td>
              <td>
                <span v-if="s.needs_manual" class="participant-pill" style="background:#ffe0b2">ручной выбор</span>
              </td>
            </tr>
            <!-- Исполнение показываем, чтобы был виден весь путь (требование ТЗ) -->
            <tr v-if="executorSlot">
              <td>Исполнение · {{ executorSlot.role_name }}</td>
              <td>
                {{ executorSlot.user_name || nameByBid(executorSlot.b24_user_id) || '— не назначен —' }}
              </td>
              <td><span class="participant-pill" style="background:#e0f2f1">после согласования</span></td>
            </tr>
          </tbody>
        </table>

        <div class="extras">
          <div class="extras-title">Дополнительные согласующие</div>
          <div v-for="(e, i) in extras" :key="i" class="extra-row">
            <div class="extra-select">
              <UserSearchSelect v-model="e.uid" :users="users"
                                placeholder="найти сотрудника…" @pick="onPickUser" />
            </div>
            <label class="extra-after">
              вставить
              <select v-model.number="e.after">
                <option :value="-1">в начале</option>
                <option v-for="s in approverSlots" :key="s.order" :value="s.order">
                  после «{{ s.role_name }}»
                </option>
              </select>
            </label>
            <button type="button" class="extra-x" title="Убрать" @click="removeExtra(i)">×</button>
          </div>
          <button type="button" class="btn btn--ghost" style="font-size:13px" @click="addApprover">
            ＋ Добавить согласующего
          </button>
        </div>

        <!-- Пояснение согласующим: с чем направляем круг (что изменилось
             после доработки). Необязательное — перезапуск в один клик сохранён. -->
        <div style="margin-top:12px">
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

        <div style="margin-top:12px">
          <button class="btn btn--primary" :disabled="busy" @click="submit">
            {{ compliment.status === 'rejected' ? 'Перезапустить согласование (новый круг)' : 'Отправить на согласование' }}
          </button>
        </div>
      </div>

      <!-- Управление -->
      <div v-if="canCancel || canDelete || canReturn" class="detail-card">
        <div class="detail-card-header">Управление</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button v-if="canReturn" class="btn btn--soft" :disabled="busy" @click="returnForRevision">Вернуть на доработку</button>
          <button v-if="canCancel" class="btn btn--soft" :disabled="busy" @click="cancelCompliment">Отменить заявку</button>
          <button v-if="canDelete" class="btn btn--danger" :disabled="busy" @click="removeCompliment">Удалить заявку</button>
        </div>
        <div class="detail-meta" style="margin-top:6px">
          Отменить можно только до согласования: судьба согласованной заявки не меняется.
        </div>
      </div>

      <!-- Исполнение -->
      <div v-if="canTake || canExecute || compliment.status === 'executed'" class="detail-card">
        <div class="detail-card-header">Исполнение</div>
        <template v-if="compliment.status === 'executed'">
          <div>Исполнена {{ fmtDateTime(compliment.executed_at) }}</div>
          <div v-if="compliment.execution_comment" class="detail-meta" style="margin-top:4px">
            {{ compliment.execution_comment }}
          </div>
        </template>
        <template v-else>
          <div class="detail-meta" style="margin-bottom:8px">
            Заявка согласована. Возьмите её в работу и отметьте выдачу комплимента.
          </div>
          <input
            v-model="executionComment" type="text" class="exec-comment"
            placeholder="Комментарий исполнителя (необязательно)"
          />
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
            <button v-if="canTake" class="btn btn--soft" :disabled="busy" @click="take">Взять в работу</button>
            <button v-if="canExecute" class="btn btn--primary" :disabled="busy" @click="execute">Исполнена</button>
          </div>
        </template>
      </div>

      <!-- Документы на выходе -->
      <div class="detail-card">
        <div class="detail-card-header">Документы заявки</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn--soft" :disabled="busy" @click="downloadForm">
            Скачать заявку {{ hasApproval ? 'с листом согласования ' : '' }}(PDF)
          </button>
          <button v-if="hasApproval" class="btn btn--ghost" :disabled="busy" @click="downloadSheet">
            Только лист согласования (PDF)
          </button>
        </div>
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
        :created-at="compliment.created_at"
        :submitted-at="compliment.approval?.submitted_at"
        :completed-at="compliment.approval?.completed_at"
        :extra-rows="summaryExtras"
      />

      <DocumentsCard
        :docs="compliment.documents" :busy="busy"
        @download="dl" @upload="fileInput?.click()"
        @add-version="pickVersion" @edit="(id) => (editingDocId = id)"
      />
      <input ref="fileInput" type="file" style="display:none" @change="uploadFile" />
      <input ref="versionInput" type="file" style="display:none" @change="uploadVersion" />
    </template>

    <!-- Оверлей онлайн-редактора -->
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
  border-radius: 6px; font: inherit; font-size: 13px;
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
</style>
