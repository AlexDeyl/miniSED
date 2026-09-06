<script setup lang="ts">
// Раздел «Иное»: всё, что не относится к визированию.
//  • «Новое согласование» — создание свободного согласования. Раньше жило
//    кнопкой в шапке рабочего места визирования; создание — не визирование,
//    поэтому уехало сюда.
//  • «Шаблоны» — маршруты для таких согласований, там же, где их применяют.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { agreements } from '@/services/agreements'
import { ApiError } from '@/services/api'
import BitrixSearchModal from '@/components/BitrixSearchModal.vue'
import { useUserDirectory } from '@/composables/useUserDirectory'
import { mergeIds, useBitrixPicker } from '@/composables/useBitrixPicker'
import { useOtherUiStore } from '@/stores/otherUi'
import { useSvetoforStore } from '@/stores/svetofor'
import type { AgreementTemplate } from '@/types/agreement'

const router = useRouter()
const ui = useOtherUiStore()
const svet = useSvetoforStore()
const mode = computed(() => ui.mode)

const { userDir, portalDomain, loadUserDir, udName, udInitials } = useUserDirectory()
const { pickerKind, pickUsers, pickDeal, onPickUser, onPickDeal } =
  useBitrixPicker(userDir, portalDomain)

const error = ref<string | null>(null)

// --- форма нового согласования ---
const form = ref({
  title: '', description: '', amount: '', deadline: '', crm_link: '',
  flow_type: 'parallel', internal_users: '',
})
const formFiles = ref<File[]>([])
const savingForm = ref(false)

// внешние участники — чипами
const externalList = ref<string[]>([])
const externalInput = ref('')
function addExternal() {
  const e = externalInput.value.trim()
  if (e && !externalList.value.includes(e)) externalList.value.push(e)
  externalInput.value = ''
}
function removeExternal(i: number) { externalList.value.splice(i, 1) }

// Внутренние участники как чипы (id → аватар + ФИО)
const internalChips = computed(() =>
  form.value.internal_users
    .split(',').map((s) => s.trim()).filter(Boolean)
    .map(Number).filter((n) => !Number.isNaN(n)),
)
function removeInternal(id: number) {
  form.value.internal_users = internalChips.value.filter((x) => x !== id).join(', ')
}

function pickBitrixUsers() {
  pickUsers((ids) => { form.value.internal_users = mergeIds(form.value.internal_users, ids) })
}
function pickBitrixDeal() {
  pickDeal((link) => { form.value.crm_link = link })
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
    form.value = {
      title: '', description: '', amount: '', deadline: '', crm_link: '',
      flow_type: 'parallel', internal_users: '',
    }
    externalList.value = []
    formFiles.value = []
    selectedTemplate.value = ''
    // Созданное согласование живёт в рабочем месте визирования — уходим туда и
    // сразу раскрываем карточку (тот же deep-link, что в письмах).
    svet.mode = 'in_progress'
    router.push({ path: '/svetofor', query: { open: String(created.id) } })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать'
  } finally {
    savingForm.value = false
  }
}

// --- шаблоны маршрута ---
const templates = ref<AgreementTemplate[]>([])
const selectedTemplate = ref<number | ''>('')
const templateName = ref('')
const templateScope = ref('private')
const savingTemplate = ref(false)
const loadingTemplates = ref(false)

async function loadTemplates() {
  loadingTemplates.value = true
  try {
    templates.value = await agreements.templates()
  } catch { /* не критично */ } finally {
    loadingTemplates.value = false
  }
}
function applyTemplate() {
  const t = templates.value.find((x) => x.id === selectedTemplate.value)
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
    if (Number.isNaN(id)) return
    parts.push({ type: 'internal', b24_user_id: id, email: '', name: '', order_index: idx })
    idx += 1
  })
  externalList.value.forEach((email) => {
    parts.push({ type: 'external', b24_user_id: null, email, name: '', order_index: idx })
    idx += 1
  })
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
    await agreements.createTemplate({
      name: templateName.value.trim(), scope: templateScope.value, participants: parts,
    })
    templateName.value = ''
    await loadTemplates()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить шаблон'
  } finally {
    savingTemplate.value = false
  }
}

