<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { bitrix } from '@/services/bitrix'
import { contracts, type UserOption } from '@/services/contracts'
import { documents as documentsApi } from '@/services/documents'
import { api, ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { ContractDetail, ContractRouteSlot } from '@/types/contract'
import type { ApprovalParticipant, ParticipantInput } from '@/types/approval'
import DocumentEditor from '@/components/DocumentEditor.vue'
import UserSearchSelect from '@/components/UserSearchSelect.vue'

const props = defineProps<{ id: string }>()
const auth = useAuthStore()
const router = useRouter()

const DECISION_RU: Record<string, string> = {
  waiting: 'Ожидает', approved: 'Согласовано', rejected: 'Отклонено',
}
const RESULT_RU: Record<string, string> = {
  pending: 'В процессе', approved: 'Согласован', rejected: 'Отклонён', returned: 'Возвращён',
}

const contract = ref<ContractDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

const route = ref<(ContractRouteSlot & { manual: string })[]>([])
// Дополнительные согласующие, добавленные инициатором вручную (напр. главбух).
// after — order авто-этапа, ПОСЛЕ которого вставить (или -1 = в самом начале).
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
// Комментарий к моему решению (при отклонении обязателен) — как в светофоре.
const decisionComment = ref('')

const isInitiator = computed(() => contract.value?.initiator_b24_id === auth.b24UserId)
const canSubmit = computed(
  () => isInitiator.value && ['draft', 'returned', 'rejected'].includes(contract.value?.status || ''),
)
const canCancel = computed(
  () => isInitiator.value && ['draft', 'on_approval', 'returned', 'rejected'].includes(contract.value?.status || ''),
)
const canDelete = computed(() => isInitiator.value && contract.value?.status === 'canceled')
const canReturn = computed(() => isInitiator.value && contract.value?.status === 'on_approval')

async function load() {
  loading.value = true
  error.value = null
  try {
    contract.value = await contracts.get(props.id)
    if (!users.value.length) {
      try { users.value = await contracts.users() } catch { /* не критично */ }
    }
    if (!Object.keys(roleNames.value).length) {
      try {
        const m = await contracts.meta()
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
  const { route: slots } = await contracts.routePreview(props.id)
  route.value = slots.map((s) => ({ ...s, manual: '' }))
  extras.value = []
}

// Добавить своего согласующего (по умолчанию — в конец маршрута).
function addApprover() {
  const lastOrder = route.value.length ? route.value[route.value.length - 1].order : -1
  extras.value.push({ uid: '', after: lastOrder })
}
function removeExtra(i: number) {
  extras.value.splice(i, 1)
}

function nameByBid(bid: number | null | undefined): string {
  const u = users.value.find((x) => x.bitrix_id === bid)
  return u ? u.fio : ''
}

// Выбрали сотрудника в поиске — добавим его в локальный список имён, чтобы
// потом (в кругах согласования) он резолвился в ФИО, а не «USER #id».
function onPickUser(u: UserOption) {
  if (!users.value.some((x) => x.bitrix_id === u.bitrix_id)) users.value.push(u)
}

// Согласующего могли выбрать поиском по Битриксу — тогда его нет в матрице
// сотрудников (/core/users/) и после перезагрузки страницы он выглядел бы как
// «USER #id». Дотягиваем ФИО из портала. Вне Битрикса — тихий no-op.
async function enrichUnknownUsers() {
  const need = new Set<number>()
  for (const r of contract.value?.approval?.rounds || []) {
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

async function run(fn: () => Promise<ContractDetail>) {
  busy.value = true
  error.value = null
  try {
    contract.value = await fn()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

// Собирает участников в ИТОГОВОМ порядке: авто-этапы маршрута + вставленные
// инициатором доп. согласующие (после выбранного этапа). Возвращает null и
// выставляет error при незаполненных данных.
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

  pushExtras(-1) // добавленные «в начале»
  for (const s of route.value) {
    if (s.group) {
      list.push({ b24_user_id: null, role: s.role_code })
    } else {
      const uid = s.resolved ? s.b24_user_id! : parseInt(s.manual, 10)
      if (Number.isNaN(uid)) {
        error.value = `Укажите согласующего для роли «${s.role_name}».`
        return null
      }
      list.push({ b24_user_id: uid, role: s.role_code })
    }
    pushExtras(s.order) // добавленные после этого этапа
    if (failed) return null
  }
  if (failed) return null

  return list.map((x, i) => ({
    type: 'internal', b24_user_id: x.b24_user_id, role: x.role, order: i,
  }))
}

function submit() {
  const participants = buildParticipants()
  if (!participants) return
  run(async () => {
    const r = await contracts.submit(props.id, participants)
    route.value = []
    extras.value = []
    return r
  })
}

function isGroupLegal(p: ApprovalParticipant): boolean {
  return p.role === 'legal_dept' && !p.b24_user_id
}
// Как участник подписан в кругах/истории.
function partLabel(p: ApprovalParticipant): string {
  if (isGroupLegal(p)) return 'Юридический отдел'
  if (p.type === 'external') return p.email || p.name || 'внешний участник'
  return nameByBid(p.b24_user_id) || `USER #${p.b24_user_id}`
}

const rounds = computed(() => contract.value?.approval?.rounds || [])
const currentRound = computed(() => rounds.value[rounds.value.length - 1] || null)

// Маршрут строго последовательный: решает первый ожидающий в текущем круге
// (движок это же и проверяет — см. approvalflow.services._is_turn).
const pendingPart = computed<ApprovalParticipant | null>(() => {
  if (contract.value?.status !== 'on_approval' || !currentRound.value) return null
  return [...currentRound.value.participants]
    .sort((a, b) => a.order - b.order)
    .find((p) => p.decision === 'waiting') || null
})

function isMine(p: ApprovalParticipant): boolean {
  if (p.type !== 'internal') return false
  return isGroupLegal(p) ? auth.isLawyer : p.b24_user_id === auth.b24UserId
}
// Моё решение сейчас ждут (кнопки «Согласовать/Отклонить»).
const myPart = computed(() => (pendingPart.value && isMine(pendingPart.value) ? pendingPart.value : null))
// Моё уже принятое решение в текущем круге (чтобы показать его в карточке).
const myDecided = computed(
  () => currentRound.value?.participants.find((p) => isMine(p) && p.decision !== 'waiting') || null,
)
// Я вообще участник этого договора?
const iAmParticipant = computed(() => rounds.value.some((r) => r.participants.some(isMine)))

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject') {
  const comment = decisionComment.value.trim()
  if (decision === 'reject' && !comment) {
    error.value = 'При отклонении комментарий обязателен.'
    return
  }
  run(async () => {
    const r = await contracts.decide(props.id, p.id, decision, comment)
    decisionComment.value = ''
    return r
  })
}

// --- сводка по текущему кругу ---
const progress = computed(() => {
  const parts = currentRound.value?.participants || []
  return { done: parts.filter((p) => p.decision !== 'waiting').length, total: parts.length }
})

// --- история согласования (лента по кругам) ---
interface HistoryEvent {
  key: string
  when: string
  who: string
  what: string
  ok: boolean | null
  comment: string
}
const history = computed(() =>
  rounds.value.map((rnd) => {
    const events: HistoryEvent[] = rnd.participants
      .filter((p) => p.decided_at)
      .map((p) => ({
        key: `p${p.id}`,
        when: p.decided_at as string,
        who: partLabel(p),
        what: p.decision === 'approved' ? 'согласовал(а)' : 'отклонил(а)',
        ok: p.decision === 'approved',
        comment: p.decision_comment,
      }))
      .sort((a, b) => a.when.localeCompare(b.when))
    if (rnd.result === 'returned' && rnd.completed_at) {
      events.push({
        key: `r${rnd.id}`, when: rnd.completed_at, who: 'Инициатор',
        what: 'вернул(а) на доработку', ok: null, comment: rnd.comment,
      })
    }
    return { round: rnd.round_number, result: rnd.result, started_at: rnd.started_at, events }
  }),
)

function fmt(dt: string | null | undefined): string {
  return dt ? new Date(dt).toLocaleString('ru') : '—'
}

function cancelContract() {
  if (!confirm('Отменить договор?')) return
  run(() => contracts.cancel(props.id))
}
// Инициатор может отозвать договор с круга и доработать (потом — новый круг).
function returnForRevision() {
  const comment = window.prompt('Причина возврата на доработку:') || ''
  if (!comment.trim()) return
  run(() => contracts.returnForRevision(props.id, comment.trim()))
}
async function removeContract() {
  if (!confirm('Удалить отменённый договор безвозвратно?')) return
  busy.value = true
  try {
    await contracts.remove(props.id)
    router.push('/contracts')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить'
    busy.value = false
  }
}

function dl(url: string | null, name: string) {
  if (url) api.download(url, name).catch((e) => (error.value = e.message))
}
function downloadSheet() {
  if (contract.value) api.download(contracts.sheetPdfUrl(props.id), `Лист_согласования_${contract.value.number}.pdf`)
    .catch((e) => (error.value = e.message))
}
// лист согласования доступен, когда есть хотя бы один круг (как у заявок)
const hasApproval = computed(() => (contract.value?.approval?.rounds?.length || 0) > 0)
async function uploadFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  error.value = null
  try {
    await contracts.uploadDocument(props.id, file, file.name)
    contract.value = await contracts.get(props.id)
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
    contract.value = await contracts.get(props.id)
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

function money(v: string | null): string {
  if (!v) return ''
  const n = Number(v)
  return Number.isNaN(n) ? '' : n.toLocaleString('ru-RU') + ' ₽'
}

onMounted(load)
</script>

<template>
  <section>
    <RouterLink to="/contracts" class="back-link">← К договорам</RouterLink>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error && !contract" class="state state--error">{{ error }}</p>

    <template v-else-if="contract">
      <div class="detail-header-main">
        <div>
          <h1 class="detail-title">{{ contract.number }} · {{ contract.title }}</h1>
          <div class="detail-meta">
            {{ contract.organization_name }}
            <template v-if="contract.cfo_name"> · {{ contract.cfo_name }}</template>
            <template v-if="contract.amount"> · {{ money(contract.amount) }}</template>
            · инициатор #{{ contract.initiator_b24_id }}
          </div>
          <div class="detail-meta" v-if="contract.is_nonstandard || contract.has_disagreement_protocol">
            <span v-if="contract.is_nonstandard" class="tag-chip">нестандартный</span>
            <span v-if="contract.has_disagreement_protocol" class="tag-chip">протокол разногласий</span>
          </div>
          <div class="detail-meta" v-if="contract.crm_link">
            CRM:
            <a :href="contract.crm_link" target="_blank" rel="noopener"
               style="color:#1976d2;word-break:break-all">{{ contract.crm_link }}</a>
          </div>
        </div>
        <span class="status-pill" :class="contract.status">{{ contract.status_display }}</span>
      </div>

      <p v-if="error" class="state state--error">{{ error }}</p>

      <!-- Описание (комментарий инициатора при создании) -->
      <div v-if="contract.comment" class="detail-card">
        <div class="detail-card-header">Описание</div>
        <div style="white-space:pre-line">{{ contract.comment }}</div>
      </div>

      <!-- Предпросмотр маршрута + отправка -->
      <div v-if="canSubmit" class="detail-card">
        <div class="detail-card-header">Маршрут согласования (авто, последовательный)</div>
        <table class="round-table">
          <tbody>
            <tr v-for="s in route" :key="s.order">
              <td>
                {{ s.order + 1 }}. {{ s.role_name }}
                <span class="ag-muted" style="font-size:12px"> · {{ s.role_class === 'signer' ? 'подписант' : 'согласующий' }}</span>
              </td>
              <td>
                <template v-if="s.group">Юридический отдел (любой юрист)</template>
                <template v-else-if="s.resolved">
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
          </tbody>
        </table>

        <!-- Дополнительные согласующие (добавляет инициатор) -->
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
                <option v-for="s in route" :key="s.order" :value="s.order">
                  после «{{ s.role_name }}»
                </option>
              </select>
            </label>
            <button type="button" class="extra-x" @click="removeExtra(i)" title="Убрать">×</button>
          </div>
          <button type="button" class="btn btn--ghost" style="font-size:13px" @click="addApprover">
            ＋ Добавить согласующего
          </button>
        </div>

        <div style="margin-top:12px">
          <button class="btn btn--primary" :disabled="busy" @click="submit">
            {{ contract.status === 'rejected' ? 'Перезапустить согласование (новый круг)' : 'Отправить на согласование' }}
          </button>
        </div>
      </div>

      <!-- Управление -->
      <div v-if="canCancel || canDelete || canReturn" class="detail-card">
        <div class="detail-card-header">Управление</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button v-if="canReturn" class="btn btn--soft" :disabled="busy" @click="returnForRevision">Вернуть на доработку</button>
          <button v-if="canCancel" class="btn btn--soft" :disabled="busy" @click="cancelContract">Отменить договор</button>
          <button v-if="canDelete" class="btn btn--danger" :disabled="busy" @click="removeContract">Удалить договор</button>
        </div>
        <div v-if="canReturn" class="detail-meta" style="margin-top:6px">
          Возврат снимает договор с текущего круга — после правок его можно отправить заново.
        </div>
      </div>

      <!-- Лист согласования (PDF) -->
      <div v-if="hasApproval" class="detail-card">
        <div class="detail-card-header">Лист согласования</div>
        <button class="btn btn--soft" :disabled="busy" @click="downloadSheet">Скачать лист согласования (PDF)</button>
      </div>

      <!-- Ваше решение -->
      <div v-if="myPart || myDecided || iAmParticipant" class="detail-card">
        <div class="detail-card-header">Ваше решение</div>
        <template v-if="myPart">
          <div class="detail-meta" style="margin-bottom:6px">
            Сейчас очередь за вами<template v-if="myPart.role"> — как «{{ roleName(myPart.role) }}»</template>.
          </div>
          <textarea
            v-model="decisionComment" rows="3" class="decision-comment"
            placeholder="Комментарий (при отклонении обязателен)"
          ></textarea>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
            <button class="btn btn--primary" :disabled="busy" @click="decide(myPart, 'approve')">Согласовать</button>
            <button class="btn btn--danger" :disabled="busy" @click="decide(myPart, 'reject')">Отклонить</button>
          </div>
        </template>
        <template v-else-if="myDecided">
          <div>
            Ваше решение:
            <span class="participant-pill" :class="myDecided.decision">
              {{ DECISION_RU[myDecided.decision] || myDecided.decision }}
            </span>
            <span class="detail-meta"> · {{ fmt(myDecided.decided_at) }}</span>
          </div>
          <div v-if="myDecided.decision_comment" class="detail-meta" style="margin-top:4px">
            {{ myDecided.decision_comment }}
          </div>
        </template>
        <div v-else class="detail-meta">
          <template v-if="pendingPart">Ждём решения: {{ partLabel(pendingPart) }}.</template>
          <template v-else>Ваше решение сейчас не требуется.</template>
        </div>
      </div>

      <!-- Круги согласования -->
      <div v-for="rnd in rounds" :key="rnd.id" class="detail-card">
        <div class="detail-card-header">
          Круг {{ rnd.round_number }}
          <span class="participant-pill" :class="rnd.result">{{ RESULT_RU[rnd.result] || rnd.result }}</span>
        </div>
        <table class="round-table">
          <tbody>
            <tr v-for="p in rnd.participants" :key="p.id">
              <td>{{ roleName(p.role) }}</td>
              <td>
                {{ partLabel(p) }}
                <span v-if="pendingPart && pendingPart.id === p.id" class="participant-pill" style="background:#fff3cd">сейчас решает</span>
              </td>
              <td>
                <span class="participant-pill" :class="p.decision">{{ DECISION_RU[p.decision] || p.decision }}</span>
                <span v-if="p.decided_at" class="detail-meta"> · {{ fmt(p.decided_at) }}</span>
                <em v-if="p.decision_comment"> — {{ p.decision_comment }}</em>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- История согласования -->
      <div v-if="rounds.length" class="detail-card">
        <div class="detail-card-header">История согласования</div>
        <div v-for="grp in history" :key="grp.round" style="margin-bottom:10px">
          <div style="font-weight:600;font-size:12px;margin-bottom:4px">
            Круг {{ grp.round }} · отправлен {{ fmt(grp.started_at) }}
            <span class="participant-pill" :class="grp.result">{{ RESULT_RU[grp.result] || grp.result }}</span>
          </div>
          <p v-if="!grp.events.length" class="detail-meta" style="margin:0">Решений пока нет.</p>
          <div v-for="ev in grp.events" :key="ev.key" class="log-item">
            <b>{{ ev.who }}</b>
            <span :style="{ color: ev.ok === null ? 'inherit' : ev.ok ? 'var(--green-main)' : 'var(--red-main)' }">
              {{ ev.what }}</span>
            · {{ fmt(ev.when) }}
            <div v-if="ev.comment" class="detail-meta">{{ ev.comment }}</div>
          </div>
        </div>
      </div>

      <!-- Сводка -->
      <div v-if="rounds.length" class="detail-card">
        <div class="detail-card-header">Сводка</div>
        <table class="round-table">
          <tbody>
            <tr><td>Круг</td><td>{{ currentRound?.round_number }} · согласовали {{ progress.done }} из {{ progress.total }}</td></tr>
            <tr><td>Сейчас решает</td><td>{{ pendingPart ? partLabel(pendingPart) : '—' }}</td></tr>
            <tr><td>Создан</td><td>{{ fmt(contract.created_at) }}</td></tr>
            <tr><td>Отправлен</td><td>{{ fmt(contract.approval?.submitted_at) }}</td></tr>
            <tr><td>Завершён</td><td>{{ fmt(contract.approval?.completed_at) }}</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Документы (с историей версий, как в карточке согласования) -->
      <div class="detail-card">
        <div class="detail-card-header">Документы</div>
        <div v-for="d in contract.documents" :key="d.id" class="doc-item">
          <div class="doc-name">
            {{ d.title }}
            <span class="detail-meta">· актуальная v{{ d.current_version_number }}</span>
          </div>
          <div class="doc-actions">
            <a
              v-for="v in d.versions" :key="v.id" href="#" class="doc-link" :title="v.change_comment"
              @click.prevent="dl(v.download_url, `${d.title} v${v.version_number}`)"
            >v{{ v.version_number }}{{ v.is_current ? ' ✓' : '' }}</a>
            <button type="button" class="doc-link doc-linkbtn" :disabled="busy" @click="pickVersion(d.id)">
              ＋ новая версия
            </button>
            <button
              v-if="d.can_edit_online" type="button" class="doc-link doc-linkbtn"
              @click="editingDocId = d.id"
            >✏️ Редактировать онлайн</button>
          </div>
          <template v-for="v in d.versions" :key="'c' + v.id">
            <div v-if="v.change_comment" class="detail-meta">v{{ v.version_number }}: {{ v.change_comment }}</div>
          </template>
        </div>
        <p v-if="!contract.documents.length" class="muted" style="margin:0 0 8px">Файлов пока нет.</p>
        <input ref="fileInput" type="file" style="display:none" @change="uploadFile" />
        <input ref="versionInput" type="file" style="display:none" @change="uploadVersion" />
        <button class="btn btn--ghost" :disabled="busy" @click="fileInput?.click()">Прикрепить документ</button>
        <div v-if="contract.documents.length" class="detail-meta" style="margin-top:6px">
          Правки: скачайте версию, измените локально и загрузите как «новую версию» — старая
          останется в истории. Файлы Word/Excel можно править прямо в браузере.
        </div>
      </div>
    </template>

    <!-- Оверлей онлайн-редактора -->
    <DocumentEditor v-if="editingDocId" :doc-id="editingDocId" @close="onEditorClose" />
  </section>
</template>

<style scoped>
/* Документы с версиями и лента истории — визуально как в карточке согласования. */
.doc-item { background: #fff; border-radius: 8px; border: 1px solid #e0e0e0; padding: 8px 10px; margin-bottom: 8px; }
.doc-name { font-size: 14px; font-weight: 500; margin-bottom: 4px; overflow-wrap: anywhere; word-break: break-word; }
.doc-actions { font-size: 12px; display: flex; gap: 14px; flex-wrap: wrap; }
.doc-link { color: var(--green-main); text-decoration: none; cursor: pointer; }
.doc-link:hover { text-decoration: underline; }
.doc-linkbtn { border: none; background: transparent; padding: 0; cursor: pointer; color: var(--green-main); font: inherit; font-size: 12px; }
.doc-linkbtn:hover { text-decoration: underline; }
.doc-linkbtn:disabled { opacity: 0.5; cursor: default; text-decoration: none; }

.log-item { font-size: 12px; margin-bottom: 8px; }
.decision-comment {
  width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #d0d0d0;
  border-radius: 6px; font: inherit; font-size: 13px; resize: vertical;
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
