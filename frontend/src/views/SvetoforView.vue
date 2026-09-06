<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { agreements } from '@/services/agreements'
import { requests } from '@/services/requests'
import { contracts } from '@/services/contracts'
import { compliments } from '@/services/compliments'
import type { ContractListItem } from '@/types/contract'
import type { ComplimentListItem } from '@/types/compliment'
import BitrixSearchModal from '@/components/BitrixSearchModal.vue'
import DocumentEditor from '@/components/DocumentEditor.vue'
import SearchBox from '@/components/SearchBox.vue'
import { useUserDirectory } from '@/composables/useUserDirectory'
import { mergeIds, useBitrixPicker } from '@/composables/useBitrixPicker'
import { api, ApiError } from '@/services/api'
import { versionFileName } from '@/utils/filename'
import { useAuthStore } from '@/stores/auth'
import { useSvetoforStore, type SvetoforMode as Mode } from '@/stores/svetofor'
import {
  type Agreement, type AgParticipant, type DecisionLog,
  AG_STATUS_LABEL,
} from '@/types/agreement'
import type { RegulatoryRequestListItem } from '@/types/request'

const auth = useAuthStore()

// Режим вкладок живёт в сторе — кнопки перенесены в сайдбар (App.vue).
const svet = useSvetoforStore()
const mode = computed(() => svet.mode)

// Поиск по согласованиям: название, описание, сделка, участники и ИМЕНА
// прикреплённых файлов. При непустом запросе вкладка выборку не сужает —
// ищут карточку, не зная её статуса (как в очереди юротдела).
const query = ref('')

// Рабочее место визирования показывает ВСЁ, что проходило через меня, а не
// только свободные согласования: заявки, договоры и комплименты, где я
// согласующий, попадают в те же вкладки. Свои свободные согласования тоже
// остаются в списке — жить им больше негде, отдельного раздела у них нет.
type WorkKind = 'agreement' | 'request' | 'contract' | 'compliment'

interface WorkItem {
  kind: WorkKind
  id: number
  title: string
  subtitle: string
  status: string
  statusDisplay: string
  badge: string
  createdAt: string
  /** Маршрут карточки; у согласований пусто — они раскрываются панелью справа. */
  to: string
  tags: string[]
}

const rawAgreements = ref<Agreement[]>([])
const rawRequests = ref<RegulatoryRequestListItem[]>([])
const rawContracts = ref<ContractListItem[]>([])
const rawCompliments = ref<ComplimentListItem[]>([])

const selected = ref<Agreement | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const busy = ref(false)

const uid = computed(() => auth.b24UserId)

const {
  userDir, portalDomain, loadUserDir, udName, udPos, udInitials, enrichUsers,
} = useUserDirectory()

// Свободные согласования отбираем по статусу на сервере: иначе на каждой
// вкладке пришлось бы тянуть весь архив.
const STATUS_BY_MODE: Partial<Record<Mode, string>> = {
  in_progress: 'in_progress',
  rejected: 'rejected',
  completed: 'completed',
}

// Статусные вкладки — архив по статусу. У каждого модуля свои статусы, поэтому
// раскладку берём ту же, что в его собственном разделе: иначе одна и та же
// карточка попадала бы в разных местах приложения на разные вкладки.
const TAB_STATUSES: Record<string, Record<WorkKind, string[]>> = {
  in_progress: {
    agreement: ['in_progress'],
    request: ['on_approval', 'returned'],
    contract: ['on_approval'],
    compliment: ['on_approval', 'returned'],
  },
  rejected: {
    agreement: ['rejected'],
    request: ['rejected'],
    contract: ['rejected', 'returned'],
    compliment: ['rejected'],
  },
  completed: {
    agreement: ['completed'],
    request: ['approved', 'to_legal', 'legal_work', 'signing', 'executed', 'closed'],
    contract: ['approved'],
    compliment: ['approved', 'in_work', 'executed'],
  },
}

function fmtDate(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleDateString('ru') : ''
}