onMounted(() => {
  loadUserDir()
  loadTemplates()
})
</script>

<template>
  <section>
    <!-- Поиск сотрудников/сделок через коннектор (вне iframe портала) -->
    <BitrixSearchModal
      v-if="pickerKind"
      :kind="pickerKind"
      @pick-user="onPickUser"
      @pick-deal="onPickDeal"
      @close="pickerKind = null"
    />

    <p v-if="error" class="state state--error" style="margin:0 0 10px">{{ error }}</p>

    <!-- Новое согласование -->
    <div v-if="mode === 'create'" class="form-card">
      <div class="fr">
        <label class="fr-label fr-req">Название</label>
        <input v-model="form.title" class="fr-input" />
      </div>

      <div class="fr">
        <label class="fr-label">Описание</label>
        <textarea v-model="form.description" class="fr-input" rows="3"></textarea>
      </div>

      <div class="fr">
        <label class="fr-label">Тип согласования</label>
        <label class="fr-radio">
          <input v-model="form.flow_type" type="radio" value="parallel" />
          Параллельное (все могут голосовать сразу)
        </label>
        <label class="fr-radio">
          <input v-model="form.flow_type" type="radio" value="sequential" />
          Последовательное (по очереди, в порядке добавления)
        </label>
      </div>

      <div class="fr-cols">
        <div class="fr">
          <label class="fr-label">Сумма</label>
          <input v-model="form.amount" class="fr-input" type="number" />
        </div>
        <div class="fr">
          <label class="fr-label">Дедлайн</label>
          <input v-model="form.deadline" class="fr-input" type="date" />
          <div class="fr-hint">Необязательное поле, используется для напоминаний.</div>
        </div>
      </div>

      <div class="fr">
        <label class="fr-label">Привязка к CRM</label>
        <div class="fr-inline">
          <input v-model="form.crm_link" class="fr-input" placeholder="Вставьте ссылку или выберите" />
          <button type="button" class="ag-btn ag-btn--blue" @click="pickBitrixDeal">Выбрать из CRM</button>
        </div>
        <div class="fr-hint">
          Можно вставить ссылку на сделку/счёт/контакт вручную или выбрать элемент CRM
          через диалог Битрикс24.
        </div>
      </div>

      <div class="fr">
        <label class="fr-label">Участники из Б24</label>
        <div class="fr-inline">
          <input v-model="form.internal_users" class="fr-input" placeholder="Например: 1, 25, 37" />
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
          <input
            v-model="externalInput" class="fr-input" type="email"
            placeholder="email@example.com" @keyup.enter="addExternal"
          />
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
        <label class="fr-label">Шаблон маршрута</label>
        <div class="fr-inline">
          <select v-model="selectedTemplate" class="fr-input" @change="applyTemplate">
            <option value="">— Не использовать шаблон —</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <button type="button" class="ag-btn ag-btn--soft" @click="loadTemplates">Обновить</button>
        </div>
        <div class="fr-hint">
          Шаблон подставляет только маршрут (список участников); сохранить набранный
          маршрут как шаблон можно на вкладке «Шаблоны».
        </div>
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
        <div class="fr-hint">
          Можно добавлять по одному в несколько заходов; лишние — убрать до отправки.
        </div>
      </div>

      <button class="btn btn--primary" :disabled="savingForm" @click="createApproval">
        {{ savingForm ? 'Создание…' : 'Создать и отправить' }}
      </button>
    </div>

    <!-- Шаблоны маршрутов -->
    <div v-else class="form-card">
      <p class="fr-hint" style="margin-top:0">
        Шаблон хранит только маршрут — список участников. Название и описание
        согласования задаются при создании.
      </p>

      <div class="fr">
        <label class="fr-label">Сохранить маршрут, набранный в форме</label>
        <div class="fr-inline">
          <input v-model="templateName" class="fr-input" placeholder="Название шаблона" />
          <select v-model="templateScope" class="fr-input" style="max-width:130px">
            <option value="private">Только мне</option>
            <option value="public">Всем</option>
          </select>
          <button
            type="button" class="ag-btn ag-btn--green"
            :disabled="savingTemplate" @click="saveTemplate"
          >{{ savingTemplate ? 'Сохранение…' : 'Сохранить' }}</button>
        </div>
        <div class="fr-hint">
          Берётся маршрут с вкладки «Новое согласование» —
          сейчас в нём {{ internalChips.length + externalList.length }} участник(ов).
        </div>
      </div>

      <p v-if="loadingTemplates" class="state">Загрузка…</p>
      <p v-else-if="templates.length === 0" class="state">Шаблонов пока нет.</p>
      <ul v-else class="item-list">
        <li v-for="t in templates" :key="t.id">
          <div class="item-card">
            <div class="item-title-row">
              <span class="item-title">{{ t.name }}</span>
              <span class="item-sub">{{ t.participants.length }} участник(ов)</span>
            </div>
            <div class="chips">
              <span v-for="(p, i) in t.participants" :key="i" class="chip">
                {{ p.type === 'internal' ? udName(p.b24_user_id) : p.email }}
              </span>
            </div>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.form-card {
  background: #fff; border: 1px solid #f1f1f1; border-radius: 10px;
  padding: 16px 18px; box-shadow: var(--shadow-soft); max-width: 720px;
}
.fr { margin-bottom: 18px; }
.fr-cols { display: flex; gap: 14px; }
.fr-cols .fr { flex: 1; }
.fr-label { display: block; font-size: 12px; font-weight: 500; margin-bottom: 4px; }
.fr-req::after { content: " *"; color: var(--red-main); }
.fr-input {
  width: 100%; box-sizing: border-box; padding: 8px 11px; border-radius: 4px;
  border: 1px solid #d0d0d0; font: inherit; font-size: 14px;
}
textarea.fr-input { resize: vertical; }
.fr-hint { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.fr-radio { display: block; font-size: 13px; margin: 4px 0; }
.fr-inline { display: flex; gap: 8px; align-items: center; }
.fr-inline .fr-input { flex: 1; min-width: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px;
  border-radius: 999px; background: #f1f3f4; font-size: 12px;
}
.chip--ext { background: #fff3e0; }
.chip--user { background: var(--green-light); color: #0a6e52; padding-left: 3px; }
.chip-ava {
  width: 20px; height: 20px; border-radius: 999px; background: #fff;
  color: var(--green-main); font-size: 10px; font-weight: 600;
  display: inline-flex; align-items: center; justify-content: center; flex: none;
}
.chip-x {
  border: none; background: transparent; cursor: pointer; font-size: 14px;
  line-height: 1; color: var(--text-muted); padding: 0;
}
.file-list { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.file-row {
  display: flex; align-items: center; gap: 8px; background: #f5f6f8;
  border-radius: 6px; padding: 5px 8px; font-size: 12.5px;
}
.file-name { flex: 1; overflow-wrap: anywhere; }
.ag-btn {
  font: inherit; font-size: 13px; cursor: pointer; border-radius: 6px;
  border: 1px solid var(--gray-border); background: #fff; color: var(--text-main);
  padding: 7px 12px;
}
.ag-btn:disabled { opacity: 0.5; cursor: default; }
.ag-btn--soft { background: #f1f1f1; border-color: #e0e0e0; color: #333; }
.ag-btn--green { background: var(--green-main); color: #fff; border-color: var(--green-main); }
.ag-btn--blue { background: #2f6fd6; color: #fff; border-color: #2f6fd6; white-space: nowrap; }
</style>
