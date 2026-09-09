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
import { isGroupLegal, useApprovalCard } from '@/composables/useApprovalCard'
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

const contract = ref<ContractDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

// Слот маршрута + выбранный вручную согласующий (manual) и признак замены
// автоподобранного (replacing).
type RouteRow = ContractRouteSlot & { manual: string; replacing: boolean }
const route = ref<RouteRow[]>([])
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

const isInitiator = computed(() => contract.value?.initiator_b24_id === auth.b24UserId)
const canSubmit = computed(
  () => isInitiator.value && ['draft', 'returned', 'rejected'].includes(contract.value?.status || ''),
)
const canCancel = computed(
  () => isInitiator.value && ['draft', 'on_approval', 'returned', 'rejected'].includes(contract.value?.status || ''),
)
const canDelete = computed(() => isInitiator.value && contract.value?.status === 'canceled')
const canReturn = computed(() => isInitiator.value && contract.value?.status === 'on_approval')
// Править карточку можно там же, где отправлять: черновик, возвращённый и
// отклонённый (contracts EDITABLE_STATUSES).
const canEdit = canSubmit

// Замена согласующего, подобранного матрицей ролей (руководитель в отпуске,
// назначение устарело). Явным действием — случайный клик не должен молча
// переписать маршрут.
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
  route.value = slots.map((s) => ({ ...s, manual: '', replacing: false }))
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
      const uid = s.resolved && !s.replacing ? s.b24_user_id! : parseInt(s.manual, 10)
      if (Number.isNaN(uid)) {
        error.value = s.replacing
          ? `Выберите, кем заменить согласующего в роли «${s.role_name}».`
          : `Укажите согласующего для роли «${s.role_name}».`
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

// Пояснение инициатора согласующим при направлении круга (в т.ч. повторном).
const submitComment = ref('')

function submit() {
  const participants = buildParticipants()
  if (!participants) return
  run(async () => {
    const r = await contracts.submit(props.id, participants, submitComment.value.trim())
    route.value = []
    extras.value = []
    submitComment.value = ''
    return r
  })
}

// Как участник подписан в кругах/истории.
function partLabel(p: ApprovalParticipant): string {
  if (isGroupLegal(p)) return 'Юридический отдел'
  if (p.type === 'external') return p.email || p.name || 'внешний участник'
  return nameByBid(p.b24_user_id) || `USER #${p.b24_user_id}`
}

// Общая логика карточки согласования (та же у заявок и будущих модулей).
const { rounds, currentRound, pendingPart, myPart, myDecided, iAmParticipant, progress, history, waitingParts,
} =
  useApprovalCard(
    () => contract.value?.approval,
    () => contract.value?.status === 'on_approval',
    partLabel,
  )

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject', comment: string) {
  run(() => contracts.decide(props.id, p.id, decision, comment))
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
            {{ contract.status === 'rejected' ? 'Перезапустить согласование (новый круг)' : 'Отправить на согласование' }}
          </button>
        </div>
      </div>

      <!-- Управление -->
      <div v-if="canCancel || canDelete || canReturn || canEdit" class="detail-card">
        <div class="detail-card-header">Управление</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <RouterLink v-if="canEdit" :to="`/contracts/${contract.id}/edit`" class="btn btn--primary">
            Редактировать договор
          </RouterLink>
          <button v-if="canReturn" class="btn btn--soft" :disabled="busy" @click="returnForRevision">Вернуть на доработку</button>
          <button v-if="canCancel" class="btn btn--soft" :disabled="busy" @click="cancelContract">Отменить договор</button>
          <button v-if="canDelete" class="btn btn--danger" :disabled="busy" @click="removeContract">Удалить договор</button>
        </div>
        <div v-if="canReturn" class="detail-meta" style="margin-top:6px">
          Возврат снимает договор с текущего круга — после правок его можно отправить заново.
        </div>
        <div v-else-if="canEdit" class="detail-meta" style="margin-top:6px">
          Карточка открыта для правки, пока договор не на согласовании. После
          правок отправьте его на согласование заново.
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
        :created-at="contract.created_at"
        :submitted-at="contract.approval?.submitted_at"
        :completed-at="contract.approval?.completed_at"
      />

      <DocumentsCard
        :docs="contract.documents" :busy="busy"
        hint="Правки: скачайте версию, измените локально и загрузите как «новую версию» — старая останется в истории. Файлы Word/Excel можно править прямо в браузере."
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
.link-btn {
  background: none; border: none; padding: 0; margin-left: 8px;
  color: var(--green-main); cursor: pointer; font: inherit; font-size: 12px;
  text-decoration: underline;
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
