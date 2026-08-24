<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { agreements } from '@/services/agreements'
import { requests } from '@/services/requests'
import { contracts } from '@/services/contracts'
import { compliments } from '@/services/compliments'
import type { ContractListItem } from '@/types/contract'
import type { ComplimentListItem } from '@/types/compliment'
import { bitrix, type BitrixUser, type BitrixDeal } from '@/services/bitrix'
import BitrixSearchModal from '@/components/BitrixSearchModal.vue'
import DocumentEditor from '@/components/DocumentEditor.vue'
import { api, ApiError } from '@/services/api'
import { versionFileName } from '@/utils/filename'
import { useAuthStore } from '@/stores/auth'
import { useSvetoforStore, type SvetoforMode as Mode } from '@/stores/svetofor'
import {
  type Agreement, type AgParticipant, type AgreementTemplate, type DecisionLog,
  AG_STATUS_LABEL,
} from '@/types/agreement'
import type { RegulatoryRequestListItem } from '@/types/request'

const auth = useAuthStore()

// Режим вкладок живёт в сторе — кнопки перенесены в сайдбар (App.vue).
const svet = useSvetoforStore()
const mode = computed(() => svet.mode)

const items = ref<Agreement[]>([])
// Регламентные заявки, ждущие моего решения (показываем во вкладке «Требует действия»).
const requestTodo = ref<RegulatoryRequestListItem[]>([])
// Договоры, ждущие моего решения (та же вкладка «Требует действия»).
const contractTodo = ref<ContractListItem[]>([])
// Заявки на комплименты, ждущие моего решения.
const complimentTodo = ref<ComplimentListItem[]>([])
const templates = ref<AgreementTemplate[]>([])
const selected = ref<Agreement | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const busy = ref(false)

const uid = computed(() => auth.b24UserId)

// Справочник b24_id → ФИО/должность (как в старом миниседе показываем имена).
// Наполняется из /api/core/users/ и из данных BX24 при выборе сотрудников.
const userDir = ref<Record<number, { fio: string; position?: string }>>({})
// домен портала — для сборки полной ссылки на сделку при выборе через коннектор
const portalDomain = ref('')
async function loadUserDir() {
  try {
    for (const u of await requests.users()) {
      userDir.value[u.bitrix_id] = { fio: u.fio, position: u.position_name || '' }
    }
  } catch { /* не критично */ }
  try { portalDomain.value = (await bitrix.status()).domain || '' } catch { /* не критично */ }
}
function udName(id: number | null | undefined): string {
  return (id != null && userDir.value[id]?.fio) || (id != null ? `USER #${id}` : '')
}
function udPos(id: number | null | undefined): string {
  return (id != null && userDir.value[id]?.position) || ''
}
function udInitials(id: number | null | undefined): string {
  const known = id != null && userDir.value[id]?.fio
  if (!known) return 'U#'
  const parts = known.trim().split(/\s+/).filter(Boolean)
  const s = parts.length >= 2 ? parts[0][0] + parts[1][0] : known.trim().slice(0, 2)
  return s.toUpperCase()
}
// Дозагрузка ФИО/должности из Битрикса для id, которых нет в справочнике
// (реальные сотрудники портала, не заведённые в профилях). Вне Битрикса — no-op.
async function enrichUsers(ids: (number | null | undefined)[]) {
  const need = [...new Set(ids.filter((x): x is number => x != null && userDir.value[x] === undefined))]
  if (!need.length) return
  try {
    const { results } = await bitrix.usersByIds(need)
    for (const u of results) {
      const id = Number(u.ID)
      if (Number.isNaN(id)) continue
      const fio = [u.LAST_NAME, u.NAME, u.SECOND_NAME].filter(Boolean).join(' ') || `USER #${id}`
      userDir.value[id] = { fio, position: u.WORK_POSITION || '' }
    }
  } catch { /* вне Битрикса недоступно */ }
}

// Статусные вкладки — архив по статусу (в работе / отклонённые / завершённые)
// по ВСЕМ доступным мне согласованиям: не только созданным мной, но и тем, где
// я согласующий. Иначе завершённое согласование, где я был участником, не
// попадало никуда, кроме вкладки «Все».
const STATUS_BY_MODE: Partial<Record<Mode, string>> = {
  in_progress: 'in_progress',
  rejected: 'rejected',
  completed: 'completed',
}

async function fetchByMode(m: Mode): Promise<Agreement[]> {
  if (m === 'todo') return agreements.todo()
  const statusFilter = STATUS_BY_MODE[m]
  if (statusFilter) return agreements.all(statusFilter)
  return agreements.all()
}