// Имена подставляются здесь, а не при загрузке: справочник сотрудников
// дозагружается из Битрикса асинхронно, и вычисляемый список сам обновится.
const items = computed<WorkItem[]>(() => {
  const merged: WorkItem[] = [
    ...rawAgreements.value.map((a) => ({
      kind: 'agreement' as const,
      id: a.id,
      title: `#${a.id} ${a.title}`,
      subtitle: [
        `Автор: ${udName(a.author_b24_id)}`,
        fmtDate(a.created_at),
        a.deadline ? `Дедлайн: ${fmtDate(a.deadline)}` : '',
      ].filter(Boolean).join(' · '),
      status: a.status,
      statusDisplay: AG_STATUS_LABEL[a.status] || a.status,
      badge: 'Согласование',
      createdAt: a.created_at,
      to: '',
      tags: a.participants.map((p) => (p.type === 'internal' ? udName(p.b24_user_id) : p.email)),
    })),
    ...rawRequests.value.map((r) => ({
      kind: 'request' as const,
      id: r.id,
      title: `${r.number} · ${r.type_display}`,
      subtitle: [r.subject_name || 'Без темы', r.organization_name].filter(Boolean).join(' · '),
      status: r.status,
      statusDisplay: r.status_display,
      badge: 'Заявка',
      createdAt: r.created_at,
      to: `/requests/${r.id}`,
      tags: [],
    })),
    ...rawContracts.value.map((c) => ({
      kind: 'contract' as const,
      id: c.id,
      title: `${c.number} · ${c.title}`,
      subtitle: [c.organization_name, c.cfo_name].filter(Boolean).join(' · '),
      status: c.status,
      statusDisplay: c.status_display,
      badge: 'Договор',
      createdAt: c.created_at,
      to: `/contracts/${c.id}`,
      tags: [],
    })),
    ...rawCompliments.value.map((c) => ({
      kind: 'compliment' as const,
      id: c.id,
      title: `${c.number} · ${c.title}`,
      subtitle: [c.category_display, c.company].filter(Boolean).join(' · '),
      status: c.status,
      statusDisplay: c.status_display,
      badge: 'Комплимент',
      createdAt: c.created_at,
      to: `/compliments/${c.id}`,
      tags: [],
    })),
  ]
  // «Требует действия» и «Все» показывают всё пришедшее; при поиске вкладка
  // тоже не сужает выборку — статус искомой карточки заранее неизвестен.
  const byStatus = query.value ? undefined : TAB_STATUSES[mode.value]
  const list = byStatus
    ? merged.filter((it) => (byStatus[it.kind] || []).includes(it.status))
    : merged
  return [...list].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
})

async function loadList() {
  loading.value = true
  error.value = null
  selected.value = null
  const q = query.value || undefined
  try {
    if (mode.value === 'todo' && !q) {
      // «Требует действия» — то, что ждёт именно моего решения, по всем модулям
      const [ag, rq, ct, cm] = await Promise.all([
        agreements.todo(),
        requests.todo().catch(() => []),
        contracts.todo().catch(() => []),
        compliments.todo().catch(() => []),
      ])
      rawAgreements.value = ag
      rawRequests.value = rq
      rawContracts.value = ct
      rawCompliments.value = cm
    } else {
      // Архивные вкладки: всё, где я согласующий, плюс свои свободные
      // согласования. Статус согласований отбираем на сервере — иначе на каждой
      // вкладке пришлось бы тянуть весь архив; остальные модули отсеиваем на
      // клиенте, их объёмы несопоставимо меньше.
      const agStatus = q ? undefined : STATUS_BY_MODE[mode.value]
      const [ag, rq, ct, cm] = await Promise.all([
        agreements.all(agStatus, q),
        requests.list(undefined, q, 'participant').catch(() => []),
        contracts.list('participant', q).catch(() => []),
        compliments.list('participant', q).catch(() => []),
      ])
      rawAgreements.value = ag
      rawRequests.value = rq
      rawContracts.value = ct
      rawCompliments.value = cm
    }
    // подтянуть имена авторов/участников списка
    enrichUsers(rawAgreements.value.flatMap(
      (a) => [a.author_b24_id, ...a.participants.map((p) => p.b24_user_id)],
    ))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка загрузки'
  } finally {
    loading.value = false
  }
}

