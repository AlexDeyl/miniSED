<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { agreements } from '@/services/agreements'
import { api, ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import {
  type Agreement, type AgParticipant, type AgreementTemplate,
  AG_STATUS_LABEL,
} from '@/types/agreement'

const auth = useAuthStore()

type Mode = 'todo' | 'my' | 'all' | 'templates'
const TABS: { code: Mode; label: string }[] = [
  { code: 'todo', label: 'Требуется действие' },
  { code: 'my', label: 'Созданные мной' },
  { code: 'all', label: 'Все' },
  { code: 'templates', label: 'Шаблоны' },
]

const mode = ref<Mode>('todo')
const items = ref<Agreement[]>([])
const templates = ref<AgreementTemplate[]>([])
const selected = ref<Agreement | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const busy = ref(false)

const uid = computed(() => auth.b24UserId)

async function fetchByMode(m: Mode): Promise<Agreement[]> {
  if (m === 'todo') return agreements.todo()
  if (m === 'my') return agreements.my()
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
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка загрузки'
  } finally {
    loading.value = false
  }
}

function setMode(m: Mode) {
  mode.value = m
  loadList()
}

const decisionComment = ref('')
async function open(id: number) {
  decisionComment.value = ''
  try {
    selected.value = await agreements.get(id)
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
}

// решение текущего пользователя (для блока «Ваше решение»)
const myPart = computed(() =>
  selected.value?.participants.find((p) => p.type === 'internal' && p.b24_user_id === uid.value) ?? null,
)

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

function restart() { run(() => agreements.restart(selected.value!.id)) }
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

function crmDialogHint() {
  alert('Выбор из CRM доступен внутри Битрикс24. Вставьте ссылку на сделку вручную.')
}
function b24DialogHint() {
  alert('Выбор сотрудников через диалог доступен внутри Битрикс24. Укажите ID через запятую.')
}

function openForm() {
  showForm.value = true
  loadFormTemplates()
}
function onFormFiles(e: Event) {
  formFiles.value = Array.from((e.target as HTMLInputElement).files || [])
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
    setMode('my')
    await open(created.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать'
  } finally {
    savingForm.value = false
  }
}

function partLabel(p: AgParticipant): string {
  if (p.type === 'internal') return `USER #${p.b24_user_id}`
  return p.email || p.name || 'Внешний участник'
}
function avatarText(p: AgParticipant): string {
  if (p.type === 'internal') return 'U#'
  return (p.email || '?').charAt(0).toUpperCase()
}
const PART_STATUS_LABEL: Record<string, string> = {
  waiting: 'Ожидаем', approved: 'Согласовано', rejected: 'Отклонено',
}

onMounted(loadList)
</script>

<template>
  <div class="svet">
    <div class="svet-head">
      <div class="svet-tabs">
        <button v-for="t in TABS" :key="t.code" class="svet-tab" :class="{ active: mode === t.code }" @click="setMode(t.code)">
          {{ t.label }}
        </button>
      </div>
      <button class="btn btn--primary" @click="openForm">+ Новое согласование</button>
    </div>

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
          <p v-if="items.length === 0" class="state">Пусто.</p>
          <div v-for="a in items" :key="a.id" class="svet-card" :class="{ active: selected?.id === a.id }" @click="open(a.id)">
            <div class="svet-card-row">
              <span class="svet-card-title">#{{ a.id }} {{ a.title }}</span>
              <span class="status-pill" :class="a.status">{{ AG_STATUS_LABEL[a.status] }}</span>
            </div>
            <div class="item-sub">Автор: {{ a.author_b24_id }} · {{ new Date(a.created_at).toLocaleDateString('ru') }}
              <template v-if="a.deadline"> · Дедлайн: {{ new Date(a.deadline).toLocaleDateString('ru') }}</template>
            </div>
            <div class="item-tags">
              <span v-for="p in a.participants" :key="p.id" class="tag-chip">
                {{ p.type === 'internal' ? `#${p.b24_user_id}` : p.email }}
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
              Автор: {{ selected.author_b24_id }} · Создано: {{ new Date(selected.created_at).toLocaleString('ru') }}
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
                       @click.prevent="dl(v.download_url, `${d.title} v${v.version_number}`)">
                      v{{ v.version_number }}{{ v.is_current ? ' ✓' : '' }}
                    </a>
                    <button v-if="isAuthor" type="button" class="doc-link doc-linkbtn" @click="pickVersion(d.id)">＋ новая версия</button>
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

              <div class="ag-card">
                <div class="ag-card-header">Лист согласования</div>
                <button class="ag-btn ag-btn--soft ag-btn--wide" :disabled="busy" @click="downloadSheet">Скачать лист согласования (PDF)</button>
              </div>

              <div class="ag-card">
                <div class="ag-card-header">Ход согласования</div>
                <div v-if="!selected.decision_logs.length" class="ag-muted">Пока ничего не происходило.</div>
                <div v-for="log in selected.decision_logs" :key="log.id" class="log-item">
                  <b>{{ partLabel(log.participant) }}</b>
                  — <span :style="{ color: log.status === 'approved' ? 'var(--green-main)' : 'var(--red-main)' }">
                    {{ log.status === 'approved' ? 'согласовано' : 'отклонено' }}</span>
                  · {{ new Date(log.decided_at).toLocaleString('ru') }}
                  <div v-if="log.comment" class="ag-muted">{{ log.comment }}</div>
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

              <!-- Участники -->
              <div class="ag-card">
                <div class="ag-card-header">Участники</div>
                <div v-for="p in selected.participants" :key="p.id" class="participant-card">
                  <div class="pc-left">
                    <div class="pc-avatar">{{ avatarText(p) }}</div>
                    <div class="pc-main">
                      <div class="pc-name">{{ partLabel(p) }}</div>
                      <span class="ag-badge" :class="p.status">{{ PART_STATUS_LABEL[p.status] }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Сводка -->
              <div class="ag-card">
                <div class="ag-card-header">Сводка</div>

                <div class="sum-block">
                  <div class="sum-label">Инициатор</div>
                  <div>#{{ selected.author_b24_id }}</div>
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

                <div v-if="isAuthor && (selected.status === 'rejected' || selected.status === 'in_progress')" class="sum-block">
                  <div class="sum-label">Управление</div>
                  <button class="ag-btn ag-btn--orange ag-btn--wide" :disabled="busy" @click="restart">Перезапустить согласование</button>
                  <div class="sum-hint">Сбрасывает только отклонивших участников. Остальные решения сохраняются.</div>
                </div>

                <div v-if="isAuthor && selected.status === 'in_progress'" class="sum-block">
                  <div class="sum-label">Отмена</div>
                  <button class="ag-btn ag-btn--soft ag-btn--wide" :disabled="busy" @click="cancel">Отменить согласование</button>
                  <div class="sum-hint">Статус станет «Отменено», участники больше не смогут голосовать.</div>
                </div>

                <div v-if="isAuthor" class="sum-block">
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
              <button type="button" class="ag-btn ag-btn--blue" @click="crmDialogHint">Выбрать из CRM</button>
            </div>
            <div class="fr-hint">Можно вставить ссылку на сделку/счёт/контакт вручную или выбрать элемент CRM через диалог Битрикс24.</div>
          </div>

          <div class="fr">
            <label class="fr-label">Участники из Б24</label>
            <div class="fr-inline">
              <input class="fr-input" v-model="form.internal_users" placeholder="Например: 1, 25, 37" />
              <button type="button" class="ag-btn ag-btn--blue" @click="b24DialogHint">+ Выбрать в Б24</button>
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
            <div class="fr-hint">Прикрепите документы, которые нужно согласовать.</div>
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
.svet-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.svet-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.svet-tab { border: 1px solid var(--gray-border); background: #fff; color: var(--text-muted); border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.svet-tab.active { background: var(--green-light); color: var(--green-main); border-color: var(--green-main); font-weight: 500; }
.svet-body { display: flex; gap: 14px; flex: 1; overflow: hidden; }
.svet-list { width: 360px; flex: none; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.svet-detail { flex: 1; overflow-y: auto; background: var(--gray-bg); border-radius: 10px; padding: 4px 4px 20px; }
.placeholder { color: var(--text-muted); text-align: center; padding: 40px; }
.svet-card { background: #fff; border: 1px solid #f1f1f1; border-radius: 8px; padding: 10px 12px; box-shadow: var(--shadow-soft); cursor: pointer; }
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
