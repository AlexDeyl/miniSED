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

const fileInput = ref<HTMLInputElement | null>(null)
async function updateDocs(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return
  await run(() => agreements.updateDocuments(selected.value!.id, files))
  input.value = ''
}
function dl(url: string | null, name: string) {
  if (url) api.download(url, name).catch((e) => (error.value = e.message))
}

const isAuthor = computed(() => selected.value?.author_b24_id === uid.value)

// --- новое согласование (slide-over) ---
const showForm = ref(false)
const form = ref({
  title: '', description: '', amount: '', deadline: '', crm_link: '',
  flow_type: 'parallel', internal_users: '', external_emails: '',
})
const formFiles = ref<File[]>([])
const savingForm = ref(false)

function onFormFiles(e: Event) {
  formFiles.value = Array.from((e.target as HTMLInputElement).files || [])
}
async function createApproval() {
  if (!form.value.title.trim()) { error.value = 'Укажите название'; return }
  savingForm.value = true
  error.value = null
  try {
    const created = await agreements.create({ ...form.value, files: formFiles.value })
    showForm.value = false
    form.value = { title: '', description: '', amount: '', deadline: '', crm_link: '', flow_type: 'parallel', internal_users: '', external_emails: '' }
    formFiles.value = []
    setMode('my')
    await open(created.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать'
  } finally {
    savingForm.value = false
  }
}

function partLabel(p: AgParticipant): string {
  if (p.type === 'internal') return `Сотрудник #${p.b24_user_id}`
  return p.email || p.name || 'Внешний участник'
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
      <button class="btn btn--primary" @click="showForm = true">+ Новое согласование</button>
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

        <template v-else>
          <div class="detail-header-main">
            <div>
              <h1 class="detail-title">#{{ selected.id }} {{ selected.title }}</h1>
              <div class="detail-meta">Автор: {{ selected.author_b24_id }} · Создано: {{ new Date(selected.created_at).toLocaleString('ru') }}</div>
            </div>
            <span class="status-pill" :class="selected.status">{{ AG_STATUS_LABEL[selected.status] }}</span>
          </div>

          <div class="detail-grid">
            <!-- Центр: описание, документы, ход -->
            <div>
              <div class="detail-card">
                <div class="detail-card-header">Описание</div>
                <p style="margin:0;white-space:pre-line">{{ selected.description || 'Описание не указано.' }}</p>
              </div>

              <div class="detail-card">
                <div class="detail-card-header">
                  Документы
                  <span style="flex:1"></span>
                  <button v-if="isAuthor" class="btn btn--ghost" style="padding:4px 10px" @click="fileInput?.click()">Обновить файлы</button>
                  <input ref="fileInput" type="file" multiple style="display:none" @change="updateDocs" />
                </div>
                <ul v-if="selected.documents.length" class="item-tags" style="flex-direction:column;align-items:flex-start;gap:6px">
                  <li v-for="d in selected.documents" :key="d.id">
                    <a href="#" @click.prevent="dl(d.file || d.url, d.name)">{{ d.name }}</a>
                  </li>
                </ul>
                <p v-else class="muted" style="margin:0">Документы не прикреплены.</p>
              </div>

              <div class="detail-card">
                <div class="detail-card-header">Ход согласования</div>
                <p v-if="!selected.decision_logs.length" class="muted" style="margin:0">Пока ничего не происходило.</p>
                <div v-for="log in selected.decision_logs" :key="log.id" style="margin-bottom:8px">
                  <b>{{ partLabel(log.participant) }}</b>
                  — <span :style="{ color: log.status === 'approved' ? 'var(--green-main)' : 'var(--red-main)' }">
                    {{ log.status === 'approved' ? 'согласовано' : 'отклонено' }}</span>
                  · {{ new Date(log.decided_at).toLocaleString('ru') }}
                  <div v-if="log.comment" class="muted">{{ log.comment }}</div>
                </div>
              </div>
            </div>

            <!-- Правая колонка: решение, участники, сводка, управление -->
            <div class="detail-side">
              <!-- Ваше решение -->
              <div class="detail-side-block">
                <div class="detail-card-header">Ваше решение</div>
                <template v-if="myPart && myPart.status === 'waiting' && selected.status === 'in_progress'">
                  <div class="muted" style="font-size:12px;margin-bottom:6px">Текущее решение: ожидаем</div>
                  <textarea v-model="decisionComment" rows="3" placeholder="Комментарий (при отклонении обязателен)"
                            style="width:100%;padding:8px;border:1px solid var(--gray-border);border-radius:6px;font:inherit;resize:vertical"></textarea>
                  <div class="row-actions" style="margin-top:8px">
                    <button class="btn" :disabled="busy" @click="decide(myPart, 'reject')">Отклонить</button>
                    <button class="btn btn--ok" :disabled="busy" @click="decide(myPart, 'approve')">Согласовать</button>
                  </div>
                </template>
                <template v-else-if="myPart">
                  <div class="muted" style="font-size:13px">
                    <template v-if="selected.status === 'completed' || selected.status === 'rejected' || selected.status === 'canceled'">
                      Согласование завершено. Изменить решение невозможно.<br />
                    </template>
                    Ваше решение:
                    <span class="participant-pill" :class="myPart.status">
                      {{ myPart.status === 'approved' ? 'Согласовано' : myPart.status === 'rejected' ? 'Отклонено' : 'Ожидаем' }}
                    </span>
                  </div>
                </template>
                <div v-else class="muted" style="font-size:13px">Вы не участник этого согласования.</div>
              </div>

              <!-- Участники -->
              <div class="detail-side-block">
                <div class="detail-card-header">Участники</div>
                <div v-for="p in selected.participants" :key="p.id" style="margin-bottom:8px">
                  {{ partLabel(p) }}
                  <span class="participant-pill" :class="p.status" style="display:block;width:fit-content;margin-top:2px">
                    {{ p.status === 'waiting' ? 'Ожидаем' : p.status === 'approved' ? 'Согласовано' : 'Отклонено' }}
                  </span>
                </div>
              </div>

              <!-- Сводка -->
              <div class="detail-side-block">
                <div class="detail-card-header">Сводка</div>
                <div class="kv"><span>Инициатор</span><b>#{{ selected.author_b24_id }}</b></div>
                <div class="kv"><span>Сумма</span><b>{{ selected.amount || '—' }}</b></div>
                <div class="kv"><span>CRM</span>
                  <a v-if="selected.crm_link" :href="selected.crm_link" target="_blank" rel="noopener">сделка ↗</a>
                  <b v-else>Не привязано</b>
                </div>
              </div>

              <!-- Управление: перезапуск (для отклонённых) -->
              <div v-if="isAuthor && (selected.status === 'rejected' || selected.status === 'in_progress')" class="detail-side-block">
                <div class="detail-card-header">Управление</div>
                <button class="btn" style="width:100%;background:var(--orange-main);color:#fff;border:none" :disabled="busy" @click="restart">Перезапустить согласование</button>
                <p class="muted" style="font-size:11px;margin:8px 0 0">Сбрасывает только отклонивших участников. Остальные решения сохраняются.</p>
              </div>

              <!-- Отмена -->
              <div v-if="isAuthor && selected.status === 'in_progress'" class="detail-side-block">
                <div class="detail-card-header">Отмена</div>
                <button class="btn btn--ghost" style="width:100%" :disabled="busy" @click="cancel">Отменить согласование</button>
                <p class="muted" style="font-size:11px;margin:8px 0 0">Статус станет «Отменено», участники больше не смогут голосовать.</p>
              </div>

              <!-- Удаление -->
              <div v-if="isAuthor" class="detail-side-block">
                <div class="detail-card-header">Удаление</div>
                <button class="btn btn--no" style="width:100%" :disabled="busy" @click="remove">Удалить согласование</button>
                <p class="muted" style="font-size:11px;margin:8px 0 0">Будут удалены все данные по этому согласованию.</p>
              </div>
            </div>
          </div>
        </template>
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
          <label class="form-field"><span>Название *</span><input v-model="form.title" /></label>
          <label class="form-field"><span>Описание</span><textarea v-model="form.description" rows="3"></textarea></label>
          <div class="form-field">
            <span>Тип согласования</span>
            <label class="radio"><input type="radio" value="parallel" v-model="form.flow_type" /> Параллельное (все сразу)</label>
            <label class="radio"><input type="radio" value="sequential" v-model="form.flow_type" /> Последовательное (по очереди)</label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Сумма</span><input v-model="form.amount" type="number" /></label>
            <label class="form-field"><span>Дедлайн</span><input v-model="form.deadline" type="date" /></label>
          </div>
          <label class="form-field"><span>Привязка к CRM (ссылка)</span><input v-model="form.crm_link" placeholder="https://…/crm/deal/…" /></label>
          <label class="form-field"><span>Участники из Б24 (ID через запятую)</span><input v-model="form.internal_users" placeholder="1099, 1535" /></label>
          <label class="form-field"><span>Внешние участники (email через запятую)</span><input v-model="form.external_emails" placeholder="a@b.ru, c@d.ru" /></label>
          <label class="form-field"><span>Файлы</span><input type="file" multiple @change="onFormFiles" /></label>
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
.detail-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr); gap: 14px; padding: 0 6px; }
.kv { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; margin: 4px 0; }
.kv span { color: var(--text-muted); }
.radio { display: block; font-size: 13px; margin: 3px 0; }

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
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