async function loadList() {
  loading.value = true
  error.value = null
  selected.value = null
  try {
    if (mode.value === 'templates') {
      templates.value = await agreements.templates()
    } else {
      items.value = await fetchByMode(mode.value)
      // подтянуть имена авторов/участников списка
      enrichUsers(items.value.flatMap((a) => [a.author_b24_id, ...a.participants.map((p) => p.b24_user_id)]))
      // заявки и договоры, ждущие моего решения — только во вкладке «Требует действия»
      requestTodo.value = mode.value === 'todo' ? await requests.todo().catch(() => []) : []
      contractTodo.value = mode.value === 'todo' ? await contracts.todo().catch(() => []) : []
      complimentTodo.value = mode.value === 'todo' ? await compliments.todo().catch(() => []) : []
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка загрузки'
  } finally {
    loading.value = false
  }
}

function setMode(m: Mode) {
  svet.mode = m
}
// Смена вкладки (в т.ч. из сайдбара) перезагружает список.
watch(() => svet.mode, loadList)

// Счётчики бейджей в сайдбаре: «требует действия» (по всем модулям) +
// непросмотренные отклонённые/завершённые (мои согласования). Обновляем всегда —
// бейджи видны независимо от активной вкладки.
async function refreshBadges() {
  const [ag, rq, ct, cm, counts] = await Promise.all([
    agreements.todo().catch(() => []),
    requests.todo().catch(() => []),
    contracts.todo().catch(() => []),
    compliments.todo().catch(() => []),
    agreements.badgeCounts().catch(() => ({ rejected_unseen: 0, completed_unseen: 0, in_progress: 0 })),
  ])
  svet.todoCount = ag.length + rq.length + ct.length + cm.length
  svet.rejectedUnseen = counts.rejected_unseen
  svet.completedUnseen = counts.completed_unseen
}

const decisionComment = ref('')
async function open(id: number) {
  decisionComment.value = ''
  try {
    const ag = await agreements.get(id)
    selected.value = ag
    enrichUsers([ag.author_b24_id, ...ag.participants.map((p) => p.b24_user_id)])
    // отметить просмотренным → сбросить «непросмотрено» и обновить бейджи
    agreements.markSeen(id).then(() => refreshBadges()).catch(() => {})
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось открыть'
  }
}

async function reloadSelected() {
  if (selected.value) await open(selected.value.id)
  if (mode.value !== 'templates') items.value = await fetchByMode(mode.value)
}

// --- решения ---
async function decide(p: AgParticipant, decision: 'approve' | 'reject') {
  const comment = decisionComment.value.trim()
  if (decision === 'reject' && !comment) {
    error.value = 'Комментарий обязателен при отклонении.'
    return
  }
  await run(() => agreements.decide(selected.value!.id, p.id, decision, comment))
  decisionComment.value = ''
  void refreshBadges()
}

// участники ТЕКУЩЕГО круга (ТЗ п.7.4)
const currentParts = computed(() =>
  selected.value ? selected.value.participants.filter((p) => p.round_number === selected.value!.current_round) : [],
)
// решение текущего пользователя (для блока «Ваше решение»).
// Матчим и внутреннего (по b24_id), и внешнего участника (по почте профиля) —
// иначе при отправке себе на email действие было недоступно.
const myPart = computed(() => {
  const myEmail = auth.profile?.email?.toLowerCase()
  return currentParts.value.find(
    (p) =>
      (p.type === 'internal' && p.b24_user_id === uid.value) ||
      (p.type === 'external' && !!myEmail && p.email?.toLowerCase() === myEmail),
  ) ?? null
})
// история по кругам (ТЗ п.7.4)
const roundsHistory = computed(() => {
  if (!selected.value) return []
  const byRound = new Map<number, DecisionLog[]>()
  for (const log of selected.value.decision_logs) {
    if (!byRound.has(log.round_number)) byRound.set(log.round_number, [])
    byRound.get(log.round_number)!.push(log)
  }
  return [...byRound.entries()].sort((a, b) => a[0] - b[0]).map(([round, logs]) => ({ round, logs }))
})
// маршрут текущего круга можно менять, пока никто не принял решение
const noneDecided = computed(() => currentParts.value.length > 0 && currentParts.value.every((p) => p.status === 'waiting'))

async function run(fn: () => Promise<unknown>) {
  busy.value = true
  error.value = null
  try {
    await fn()
    await reloadSelected()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}


// --- маршрут: смена согласующих (#6) и повторное согласование (#5) ---
const routeEdit = ref(false)
const routeInternal = ref('')
const routeExternal = ref<string[]>([])
const routeExtInput = ref('')
function openRouteEditor() {
  routeInternal.value = currentParts.value.filter((p) => p.type === 'internal').map((p) => p.b24_user_id).join(', ')
  routeExternal.value = currentParts.value.filter((p) => p.type === 'external').map((p) => p.email)
  routeExtInput.value = ''
  routeEdit.value = true
}
function addRouteExt() {
  const e = routeExtInput.value.trim()
  if (e && !routeExternal.value.includes(e)) routeExternal.value.push(e)
  routeExtInput.value = ''
}
function buildRoute() {
  const parts: { type: string; b24_user_id: number | null; email: string; order_index: number }[] = []
  let idx = 0
  routeInternal.value.split(',').map((s) => s.trim()).filter(Boolean).forEach((s) => {
    const id = parseInt(s, 10)
    if (!Number.isNaN(id)) parts.push({ type: 'internal', b24_user_id: id, email: '', order_index: idx++ })
  })
  routeExternal.value.forEach((email) => parts.push({ type: 'external', b24_user_id: null, email, order_index: idx++ }))
  return parts
}
async function saveRoute() {
  const parts = buildRoute()
  if (!parts.length) { error.value = 'Маршрут пуст.'; return }
  await run(() => agreements.setRoute(selected.value!.id, parts))
  routeEdit.value = false
}
async function resubmit(withEditedRoute: boolean) {
  const parts = withEditedRoute ? buildRoute() : undefined
  if (withEditedRoute && (!parts || !parts.length)) { error.value = 'Маршрут пуст.'; return }
  await run(() => agreements.resubmit(selected.value!.id, parts))
  routeEdit.value = false
}
function cancel() {
  if (confirm('Отменить согласование?')) run(() => agreements.cancel(selected.value!.id))
}
async function remove() {
  if (!confirm('Удалить согласование безвозвратно?')) return
  await agreements.remove(selected.value!.id)
  selected.value = null
  await loadList()
}

function dl(url: string | null, name: string) {
  if (url) api.download(url, name).catch((e) => (error.value = e.message))
}

// --- версионируемые документы (ТЗ п.7.1-7.3) ---
const newDocInput = ref<HTMLInputElement | null>(null)
const versionInput = ref<HTMLInputElement | null>(null)
const versionDocId = ref<number | null>(null)

async function uploadNewDoc(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  await run(() => agreements.addDocument(selected.value!.id, file, file.name))
  input.value = ''
}
function pickVersion(docId: number) {
  versionDocId.value = docId
  versionInput.value?.click()
}
async function uploadVersion(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  const did = versionDocId.value
  if (!file || did == null) { input.value = ''; return }
  const comment = window.prompt('Комментарий к версии (что изменено, необязательно):') || ''
  await run(() => agreements.addVersion(did, file, comment))
  input.value = ''
  versionDocId.value = null
}

// --- онлайн-редактирование документа (ТЗ п.7.2-7.3) ---
const editingDocId = ref<number | null>(null)
function onEditorClose(changed: boolean) {
  editingDocId.value = null
  // если документ правился — перечитать карточку, чтобы показать новую версию
  if (changed && selected.value) open(selected.value.id)
}

// --- лист согласования (ТЗ п.7.7) ---
function downloadSheet() {
  if (selected.value) {
    api.download(agreements.sheetPdfUrl(selected.value.id), `Лист_согласования_${selected.value.id}.pdf`)
      .catch((e) => (error.value = e.message))
  }
}

const isAuthor = computed(() => selected.value?.author_b24_id === uid.value)

// --- новое согласование (slide-over) ---
const showForm = ref(false)
const form = ref({
  title: '', description: '', amount: '', deadline: '', crm_link: '',
  flow_type: 'parallel', internal_users: '',
})
const formFiles = ref<File[]>([])
const savingForm = ref(false)

// внешние участники — чипами (как в старой форме)
const externalList = ref<string[]>([])
const externalInput = ref('')
function addExternal() {
  const e = externalInput.value.trim()
  if (e && !externalList.value.includes(e)) externalList.value.push(e)
  externalInput.value = ''
}
function removeExternal(i: number) { externalList.value.splice(i, 1) }

// Внутренние участники формы как чипы (id → аватар+ФИО, как в старом миниседе)
const internalChips = computed(() =>
  form.value.internal_users
    .split(',').map((s) => s.trim()).filter(Boolean)
    .map(Number).filter((n) => !Number.isNaN(n)),
)
function removeInternal(id: number) {
  form.value.internal_users = internalChips.value.filter((x) => x !== id).join(', ')
}

// шаблоны маршрута
const formTemplates = ref<AgreementTemplate[]>([])
const selectedTemplate = ref<number | ''>('')
const templateName = ref('')
const templateScope = ref('private')
const savingTemplate = ref(false)

async function loadFormTemplates() {
  try { formTemplates.value = await agreements.templates() } catch { /* не критично */ }
}
function applyTemplate() {
  const t = formTemplates.value.find((x) => x.id === selectedTemplate.value)
  if (!t) return
  form.value.internal_users = t.participants
    .filter((p) => p.type === 'internal' && p.b24_user_id)
    .map((p) => p.b24_user_id).join(', ')
  externalList.value = t.participants.filter((p) => p.type === 'external').map((p) => p.email)
}
function buildParticipants() {
  const parts: { type: string; b24_user_id: number | null; email: string; name: string; order_index: number }[] = []
  let idx = 0
  form.value.internal_users.split(',').map((s) => s.trim()).filter(Boolean).forEach((s) => {
    const id = parseInt(s, 10)
    if (!Number.isNaN(id)) parts.push({ type: 'internal', b24_user_id: id, email: '', name: '', order_index: idx++ })
  })
  externalList.value.forEach((email) => parts.push({ type: 'external', b24_user_id: null, email, name: '', order_index: idx++ }))
  return parts
}
async function saveTemplate() {
  const parts = buildParticipants()
  if (!templateName.value.trim() || !parts.length) {
    error.value = 'Укажите название шаблона и хотя бы одного участника.'
    return
  }
  savingTemplate.value = true
  error.value = null
  try {
    await agreements.createTemplate({ name: templateName.value.trim(), scope: templateScope.value, participants: parts })
    templateName.value = ''
    await loadFormTemplates()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить шаблон'
  } finally {
    savingTemplate.value = false
  }
}

// Нативные виджеты Битрикс24 (работают внутри iframe портала).
interface BX24User { id: string | number; name?: string; position?: string }
interface BX24CrmItem { id: string | number; title?: string; url?: string }
interface BX24SDK {
  init(cb: () => void): void
  getAuth(): { domain?: string } | false
  selectUsers?(cb: (users: BX24User[]) => void): void
  selectCRM?(
    params: { entityType?: string[]; multiple?: boolean },
    cb: (res: Record<string, BX24CrmItem[]>) => void,
  ): void
}
function bx24(): BX24SDK | undefined {
  return (window as unknown as { BX24?: BX24SDK }).BX24
}


// Слить выбранные id с уже введёнными (строка «1, 2, 3») без дублей.
function mergeIds(current: string, picked: number[]): string {
  const existing = current.split(',').map((s) => s.trim()).filter(Boolean).map(Number)
  return Array.from(new Set([...existing, ...picked])).join(', ')
}

// Модалка поиска через серверный коннектор (для выбора вне iframe портала).
const pickerKind = ref<'users' | 'deals' | null>(null)
const pickApply = ref<(ids: number[]) => void>(() => {})

// Выбор сотрудников: внутри портала — нативный диалог BX24; вне — коннектор.
// apply получает выбранные id; заодно запоминаем ФИО/должность в справочник.
function pickUsersInto(apply: (ids: number[]) => void) {
  const BX24 = bx24()
  if (BX24 && BX24.selectUsers) {
    BX24.init(() => {
      BX24.selectUsers!((users) => {
        const ids: number[] = []
        for (const u of users) {
          const id = Number(u.id)
          if (Number.isNaN(id)) continue
          ids.push(id)
          userDir.value[id] = { fio: u.name || `USER #${id}`, position: u.position || '' }
        }
        apply(ids)
      })
    })
    return
  }
  pickApply.value = apply
  pickerKind.value = 'users'
}
function pickBitrixUsers() {
  pickUsersInto((ids) => { form.value.internal_users = mergeIds(form.value.internal_users, ids) })
}
function pickRouteUsers() {
  pickUsersInto((ids) => { routeInternal.value = mergeIds(routeInternal.value, ids) })
}

// Выбор из модалки коннектора
function onPickUser(u: BitrixUser) {
  const id = Number(u.ID)
  if (Number.isNaN(id)) return
  userDir.value[id] = {
    fio: [u.LAST_NAME, u.NAME, u.SECOND_NAME].filter(Boolean).join(' ') || `USER #${id}`,
    position: u.WORK_POSITION || '',
  }
  pickApply.value([id])
}
function onPickDeal(d: BitrixDeal) {
  const dom = portalDomain.value
  form.value.crm_link = dom ? `https://${dom}/crm/deal/details/${d.ID}/` : String(d.ID)
  pickerKind.value = null
}

// Выбор сделки: внутри портала — нативный диалог CRM; вне — коннектор.
function pickBitrixDeal() {
  const BX24 = bx24()
  if (!BX24 || !BX24.selectCRM) { pickerKind.value = 'deals'; return }
  BX24.init(() => {
    BX24.selectCRM!({ entityType: ['deal'], multiple: false }, (res) => {
      const deal = res?.deal?.[0]
      if (!deal) return
      const auth = BX24.getAuth()
      const domain = (auth && auth.domain) || ''
      // deal.url приходит относительным (/crm/deal/show/ID/) — дополняем доменом
      // портала до полной ссылки, как в старом миниседе.
      let link = deal.url || (domain ? `/crm/deal/show/${deal.id}/` : String(deal.id))
      if (link.startsWith('/') && domain) link = `https://${domain}${link}`
      form.value.crm_link = link
    })
  })
}

function openForm() {
  showForm.value = true
  loadFormTemplates()
}
function onFormFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const picked = Array.from(input.files || [])
  // добавляем к уже выбранным (можно по одному, в несколько заходов), без дублей
  for (const f of picked) {
    if (!formFiles.value.some((x) => x.name === f.name && x.size === f.size)) {
      formFiles.value.push(f)
    }
  }
  input.value = '' // сброс, чтобы можно было выбрать тот же файл снова
}
function removeFormFile(i: number) {
  formFiles.value.splice(i, 1)
}
async function createApproval() {
  if (!form.value.title.trim()) { error.value = 'Укажите название'; return }
  savingForm.value = true
  error.value = null
  try {
    const created = await agreements.create({
      ...form.value,
      external_emails: externalList.value.join(','),
      files: formFiles.value,
    })
    showForm.value = false
    form.value = { title: '', description: '', amount: '', deadline: '', crm_link: '', flow_type: 'parallel', internal_users: '' }
    externalList.value = []
    formFiles.value = []
    selectedTemplate.value = ''
    setMode('in_progress')
    await open(created.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать'
  } finally {
    savingForm.value = false
  }
}

function partLabel(p: AgParticipant): string {
  if (p.type === 'internal') return udName(p.b24_user_id)
  return p.email || p.name || 'Внешний участник'
}
function partPosition(p: AgParticipant): string {
  return p.type === 'internal' ? udPos(p.b24_user_id) : ''
}
function avatarText(p: AgParticipant): string {
  if (p.type === 'internal') return udInitials(p.b24_user_id)
  return (p.email || '?').charAt(0).toUpperCase()
}
const PART_STATUS_LABEL: Record<string, string> = {
  waiting: 'Ожидаем', approved: 'Согласовано', rejected: 'Отклонено',
}

onMounted(() => { loadUserDir(); loadList(); refreshBadges() })
</script>

<template>
  <div class="svet">
    <!-- Основная кнопка — в фиксированной шапке приложения -->
    <Teleport to="#header-actions">
      <button class="btn btn--primary" @click="openForm">+ Новое согласование</button>
    </Teleport>

    <!-- Поиск сотрудников/сделок через коннектор (вне iframe портала) -->
    <BitrixSearchModal
      v-if="pickerKind"
      :kind="pickerKind"
      @pick-user="onPickUser"
      @pick-deal="onPickDeal"
      @close="pickerKind = null"
    />

    <!-- Оверлей онлайн-редактора документа (ТЗ п.7.2-7.3) -->
    <DocumentEditor
      v-if="editingDocId"
      :doc-id="editingDocId"
      @close="onEditorClose"
    />

    <p v-if="error" class="state state--error" style="margin:8px 0">{{ error }}</p>

    <div class="svet-body">
      <!-- Список -->
      <div class="svet-list">
        <p v-if="loading" class="state">Загрузка…</p>

        <template v-else-if="mode === 'templates'">
          <p v-if="templates.length === 0" class="state">Шаблонов пока нет.</p>
          <div v-for="t in templates" :key="t.id" class="svet-card">
            <div class="svet-card-title">{{ t.name }}</div>
            <div class="item-sub">{{ t.participants.length }} участник(ов)</div>
          </div>
        </template>

        <template v-else>
          <!-- Заявки, ждущие моего решения (вкладка «Требует действия») -->
          <RouterLink
            v-for="r in (mode === 'todo' ? requestTodo : [])" :key="'req' + r.id"
            :to="`/requests/${r.id}`" class="svet-card svet-card--req">
            <div class="svet-card-row">
              <span class="svet-card-title">{{ r.number }} · {{ r.type_display }}</span>
              <span class="req-badge">Заявка</span>
            </div>
            <div class="item-sub">{{ r.subject_name || 'Без темы' }} · {{ r.status_display }}</div>
          </RouterLink>

          <!-- Договоры, ждущие моего решения -->
          <RouterLink
            v-for="c in (mode === 'todo' ? contractTodo : [])" :key="'con' + c.id"
            :to="`/contracts/${c.id}`" class="svet-card svet-card--req">
            <div class="svet-card-row">
              <span class="svet-card-title">{{ c.number }} · {{ c.title }}</span>
              <span class="req-badge">Договор</span>
            </div>
            <div class="item-sub">{{ c.organization_name }} · {{ c.status_display }}</div>
          </RouterLink>

          <!-- Заявки на комплименты, ждущие моего решения -->
          <RouterLink
            v-for="c in (mode === 'todo' ? complimentTodo : [])" :key="'cmp' + c.id"
            :to="`/compliments/${c.id}`" class="svet-card svet-card--req">
            <div class="svet-card-row">
              <span class="svet-card-title">{{ c.number }} · {{ c.title }}</span>
              <span class="req-badge">Комплимент</span>
            </div>
            <div class="item-sub">{{ c.category_display }} · {{ c.company }}</div>
          </RouterLink>

          <p
            v-if="items.length === 0 && !(mode === 'todo' && (requestTodo.length || contractTodo.length || complimentTodo.length))"
            class="state"
          >Пусто.</p>
          <div v-for="a in items" :key="a.id" class="svet-card" :class="{ active: selected?.id === a.id }" @click="open(a.id)">
            <div class="svet-card-row">
              <span class="svet-card-title">#{{ a.id }} {{ a.title }}</span>
              <span class="status-pill" :class="a.status">{{ AG_STATUS_LABEL[a.status] }}</span>
            </div>
            <div class="item-sub">Автор: {{ udName(a.author_b24_id) }} · {{ new Date(a.created_at).toLocaleDateString('ru') }}
              <template v-if="a.deadline"> · Дедлайн: {{ new Date(a.deadline).toLocaleDateString('ru') }}</template>
            </div>
            <div class="item-tags">
              <span v-for="p in a.participants" :key="p.id" class="tag-chip">
                {{ p.type === 'internal' ? udName(p.b24_user_id) : p.email }}
              </span>
            </div>
          </div>
        </template>
      </div>

      <!-- Деталь -->
      <div class="svet-detail">
        <p v-if="!selected" class="placeholder">Выберите согласование из списка слева, чтобы посмотреть детали.</p>

        <div v-else class="detail-inner">
          <!-- Заголовок: название, метаданные, статус слева под ними -->
          <div class="ag-head">
            <h1 class="ag-title">#{{ selected.id }} {{ selected.title }}</h1>
            <div class="ag-meta">
              Автор: {{ udName(selected.author_b24_id) }} · Создано: {{ new Date(selected.created_at).toLocaleString('ru') }}
              <template v-if="selected.deadline"> · Дедлайн: {{ new Date(selected.deadline).toLocaleDateString('ru') }}</template>
            </div>
            <span class="ag-status" :class="selected.status">{{ AG_STATUS_LABEL[selected.status] }}</span>
          </div>

          <div class="ag-cols">
            <!-- Левая колонка -->
            <div class="ag-main">
              <div class="ag-card">
                <div class="ag-card-header">Описание</div>
                <div class="ag-card-body" style="white-space:pre-line">{{ selected.description || 'Описание не указано.' }}</div>
              </div>

              <div class="ag-card">
                <div class="ag-card-header">
                  <span>Документы</span>
                  <button v-if="isAuthor" class="ag-btn ag-btn--soft" :disabled="busy" @click="newDocInput?.click()">+ Документ</button>
                  <input ref="newDocInput" type="file" style="display:none" @change="uploadNewDoc" />
                  <input ref="versionInput" type="file" style="display:none" @change="uploadVersion" />
                </div>

                <!-- версионируемые документы (несколько версий) -->
                <div v-for="d in selected.documents_v" :key="'v' + d.id" class="doc-item">
                  <div class="doc-name">{{ d.title }} <span class="ag-muted">· актуальная v{{ d.current_version_number }}</span></div>
                  <div class="doc-actions">
                    <a v-for="v in d.versions" :key="v.id" href="#" class="doc-link" :title="v.change_comment"
                       @click.prevent="dl(v.download_url, versionFileName(d.title, v))">
                      v{{ v.version_number }}{{ v.is_current ? ' ✓' : '' }}
                    </a>
                    <button v-if="isAuthor" type="button" class="doc-link doc-linkbtn" @click="pickVersion(d.id)">＋ новая версия</button>
                    <button
                      v-if="d.can_edit_online"
                      type="button"
                      class="doc-link doc-linkbtn"
                      @click="editingDocId = d.id"
                    >✏️ Редактировать онлайн</button>
                  </div>
                  <template v-for="v in d.versions" :key="'c' + v.id">
                    <div v-if="v.change_comment" class="ag-muted" style="margin-top:2px">v{{ v.version_number }}: {{ v.change_comment }}</div>
                  </template>
                </div>

                <!-- унаследованные файлы (без версий) -->
                <div v-for="d in selected.documents" :key="d.id" class="doc-item">
                  <div class="doc-name">{{ d.name }}</div>
                  <div class="doc-actions">
                    <a href="#" class="doc-link" @click.prevent="dl(d.file || d.url, d.name)">⭳ Скачать</a>
                    <a v-if="d.file || d.url" class="doc-link" :href="d.file || d.url" target="_blank" rel="noopener">◵ Открыть</a>
                  </div>
                </div>

                <div v-if="!selected.documents.length && !selected.documents_v.length" class="ag-muted">Документы не прикреплены.</div>
                <div v-if="isAuthor && selected.documents_v.length" class="ag-muted" style="margin-top:6px">
                  Правки: скачайте версию, измените локально и загрузите как «новую версию» — старая сохранится в истории.
                </div>
              </div>

              <!-- Лист согласования нужен только у завершённых (согласовано/отклонено). -->
              <div v-if="selected.status === 'completed' || selected.status === 'rejected'" class="ag-card">
                <div class="ag-card-header">Лист согласования</div>
                <button class="ag-btn ag-btn--soft ag-btn--wide" :disabled="busy" @click="downloadSheet">Скачать лист согласования (PDF)</button>
              </div>

              <div class="ag-card">
                <div class="ag-card-header">История согласования</div>
                <div v-if="!roundsHistory.length" class="ag-muted">Пока ничего не происходило.</div>
                <div v-for="grp in roundsHistory" :key="grp.round" style="margin-bottom:10px">
                  <div style="font-weight:600;font-size:12px;margin-bottom:4px">
                    Круг {{ grp.round }}<span v-if="grp.round === selected.current_round" class="ag-muted"> · текущий</span>
                  </div>
                  <div v-for="log in grp.logs" :key="log.id" class="log-item">
                    <b>{{ partLabel(log.participant) }}</b>
                    — <span :style="{ color: log.status === 'approved' ? 'var(--green-main)' : 'var(--red-main)' }">
                      {{ log.status === 'approved' ? 'согласовано' : 'отклонено' }}</span>
                    · {{ new Date(log.decided_at).toLocaleString('ru') }}
                    <div v-if="log.comment" class="ag-muted">{{ log.comment }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Правая колонка -->
            <div class="ag-side">
              <!-- Ваше решение -->
              <div class="ag-card">
                <div class="ag-card-header">Ваше решение</div>
                <div class="inner-box">
                  <template v-if="myPart && myPart.status === 'waiting' && selected.status === 'in_progress'">
                    <div class="ag-muted" style="margin-bottom:6px">Текущее решение: ожидаем</div>
                    <textarea v-model="decisionComment" rows="3" class="ag-textarea"
                              placeholder="Комментарий (при отклонении обязателен)"></textarea>
                    <div class="decide-row">
                      <button class="ag-btn ag-btn--soft" :disabled="busy" @click="decide(myPart, 'reject')">Отклонить</button>
                      <button class="ag-btn ag-btn--green" :disabled="busy" @click="decide(myPart, 'approve')">Согласовать</button>
                    </div>
                  </template>
                  <template v-else-if="myPart">
                    <div class="ag-muted" v-if="selected.status !== 'in_progress'">Согласование завершено. Изменить решение невозможно.</div>
                    <div style="margin-top:4px">Ваше решение:
                      <span class="ag-badge" :class="myPart.status">{{ PART_STATUS_LABEL[myPart.status] }}</span>
                    </div>
                  </template>
                  <div v-else class="ag-muted">Вы не участник этого согласования.</div>
                </div>
              </div>

              <!-- Участники (текущий круг) -->
              <div class="ag-card">
                <div class="ag-card-header">
                  <span>Участники</span>
                  <span class="ag-muted" style="font-weight:400">круг {{ selected.current_round }}</span>
                </div>
                <div v-for="p in currentParts" :key="p.id" class="participant-card">
                  <div class="pc-left">
                    <div class="pc-avatar">{{ avatarText(p) }}</div>
                    <div class="pc-main">
                      <div class="pc-name">{{ partLabel(p) }}</div>
                      <div v-if="partPosition(p)" class="pc-pos">{{ partPosition(p) }}</div>
                      <span class="ag-badge" :class="p.status">{{ PART_STATUS_LABEL[p.status] }}</span>
                    </div>
                  </div>
                </div>

                <!-- Смена согласующих / повторное согласование.
                     Завершённое согласование закрыто — редактирование недоступно. -->
                <template v-if="isAuthor && selected.status !== 'completed'">
                  <button v-if="!routeEdit" class="ag-btn ag-btn--soft ag-btn--wide" style="margin-top:6px" @click="openRouteEditor">
                    {{ selected.status === 'in_progress' ? 'Изменить маршрут текущего круга' : 'Перезапустить согласование (новый круг)' }}
                  </button>
                  <div v-else class="inner-box" style="margin-top:8px">
                    <div class="ag-muted" style="margin-bottom:4px">Согласующие (ID Б24, через запятую)</div>
                    <div class="fr-inline">
                      <input v-model="routeInternal" class="ag-textarea" style="min-height:auto" placeholder="1099, 1535" />
                      <button class="ag-btn ag-btn--blue" @click="pickRouteUsers">+ Выбрать в Б24</button>
                    </div>
                    <div class="ag-muted" style="margin:8px 0 4px">Внешние (email)</div>
                    <div class="fr-inline">
                      <input v-model="routeExtInput" class="ag-textarea" style="min-height:auto" placeholder="a@b.ru" @keyup.enter="addRouteExt" />
                      <button class="ag-btn ag-btn--soft" @click="addRouteExt">+</button>
                    </div>
                    <div v-if="routeExternal.length" class="chips" style="margin-top:6px">
                      <span v-for="(em, i) in routeExternal" :key="i" class="chip chip--ext">{{ em }} <button class="chip-x" @click="routeExternal.splice(i, 1)">×</button></span>
                    </div>
                    <div style="display:grid;gap:6px;margin-top:10px">
                      <button v-if="noneDecided && selected.status === 'in_progress'" class="ag-btn ag-btn--soft" :disabled="busy" @click="saveRoute">
                        Сохранить маршрут (текущий круг)
                      </button>
                      <button v-if="selected.status === 'rejected' || selected.status === 'canceled'" class="ag-btn ag-btn--orange" :disabled="busy" @click="resubmit(true)">
                        Отправить повторно новым кругом
                      </button>
                      <button class="ag-btn" style="background:transparent" @click="routeEdit = false">Отмена</button>
                    </div>
                    <div class="ag-muted" style="font-size:11px;margin-top:6px">
                      <template v-if="selected.status === 'in_progress'">Меняет согласующих текущего круга (до первых решений).</template>
                      <template v-else>Создаёт новый круг с этими согласующими; история прошлых кругов сохраняется.</template>
                    </div>
                  </div>
                </template>
              </div>

              <!-- Сводка -->
              <div class="ag-card">
                <div class="ag-card-header">Сводка</div>

                <div class="sum-block">
                  <div class="sum-label">Инициатор</div>
                  <div>{{ udName(selected.author_b24_id) }}</div>
                </div>
                <div class="sum-block">
                  <div class="sum-label">Сумма</div>
                  <div>{{ selected.amount || '—' }}</div>
                </div>
                <div class="sum-block">
                  <div class="sum-label">CRM</div>
                  <a v-if="selected.crm_link" class="crm-link" :href="selected.crm_link" target="_blank" rel="noopener">{{ selected.crm_link }}</a>
                  <div v-else>Не привязано</div>
                </div>

                <div v-if="isAuthor && selected.status === 'in_progress'" class="sum-block">
                  <div class="sum-label">Отмена</div>
                  <button class="ag-btn ag-btn--soft ag-btn--wide" :disabled="busy" @click="cancel">Отменить согласование</button>
                  <div class="sum-hint">Статус станет «Отменено», участники больше не смогут голосовать.</div>
                </div>

                <!-- Удаление — только у отменённого согласования. -->
                <div v-if="isAuthor && selected.status === 'canceled'" class="sum-block">
                  <div class="sum-label">Удаление</div>
                  <button class="ag-btn ag-btn--red ag-btn--wide" :disabled="busy" @click="remove">Удалить согласование</button>
                  <div class="sum-hint">Будут удалены все данные по этому согласованию.</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Slide-over: новое согласование -->
    <div v-if="showForm" class="slideover-back" @click.self="showForm = false">
      <aside class="slideover">
        <div class="slideover-head">
          <b>Новое согласование</b>
          <button class="link-btn" @click="showForm = false">Закрыть</button>
        </div>
        <div class="slideover-body">
          <div class="fr">
            <label class="fr-label fr-req">Название</label>
            <input class="fr-input" v-model="form.title" />
          </div>

          <div class="fr">
            <label class="fr-label">Описание</label>
            <textarea class="fr-input" v-model="form.description" rows="3"></textarea>
          </div>

          <div class="fr">
            <label class="fr-label">Тип согласования</label>
            <label class="fr-radio"><input type="radio" value="parallel" v-model="form.flow_type" /> Параллельное (все могут голосовать сразу)</label>
            <label class="fr-radio"><input type="radio" value="sequential" v-model="form.flow_type" /> Последовательное (по очереди, в порядке добавления)</label>
          </div>

          <div class="fr">
            <label class="fr-label">Сумма</label>
            <input class="fr-input" v-model="form.amount" type="number" />
          </div>

          <div class="fr">
            <label class="fr-label">Дедлайн</label>
            <input class="fr-input" v-model="form.deadline" type="date" />
            <div class="fr-hint">Необязательное поле, используется для напоминаний.</div>
          </div>

          <div class="fr">
            <label class="fr-label">Привязка к CRM</label>
            <div class="fr-inline">
              <input class="fr-input" v-model="form.crm_link" placeholder="Вставьте ссылку или выберите" />
              <button type="button" class="ag-btn ag-btn--blue" @click="pickBitrixDeal">Выбрать из CRM</button>
            </div>
            <div class="fr-hint">Можно вставить ссылку на сделку/счёт/контакт вручную или выбрать элемент CRM через диалог Битрикс24.</div>
          </div>

          <div class="fr">
            <label class="fr-label">Участники из Б24</label>
            <div class="fr-inline">
              <input class="fr-input" v-model="form.internal_users" placeholder="Например: 1, 25, 37" />
              <button type="button" class="ag-btn ag-btn--blue" @click="pickBitrixUsers">+ Выбрать в Б24</button>
            </div>
            <div v-if="internalChips.length" class="chips" style="margin-top:8px">
              <span v-for="id in internalChips" :key="id" class="chip chip--user">
                <span class="chip-ava">{{ udInitials(id) }}</span>
                {{ udName(id) }}
                <button type="button" class="chip-x" @click="removeInternal(id)">×</button>
              </span>
            </div>
            <div class="fr-hint">Можно указать через запятую или выбрать через диалог Bitrix24.</div>
          </div>

          <div class="fr">
            <label class="fr-label">Внешние участники (email)</label>
            <div class="fr-inline">
              <input class="fr-input" v-model="externalInput" type="email" placeholder="email@example.com" @keyup.enter="addExternal" />
              <button type="button" class="ag-btn ag-btn--soft" @click="addExternal">+ Добавить</button>
            </div>
            <div v-if="externalList.length" class="chips">
              <span v-for="(em, i) in externalList" :key="i" class="chip chip--ext">
                {{ em }} <button type="button" class="chip-x" @click="removeExternal(i)">×</button>
              </span>
            </div>
            <div class="fr-hint">На указанные адреса будет отправлена ссылка для согласования.</div>
          </div>

          <div class="fr">
            <label class="fr-label">Шаблон согласования</label>
            <div class="fr-inline">
              <select class="fr-input" v-model="selectedTemplate" @change="applyTemplate">
                <option value="">— Не использовать шаблон —</option>
                <option v-for="t in formTemplates" :key="t.id" :value="t.id">{{ t.name }}</option>
              </select>
              <button type="button" class="ag-btn ag-btn--soft" @click="loadFormTemplates">Обновить</button>
            </div>
            <div class="fr-inline" style="margin-top:8px">
              <input class="fr-input" v-model="templateName" placeholder="Название шаблона" />
              <select class="fr-input" style="max-width:130px" v-model="templateScope">
                <option value="private">Только мне</option>
                <option value="public">Всем</option>
              </select>
            </div>
            <button type="button" class="ag-btn ag-btn--green" style="margin-top:8px" :disabled="savingTemplate" @click="saveTemplate">
              {{ savingTemplate ? 'Сохранение…' : 'Сохранить как шаблон' }}
            </button>
            <div class="fr-hint">Шаблон сохраняет только маршрут (список участников). Название и описание согласования вы задаёте отдельно при создании.</div>
          </div>

          <div class="fr">
            <label class="fr-label">Файлы</label>
            <input type="file" multiple @change="onFormFiles" />
            <ul v-if="formFiles.length" class="file-list">
              <li v-for="(f, i) in formFiles" :key="i" class="file-row">
                <span class="file-name">{{ f.name }}</span>
                <button type="button" class="chip-x" title="Убрать" @click="removeFormFile(i)">×</button>
              </li>
            </ul>
            <div class="fr-hint">Можно добавлять по одному в несколько заходов; лишние — убрать до отправки.</div>
          </div>
        </div>
        <div class="slideover-foot">
          <button class="btn btn--primary" :disabled="savingForm" @click="createApproval">
            {{ savingForm ? 'Создание…' : 'Создать и отправить' }}
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.svet { display: flex; flex-direction: column; height: calc(100vh - 120px); }
.svet-body { display: flex; gap: 14px; flex: 1; overflow: hidden; }
.svet-list { width: 360px; flex: none; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.svet-detail { flex: 1; overflow-y: auto; background: var(--gray-bg); border-radius: 10px; padding: 4px 4px 20px; }
.placeholder { color: var(--text-muted); text-align: center; padding: 40px; }
.svet-card { background: #fff; border: 1px solid #f1f1f1; border-radius: 8px; padding: 10px 12px; box-shadow: var(--shadow-soft); cursor: pointer; }
.svet-card--req { display: block; text-decoration: none; color: inherit; border-left: 3px solid var(--green-main); }
.req-badge { font-size: 11px; font-weight: 600; color: var(--green-main); background: var(--green-light); border-radius: 999px; padding: 2px 8px; white-space: nowrap; }
.svet-card:hover { background: #fafafa; }
.svet-card.active { border-color: var(--green-main); }
.svet-card-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.svet-card-title { font-weight: 600; font-size: 14px; }
.radio { display: block; font-size: 13px; margin: 3px 0; }

/* --- Деталь согласования (порт из старого app.html) --- */
.detail-inner { max-width: 980px; margin: 0 auto; padding: 8px 12px 24px; }
.ag-head { margin-bottom: 12px; }
.ag-title { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
.ag-meta { font-size: 12px; color: var(--text-muted); }
.ag-status { display: inline-flex; align-items: center; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; color: #fff; margin-top: 8px; }
.ag-status.in_progress { background: var(--orange-main); }
.ag-status.completed { background: var(--green-main); }
.ag-status.rejected { background: var(--red-main); }
.ag-status.draft, .ag-status.canceled { background: #9e9e9e; }

.ag-cols { display: grid; grid-template-columns: minmax(0, 2fr) minmax(260px, 1.2fr); gap: 16px; align-items: start; }
.ag-card { background: #fff; border-radius: 10px; padding: 10px 12px; box-shadow: var(--shadow-soft); border: 1px solid #f1f1f1; margin-bottom: 10px; overflow: hidden; }
.ag-card-header { font-size: 13px; font-weight: 600; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.ag-card-body { font-size: 13px; }
.ag-muted { font-size: 12px; color: var(--text-muted); }
.log-item { font-size: 12px; margin-bottom: 8px; }

.inner-box { border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px 10px; }
.ag-textarea { width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #d0d0d0; border-radius: 6px; font: inherit; font-size: 13px; resize: vertical; }
.decide-row { display: flex; gap: 8px; margin-top: 8px; }
.decide-row .ag-btn { flex: 1; }

.doc-item { background: #fff; border-radius: 8px; border: 1px solid #e0e0e0; padding: 8px 10px; margin-bottom: 8px; }
.doc-name { font-size: 14px; font-weight: 500; margin-bottom: 4px; overflow-wrap: anywhere; word-break: break-word; }
.doc-actions { font-size: 12px; display: flex; gap: 14px; }
.doc-link { color: var(--green-main); text-decoration: none; cursor: pointer; }
.doc-link:hover { text-decoration: underline; }
.doc-linkbtn { border: none; background: transparent; padding: 0; cursor: pointer; color: var(--green-main); font: inherit; font-size: 12px; }
.doc-linkbtn:hover { text-decoration: underline; }

.participant-card { background: #fff; border-radius: 8px; border: 1px solid #e0e0e0; padding: 8px 10px; margin-bottom: 6px; font-size: 13px; }
.pc-left { display: flex; gap: 8px; align-items: flex-start; min-width: 0; }
.pc-avatar { width: 28px; height: 28px; flex: 0 0 28px; border-radius: 999px; background: #e0f2f1; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 500; color: var(--green-main); }
.pc-main { display: flex; flex-direction: column; min-width: 0; gap: 3px; }
.pc-name { font-size: 13px; font-weight: 500; overflow-wrap: anywhere; }
.pc-pos { font-size: 11.5px; color: var(--text-muted); overflow-wrap: anywhere; }

.ag-badge { display: inline-block; width: fit-content; padding: 2px 8px; border-radius: 999px; font-size: 10px; background: #e0e0e0; }
.ag-badge.waiting { background: #ffe0b2; }
.ag-badge.approved { background: #c8e6c9; }
.ag-badge.rejected { background: #ffcdd2; }

.sum-block { border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; }
.sum-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-muted); margin-bottom: 4px; }
.sum-hint { font-size: 11px; color: var(--text-muted); margin-top: 6px; }
.crm-link { display: inline-block; max-width: 100%; overflow-wrap: anywhere; word-break: break-all; text-decoration: none; color: #1976d2; font-size: 12px; }
.crm-link:hover { text-decoration: underline; }

.ag-btn { font: inherit; font-size: 13px; cursor: pointer; border-radius: 6px; border: 1px solid var(--gray-border); background: #fff; color: var(--text-main); padding: 7px 12px; }
.ag-btn:disabled { opacity: 0.5; cursor: default; }
.ag-btn--wide { width: 100%; }
.ag-btn--soft { background: #f1f1f1; border-color: #e0e0e0; color: #333; }
.ag-btn--green { background: var(--green-main); color: #fff; border-color: var(--green-main); }
.ag-btn--orange { background: var(--orange-main); color: #fff; border-color: var(--orange-main); }
.ag-btn--red { background: var(--red-main); color: #fff; border-color: var(--red-main); }
.ag-btn--blue { background: #2f6fd6; color: #fff; border-color: #2f6fd6; white-space: nowrap; }

/* --- Форма создания (порт из старого app.html) --- */
.fr { margin-bottom: 18px; }
.fr-label { display: block; font-size: 12px; font-weight: 500; margin-bottom: 4px; }
.fr-req::after { content: " *"; color: var(--red-main); }
.fr-input { width: 100%; box-sizing: border-box; padding: 8px 11px; border-radius: 4px; border: 1px solid #d0d0d0; font: inherit; font-size: 14px; }
textarea.fr-input { resize: vertical; min-height: 60px; }
.fr-hint { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.fr-radio { display: block; font-size: 13px; margin: 4px 0; }
.fr-inline { display: flex; gap: 8px; align-items: center; }
.fr-inline .fr-input { flex: 1; min-width: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 999px; background: #f1f3f4; font-size: 12px; }
.chip--ext { background: #fff3e0; }
.file-list { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.file-row { display: flex; align-items: center; gap: 8px; background: #f5f6f8; border-radius: 6px; padding: 5px 8px; font-size: 12.5px; }
.file-name { flex: 1; overflow-wrap: anywhere; }
.chip--user { background: var(--green-light); color: #0a6e52; padding-left: 3px; }
.chip-ava { width: 20px; height: 20px; border-radius: 999px; background: #fff; color: var(--green-main); font-size: 10px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.chip-x { border: none; background: transparent; cursor: pointer; font-size: 14px; line-height: 1; color: var(--text-muted); padding: 0; }

.slideover-back { position: fixed; inset: 0; background: rgba(0,0,0,0.25); display: flex; justify-content: flex-end; z-index: 50; }
.slideover { width: 420px; max-width: 92vw; background: #fff; height: 100%; display: flex; flex-direction: column; box-shadow: -2px 0 12px rgba(0,0,0,0.12); }
.slideover-head { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--gray-border); }
.slideover-body { flex: 1; overflow-y: auto; padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.slideover-foot { padding: 14px 18px; border-top: 1px solid var(--gray-border); }
.slideover-body textarea { padding: 8px 11px; font: inherit; border: 1px solid var(--gray-border); border-radius: 6px; resize: vertical; }
.link-btn { background: none; border: none; color: var(--green-main); cursor: pointer; font: inherit; }

@media (max-width: 900px) {
  .svet-body { flex-direction: column; overflow: visible; }
  .svet-list { width: 100%; }
  .ag-cols { grid-template-columns: 1fr; }
}
</style>