// Смена вкладки (в т.ч. из сайдбара) или строки поиска перезагружает список.
watch([() => svet.mode, query], loadList)

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
  const id = selected.value?.id
  if (id) await open(id)
  // Обновляем только согласования — раскрытую карточку при этом не сбрасываем
  // (loadList для этого не годится: он снимает выделение).
  const q = query.value || undefined
  rawAgreements.value = (mode.value === 'todo' && !q)
    ? await agreements.todo()
    : await agreements.all(q ? undefined : STATUS_BY_MODE[mode.value], q)
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
// история по кругам (ТЗ п.7.4). Круг попадает в ленту и без решений — если
// инициатор направил его с комментарием, этот комментарий видно сразу.
const roundsHistory = computed(() => {
  if (!selected.value) return []
  const byRound = new Map<number, DecisionLog[]>()
  for (const log of selected.value.decision_logs) {
    if (!byRound.has(log.round_number)) byRound.set(log.round_number, [])
    byRound.get(log.round_number)!.push(log)
  }
  const notes = new Map<number, string>()
  for (const n of selected.value.round_notes || []) {
    notes.set(n.round_number, n.comment)
    if (!byRound.has(n.round_number)) byRound.set(n.round_number, [])
  }
  return [...byRound.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([round, logs]) => ({ round, logs, note: notes.get(round) || '' }))
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
// Пояснение инициатора согласующим при отправке нового круга (необязательное).
const resubmitComment = ref('')
async function resubmit(withEditedRoute: boolean) {
  const parts = withEditedRoute ? buildRoute() : undefined
  if (withEditedRoute && (!parts || !parts.length)) { error.value = 'Маршрут пуст.'; return }
  await run(() => agreements.resubmit(selected.value!.id, parts, resubmitComment.value.trim()))
  resubmitComment.value = ''
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

// Выбор сотрудников Битрикса — только для правки маршрута в карточке.
// Форма нового согласования вместе со своим выбором людей и сделок уехала
// в раздел «Иное» (создание — не визирование).
const { pickerKind, pickUsers, onPickUser, onPickDeal } = useBitrixPicker(userDir, portalDomain)
function pickRouteUsers() {
  pickUsers((ids) => { routeInternal.value = mergeIds(routeInternal.value, ids) })
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

// Ссылка из уведомления ведёт на /svetofor?open=<id> — сразу раскрываем эту
// карточку (в старом модуле карточка живёт внутри списка, отдельного роута нет).
const route = useRoute()
onMounted(async () => {
  loadUserDir()
  refreshBadges()
  const raw = route.query.open
  const id = parseInt(typeof raw === 'string' ? raw : '', 10)
  await loadList()
  // Карточка открывается поверх списка — вкладку не переключаем: loadList
  // сбрасывает selected, поэтому open идёт строго после него.
  if (!Number.isNaN(id)) await open(id)
})
</script>

<template>
  <div class="svet">
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
        <SearchBox
          v-model="query"
          placeholder="Поиск: название, номер, автор, сделка, имя файла"
        />
        <p v-if="query && !loading" class="state" style="margin-bottom:8px">
          Поиск идёт по всему, что мне доступно, независимо от вкладки. Найдено: {{ items.length }}.
        </p>

        <p v-if="loading" class="state">Загрузка…</p>

        <template v-else>
          <p v-if="items.length === 0" class="state">
            {{ query ? 'Ничего не найдено.' : 'Пусто.' }}
          </p>

          <!-- Карточки всех модулей в одном списке. Свободное согласование
               раскрывается панелью справа, остальное — своей страницей. -->
          <template v-for="it in items" :key="it.kind + it.id">
            <RouterLink v-if="it.to" :to="it.to" class="svet-card svet-card--req">
              <div class="svet-card-row">
                <span class="svet-card-title">{{ it.title }}</span>
                <span class="req-badge">{{ it.badge }}</span>
              </div>
              <div class="item-sub">{{ it.subtitle }} · {{ it.statusDisplay }}</div>
            </RouterLink>

            <div
              v-else class="svet-card"
              :class="{ active: selected?.id === it.id }"
              @click="open(it.id)"
            >
              <div class="svet-card-row">
                <span class="svet-card-title">{{ it.title }}</span>
                <span class="status-pill" :class="it.status">{{ it.statusDisplay }}</span>
              </div>
              <div class="item-sub">{{ it.subtitle }}</div>
              <div v-if="it.tags.length" class="item-tags">
                <span v-for="(t, i) in it.tags" :key="i" class="tag-chip">{{ t }}</span>
              </div>
            </div>
          </template>
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
                  <div v-if="grp.note" class="log-item">
                    <b>Инициатор</b>
                    — {{ grp.round > 1 ? 'направил(а) повторно' : 'направил(а) на согласование' }}
                    <div class="ag-muted">{{ grp.note }}</div>
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
                    <!-- Пояснение согласующим: что изменилось после доработки.
                         Необязательное — перезапуск в один клик сохранён. -->
                    <template v-if="selected.status === 'rejected' || selected.status === 'canceled'">
                      <div class="ag-muted" style="margin:8px 0 4px">
                        Комментарий согласующим — что изменилось (необязательно)
                      </div>
                      <textarea v-model="resubmitComment" rows="2" class="ag-textarea"
                                placeholder="Например: снизили сумму, приложена новая редакция"></textarea>
                    </template>
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
textarea.fr-input { resize: vertical; min-height: 60px; }

.link-btn { background: none; border: none; color: var(--green-main); cursor: pointer; font: inherit; }

@media (max-width: 900px) {
  .svet-body { flex-direction: column; overflow: visible; }
  .svet-list { width: 100%; }
  .ag-cols { grid-template-columns: 1fr; }
}
</style>
