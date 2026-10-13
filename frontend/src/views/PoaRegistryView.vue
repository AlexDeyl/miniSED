<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError } from '@/services/api'
import {
  poaRegistry,
  type Numbering,
  type RegistryChange,
  type RegistryEntry,
  type RegistryEntryInput,
  type RegistryMeta,
  type Validity,
} from '@/services/poaRegistry'
import { useRegistryUiStore } from '@/stores/registryUi'
import { useAdminModeStore } from '@/stores/adminMode'
import SearchBox from '@/components/SearchBox.vue'

// Реестр доверенностей и МЧД — по форме Excel-реестра юротдела: подсветка
// срока действия, графы из заявки, которые юрист уточняет. Статус в Мини-СЭД
// берётся из заявки живьём.
const ui = useRegistryUiStore()
const adminMode = useAdminModeStore()

const meta = ref<RegistryMeta | null>(null)
const items = ref<RegistryEntry[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const query = ref('')
const organization = ref<number | ''>('')
const validity = ref<Validity | ''>('')
// «Подсветка сроков» — как флажок в Excel-реестре
const highlight = ref(true)

const filters = computed(() => ({
  kind: ui.kind, organization: organization.value, validity: validity.value, q: query.value,
}))
const showMchdCols = computed(() => ui.kind !== 'poa')
const showKindCol = computed(() => ui.kind === '')

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await poaRegistry.list(filters.value)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить реестр'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try { meta.value = await poaRegistry.meta() } catch { /* реестр покажет ошибку сам */ }
  await load()
})
watch([filters, () => adminMode.active], load, { deep: true })

function fmt(d: string | null): string {
  if (!d) return ''
  const [y, m, day] = d.slice(0, 10).split('-')
  return `${day}.${m}.${y}`
}
function fmtTime(d: string): string {
  return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

// --- карточка записи (правка / новая) ---
const editing = ref<RegistryEntry | null>(null)
const creating = ref(false)
const form = reactive<RegistryEntryInput>({})
const saving = ref(false)
const formError = ref<string | null>(null)
const history = ref<RegistryChange[] | null>(null)

const FIELDS = [
  'kind', 'organization', 'number', 'reg_number', 'issue_date', 'code',
  'representative', 'powers', 'valid_until', 'cert_valid_until', 'revoked_at', 'comment',
] as const

function resetForm(src?: RegistryEntry) {
  for (const f of FIELDS) {
    ;(form as Record<string, unknown>)[f] = src ? src[f] ?? '' : ''
  }
  form.assign_number = !src
  if (!src) {
    form.kind = ui.kind || 'poa'
    form.organization = organization.value || meta.value?.organizations[0]?.id
    form.issue_date = meta.value?.today ?? ''
  }
}

async function open(e: RegistryEntry) {
  editing.value = e
  creating.value = false
  formError.value = null
  history.value = null
  resetForm(e)
  if (meta.value?.can_history) {
    try { history.value = await poaRegistry.history(e.id) } catch { history.value = [] }
  }
}
function openNew() {
  editing.value = null
  creating.value = true
  formError.value = null
  history.value = null
  resetForm()
}
function close() {
  editing.value = null
  creating.value = false
}

// пустые даты — null, иначе DRF не примет ''
function payload(): RegistryEntryInput {
  const out: Record<string, unknown> = { ...form }
  for (const f of ['issue_date', 'valid_until', 'cert_valid_until', 'revoked_at']) {
    if (!out[f]) out[f] = null
  }
  if (!creating.value) delete out.assign_number
  return out as RegistryEntryInput
}

async function save() {
  saving.value = true
  formError.value = null
  try {
    if (creating.value) await poaRegistry.create(payload())
    else if (editing.value) await poaRegistry.update(editing.value.id, payload())
    close()
    await load()
  } catch (e) {
    formError.value = e instanceof ApiError ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function removeEntry() {
  if (!editing.value || !confirm('Удалить запись из реестра?')) return
  try {
    await poaRegistry.remove(editing.value.id)
    close()
    await load()
  } catch (e) {
    formError.value = e instanceof ApiError ? e.message : 'Не удалось удалить'
  }
}

// --- нумерация ---
const numberingOpen = ref(false)
const numbering = ref<Numbering[]>([])
const numberingError = ref<string | null>(null)
async function openNumbering() {
  numberingOpen.value = true
  numberingError.value = null
  try { numbering.value = await poaRegistry.numbering() } catch (e) {
    numberingError.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  }
}
async function saveNumbering(n: Numbering) {
  numberingError.value = null
  try {
    numbering.value = await poaRegistry.setNumbering(n.organization, {
      mask: n.mask, last_seq: Number(n.last_seq),
    })
  } catch (e) {
    numberingError.value = e instanceof ApiError ? e.message : 'Не удалось сохранить'
  }
}

const exporting = ref(false)
async function doExport() {
  exporting.value = true
  try { await poaRegistry.export(filters.value) } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось выгрузить'
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <section class="reg">
    <Teleport to="#header-actions">
      <button class="btn btn--soft" :disabled="exporting" @click="doExport">Выгрузить в Excel</button>
      <button v-if="meta?.can_edit" class="btn btn--soft" @click="openNumbering">Нумерация</button>
      <button v-if="meta?.can_edit" class="btn btn--primary" @click="openNew">+ Добавить запись</button>
    </Teleport>

    <div class="reg-toolbar">
      <div class="reg-today">
        Текущая дата: <b>{{ fmt(meta?.today ?? null) }}</b>
      </div>
      <select v-model="organization" class="reg-select">
        <option value="">Все компании</option>
        <option v-for="o in meta?.organizations ?? []" :key="o.id" :value="o.id">{{ o.short_name }}</option>
      </select>
      <select v-model="validity" class="reg-select">
        <option value="">Любой срок</option>
        <option v-for="v in meta?.validity ?? []" :key="v.code" :value="v.code">{{ v.name }}</option>
      </select>
      <label class="reg-check"><input v-model="highlight" type="checkbox" /> Подсветка сроков</label>
    </div>
    <SearchBox v-model="query" placeholder="Поиск: номер, представитель, полномочия, КОД, рег. №, заявка" />

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">
      {{ query || organization || validity ? 'Ничего не найдено.' : 'В реестре пока нет записей.' }}
    </p>

    <div v-else class="reg-scroll">
      <table class="reg-table">
        <thead>
          <tr>
            <th>Компания</th>
            <th v-if="showKindCol">Вид</th>
            <th>№</th>
            <th v-if="showMchdCols">Рег. № (ФНС)</th>
            <th>Дата выдачи</th>
            <th>КОД</th>
            <th>Представитель</th>
            <th class="reg-powers-col">Полномочия</th>
            <th>Срок действия</th>
            <th v-if="showMchdCols">Срок сертификата</th>
            <th>Статус</th>
            <th>Статус в Мини-СЭД</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in items" :key="e.id" @click="open(e)">
            <td>{{ e.organization_name }}</td>
            <td v-if="showKindCol">{{ e.kind_display }}</td>
            <td class="nowrap"><b>{{ e.number || '—' }}</b></td>
            <td v-if="showMchdCols" class="reg-guid">{{ e.reg_number }}</td>
            <td class="nowrap">{{ fmt(e.issue_date) }}</td>
            <td>{{ e.code }}</td>
            <td>{{ e.representative }}</td>
            <td class="reg-powers" :title="e.powers">{{ e.powers }}</td>
            <td class="nowrap reg-term" :class="highlight ? `v-${e.validity}` : ''">{{ fmt(e.valid_until) }}</td>
            <td v-if="showMchdCols" class="nowrap">{{ fmt(e.cert_valid_until) }}</td>
            <td class="nowrap">{{ e.validity_display }}</td>
            <td>
              <RouterLink v-if="e.request" :to="`/requests/${e.request}`" @click.stop>
                {{ e.request_status_display }}
              </RouterLink>
              <span v-else class="muted">{{ e.request_status_display }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!loading && items.length" class="state">Записей: {{ items.length }}</p>

    <!-- Карточка записи -->
    <div v-if="editing || creating" class="reg-overlay" @click.self="close">
      <div class="reg-panel">
        <div class="reg-panel-head">
          <div>
            <div class="reg-panel-title">
              {{ creating ? 'Новая запись реестра' : (editing?.number || 'Запись без номера') }}
            </div>
            <div v-if="editing?.request" class="reg-panel-sub">
              Заявка <RouterLink :to="`/requests/${editing.request}`">{{ editing.request_number }}</RouterLink>
              · {{ editing.request_status_display }}
            </div>
            <div v-else-if="editing" class="reg-panel-sub">Внесена вручную</div>
          </div>
          <button class="btn btn--ghost" @click="close">✕</button>
        </div>

        <fieldset class="reg-form" :disabled="!meta?.can_edit">
          <div class="form-row">
            <label class="form-field"><span>Вид</span>
              <select v-model="form.kind">
                <option v-for="k in meta?.kinds ?? []" :key="k.code" :value="k.code">{{ k.name }}</option>
              </select>
            </label>
            <label class="form-field"><span>Компания</span>
              <select v-model="form.organization">
                <option v-for="o in meta?.organizations ?? []" :key="o.id" :value="o.id">{{ o.short_name }}</option>
              </select>
            </label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Номер доверенности</span>
              <input v-model="form.number" :placeholder="creating && form.assign_number ? 'присвоится по маске' : ''" />
            </label>
            <label class="form-field"><span>Дата выдачи</span>
              <input v-model="form.issue_date" type="date" />
            </label>
          </div>
          <label v-if="creating" class="reg-check">
            <input v-model="form.assign_number" type="checkbox" />
            Присвоить следующий номер по маске компании (если номер не указан)
          </label>
          <label v-if="form.kind === 'mchd'" class="form-field"><span>Рег. № МЧД (ФНС)</span>
            <input v-model="form.reg_number" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
          </label>
          <div class="form-row">
            <label class="form-field"><span>КОД</span><input v-model="form.code" /></label>
            <label class="form-field"><span>Представитель</span><input v-model="form.representative" /></label>
          </div>
          <label class="form-field"><span>Полномочия</span>
            <textarea v-model="form.powers" rows="6"></textarea>
          </label>
          <div class="form-row">
            <label class="form-field"><span>Срок действия</span>
              <input v-model="form.valid_until" type="date" />
            </label>
            <label v-if="form.kind === 'mchd'" class="form-field"><span>Срок сертификата</span>
              <input v-model="form.cert_valid_until" type="date" />
            </label>
            <label class="form-field"><span>Отозвана с</span>
              <input v-model="form.revoked_at" type="date" />
            </label>
          </div>
          <label class="form-field"><span>Примечание</span>
            <textarea v-model="form.comment" rows="2"></textarea>
          </label>
        </fieldset>

        <p v-if="formError" class="state state--error">{{ formError }}</p>
        <div v-if="meta?.can_edit" class="reg-actions">
          <button class="btn btn--primary" :disabled="saving" @click="save">Сохранить</button>
          <button class="btn" @click="close">Отмена</button>
          <button v-if="editing && !editing.request" class="btn btn--danger reg-del" @click="removeEntry">
            Удалить
          </button>
        </div>

        <!-- Журнал правок — только суперпользователю (ТЗ) -->
        <div v-if="history !== null" class="reg-history">
          <div class="reg-history-title">История правок</div>
          <p v-if="!history.length" class="state">Правок не было.</p>
          <table v-else class="round-table">
            <thead><tr><th>Когда</th><th>Кто</th><th>Графа</th><th>Было</th><th>Стало</th></tr></thead>
            <tbody>
              <tr v-for="c in history" :key="c.id">
                <td class="nowrap">{{ fmtTime(c.changed_at) }}</td>
                <td>{{ c.changed_by_name || (c.changed_by_b24_id ? `USER #${c.changed_by_b24_id}` : '—') }}</td>
                <td>{{ c.field_display }}</td>
                <td class="reg-pre">{{ c.old_value || '—' }}</td>
                <td class="reg-pre">{{ c.new_value || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Нумерация: маски и счётчики компаний -->
    <div v-if="numberingOpen" class="reg-overlay" @click.self="numberingOpen = false">
      <div class="reg-panel reg-panel--wide">
        <div class="reg-panel-head">
          <div>
            <div class="reg-panel-title">Нумерация доверенностей</div>
            <div class="reg-panel-sub">
              Номер присваивается при «Взять в работу». {ХХ} — порядковый номер в году (общий для
              доверенностей и МЧД компании), {ГГГГ} — год, {ГГ} — две цифры года, {ММ} — месяц.
              «Последний номер» — чтобы продолжить нумерацию, начатую до Мини-СЭД.
            </div>
          </div>
          <button class="btn btn--ghost" @click="numberingOpen = false">✕</button>
        </div>
        <p v-if="numberingError" class="state state--error">{{ numberingError }}</p>
        <table class="round-table">
          <thead><tr><th>Компания</th><th>Маска</th><th>Последний номер {{ numbering[0]?.year }}</th><th>Следующий</th><th></th></tr></thead>
          <tbody>
            <tr v-for="n in numbering" :key="n.organization">
              <td>{{ n.organization_name }}</td>
              <td><input v-model="n.mask" class="reg-input" /></td>
              <td><input v-model.number="n.last_seq" type="number" min="0" class="reg-input reg-input--num" /></td>
              <td class="nowrap"><b>{{ n.next_number }}</b></td>
              <td><button class="btn btn--soft" @click="saveNumbering(n)">Сохранить</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.reg-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 10px; }
.reg-today { background: #5b9bd5; color: #fff; border-radius: 6px; padding: 6px 12px; font-size: 13px; }
.reg-select { padding: 6px 10px; border: 1px solid var(--gray-border); border-radius: 6px; background: #fff; font-size: 13px; }
.reg-check { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }

.reg-scroll { overflow-x: auto; background: #fff; border: 1px solid #f1f1f1; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-top: 10px; }
.reg-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.reg-table th {
  background: #5b9bd5; color: #fff; font-weight: 500; text-align: left;
  padding: 8px; vertical-align: bottom; white-space: nowrap; position: sticky; top: 0;
}
.reg-table td { padding: 7px 8px; border-bottom: 1px solid #e6eef7; vertical-align: top; }
.reg-table tbody tr:nth-child(odd) td { background: #f3f7fc; }
.reg-table tbody tr { cursor: pointer; }
.reg-table tbody tr:hover td { background: var(--green-light); }
.reg-powers-col { min-width: 280px; }
.reg-powers {
  white-space: pre-line; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
  overflow: hidden; max-width: 460px;
}
.reg-guid { font-family: ui-monospace, monospace; font-size: 12px; }
.nowrap { white-space: nowrap; }
.muted { color: var(--text-muted); }

/* подсветка срока — цвета Excel-реестра юротдела */
.reg-table tbody tr td.reg-term.v-active { background: #a9d08e; }
.reg-table tbody tr td.reg-term.v-expiring { background: #ffd966; }
.reg-table tbody tr td.reg-term.v-expired { background: #a52a2a; color: #fff; }
.reg-table tbody tr td.reg-term.v-revoked { background: #bfbfbf; text-decoration: line-through; }

.reg-overlay {
  position: fixed; inset: 0; background: rgba(32,33,36,.35); z-index: 50;
  display: flex; justify-content: flex-end;
}
.reg-panel {
  background: #fff; width: min(620px, 100%); height: 100%; overflow-y: auto;
  padding: 20px 22px; box-shadow: -2px 0 12px rgba(0,0,0,.12);
  display: flex; flex-direction: column; gap: 14px;
}
.reg-panel--wide { width: min(900px, 100%); }
.reg-panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.reg-panel-title { font-size: 17px; font-weight: 600; }
.reg-panel-sub { font-size: 13px; color: var(--text-muted); margin-top: 4px; line-height: 1.45; }
.reg-form { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 14px; }
.reg-actions { display: flex; gap: 8px; }
.reg-del { margin-left: auto; }
.reg-history { border-top: 1px solid var(--gray-border); padding-top: 12px; }
.reg-history-title { font-weight: 600; margin-bottom: 6px; }
.reg-pre { white-space: pre-line; max-width: 180px; }
.reg-input { padding: 5px 8px; border: 1px solid var(--gray-border); border-radius: 6px; font-size: 13px; width: 100%; }
.reg-input--num { width: 80px; }
</style>
