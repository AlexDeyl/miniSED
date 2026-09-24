<script setup lang="ts">
// Анкета «Заявка на проверку лица» (ТЗ). Отдельно от RequestCreateView: там
// анкета представителя по доверенности, здесь — сведения о контрагенте или
// физлице, и общих полей у них почти нет. Юрлицо и объект заявки сервер
// выводит сам из «объекта сотрудничества» — в форме их не спрашиваем.
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'

const props = defineProps<{ id?: string }>()
const router = useRouter()

// --- справочники (совпадают с backend requests_reg/constants.py CHECK_*) ---
const PERSON_TYPES = [
  { code: 'legal', name: 'Юридическое лицо / ИП' },
  { code: 'individual', name: 'Физическое лицо (в том числе самозанятый)' },
]
const URGENCY = [
  { code: 'standard', name: 'Стандартная (3 раб. дня)' },
  { code: 'urgent', name: 'Срочная (1-2 раб. дня, с обоснованием)' },
]
const LEGAL_DIRECTIONS = [
  { code: 'supplier', name: 'Поставщик' },
  { code: 'buyer', name: 'Покупатель' },
]
const DIRECTIONS = [
  { code: 'supplier', name: 'Поставщик' },
  { code: 'buyer', name: 'Покупатель' },
  { code: 'employee', name: 'Сотрудник' },
  { code: 'npd', name: 'НПД (самозанятый)' },
]
const CONTRACT_KINDS = [
  { code: 'standard', name: 'Стандартный' },
  { code: 'counterparty', name: 'По форме контрагента' },
]
const PLACES = [
  { code: 'multiple', name: 'Несколько объектов (указать в графе «Иная информация»)' },
  { code: 'vvedensky', name: 'Отель «Введенский»' },
  { code: 'demetra', name: 'Отель «Деметра Арт Отель»' },
  { code: 'svet', name: 'Отель «SVET»' },
  { code: 'saga', name: 'Отель «SAGA»' },
  { code: 'dom', name: 'Отель «DOM BOUTIQUE HOTEL»' },
  { code: 'nevesomost', name: 'Невесомость' },
]
// у физлица «несколько объектов» по ТЗ не предусмотрено
const INDIVIDUAL_PLACES = PLACES.filter((p) => p.code !== 'multiple')
// Приложения — все необязательные; код уходит в document_type файла.
const ATTACHMENTS = [
  { code: 'check_anketa', name: 'Анкета / Реквизиты' },
  { code: 'check_pd_consent', name: 'Согласие на обработку персональных данных' },
  { code: 'check_urgency', name: 'Обоснование срочности' },
  { code: 'check_other', name: 'Иной документ' },
]

const data = reactive({
  person_type: 'legal',
  urgency: 'standard',
  legal: {
    name: '', inn_ogrn: '', direction: '', contract_kind: '', place: '', other_info: '',
  },
  individual: {
    last_name: '', first_name: '', middle_name: '', birth_date: '',
    passport: '', position: '', place: '',
  },
  // Раздел 2: направление — у физлица (у юрлица оно уже в разделе 1)
  direction: '',
  coop_info: '',
})
const isIndividual = computed(() => data.person_type === 'individual')

// Дата подачи — автоматически: сегодня, а при правке — дата создания заявки.
const createdAt = ref<string | null>(null)
const submitDate = computed(() =>
  new Date(createdAt.value || Date.now()).toLocaleDateString('ru-RU'),
)
const todayStr = new Date().toISOString().slice(0, 10)

const files = reactive<Record<string, File[]>>({})
function onFiles(code: string, e: Event) {
  files[code] = Array.from((e.target as HTMLInputElement).files || [])
}

const saving = ref(false)
const error = ref<string | null>(null)

// Паспорт — «0000 000000»: пробел после серии ставим сами.
function onPassportInput() {
  const d = data.individual.passport.replace(/\D/g, '').slice(0, 10)
  data.individual.passport = d.length > 4 ? `${d.slice(0, 4)} ${d.slice(4)}` : d
}

onMounted(async () => {
  if (!props.id) return
  try {
    const r = await requests.get(props.id)
    createdAt.value = r.created_at
    const src = (r.data || {}) as Record<string, unknown>
    for (const [k, v] of Object.entries(src)) {
      if ((k === 'legal' || k === 'individual') && v && typeof v === 'object') {
        Object.assign(data[k], v)
      } else if (k in data) {
        ;(data as Record<string, unknown>)[k] = v
      }
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить заявку'
  }
})

// Те же правила проверяет сервер (requests_reg/check.py data_error).
function validate(): string | null {
  if (!data.urgency) return 'Укажите срочность.'
  if (!isIndividual.value) {
    const l = data.legal
    if (!l.name.trim()) return 'Раздел 1: укажите наименование.'
    const inn = l.inn_ogrn.replace(/\D/g, '')
    if (!inn) return 'Раздел 1: укажите ИНН / ОГРН.'
    if (![10, 12, 13, 15].includes(inn.length))
      return 'Раздел 1: ИНН — 10 или 12 цифр, ОГРН — 13 или 15.'
    if (!l.direction) return 'Раздел 1: укажите направление планируемой деятельности.'
    if (!l.contract_kind) return 'Раздел 1: укажите вид планируемого договора.'
    if (!l.place) return 'Раздел 1: укажите объект, на котором планируется сотрудничество.'
    if (l.place === 'multiple' && !l.other_info.trim())
      return 'Раздел 1: выбрано «Несколько объектов» — перечислите их в графе «Иная информация».'
    return null
  }
  const i = data.individual
  if (!i.last_name.trim()) return 'Раздел 1: укажите фамилию.'
  if (!i.first_name.trim()) return 'Раздел 1: укажите имя.'
  if (!i.birth_date) return 'Раздел 1: укажите дату рождения.'
  if (i.birth_date > todayStr) return 'Раздел 1: дата рождения не может быть в будущем.'
  if (i.passport.replace(/\D/g, '').length !== 10)
    return 'Раздел 1: паспорт — 10 цифр (серия 4 + номер 6).'
  if (!i.position.trim()) return 'Раздел 1: укажите должность.'
  if (!i.place) return 'Раздел 1: укажите место сотрудничества.'
  if (!data.direction) return 'Раздел 2: укажите направление деятельности.'
  return null
}

async function save() {
  error.value = validate()
  if (error.value) return
  saving.value = true
  // В анкету кладём только ветку выбранного типа лица: паспорт физлица не
  // должен остаться висеть в заявке на юрлицо после переключения типа.
  const payloadData = isIndividual.value
    ? { person_type: data.person_type, urgency: data.urgency, individual: { ...data.individual },
        direction: data.direction, coop_info: data.coop_info.trim() }
    : { person_type: data.person_type, urgency: data.urgency, legal: { ...data.legal },
        coop_info: data.coop_info.trim() }
  let saved
  try {
    saved = props.id
      ? await requests.update(props.id, { data: payloadData })
      : await requests.create({ request_type: 'check', data: payloadData })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить'
    saving.value = false
    return
  }
  try {
    const jobs: Promise<unknown>[] = []
    for (const a of ATTACHMENTS) {
      for (const f of files[a.code] || []) {
        jobs.push(requests.uploadDocument(saved.id, f, `${a.name}: ${f.name}`, a.code))
      }
    }
    await Promise.all(jobs)
  } catch {
    error.value = 'Заявка сохранена, но часть файлов не загрузилась — добавьте их в карточке.'
  }
  router.push(`/requests/${saved.id}`)
}
</script>

<template>
  <div class="form" style="max-width:760px">
    <div class="detail-card">
      <div class="detail-card-header">Заявка</div>
      <div class="form-row">
        <label class="form-field">
          <span>Тип лица *</span>
          <select v-model="data.person_type">
            <option v-for="t in PERSON_TYPES" :key="t.code" :value="t.code">{{ t.name }}</option>
          </select>
        </label>
        <label class="form-field" style="max-width:200px">
          <span>Дата подачи заявки</span>
          <input :value="submitDate" disabled />
        </label>
      </div>
      <div class="form-field">
        <span>Срочность *</span>
        <label v-for="u in URGENCY" :key="u.code" class="check">
          <input type="radio" :value="u.code" v-model="data.urgency" /> {{ u.name }}
        </label>
        <div v-if="data.urgency === 'urgent'" class="attach-hint">
          Приложите обоснование срочности в разделе 3.
        </div>
      </div>
    </div>

    <!-- Раздел 1: юрлицо / ИП -->
    <div v-if="!isIndividual" class="detail-card">
      <div class="detail-card-header">Раздел 1. Сведения о проверяемом лице</div>
      <label class="form-field" style="margin-bottom:10px">
        <span>Наименование *</span>
        <input v-model="data.legal.name" placeholder="ООО «Ромашка» / ИП Иванов И.И." />
      </label>
      <div class="form-row">
        <label class="form-field">
          <span>ИНН / ОГРН *</span>
          <input v-model="data.legal.inn_ogrn" inputmode="numeric" maxlength="32" placeholder="ИНН или ОГРН" />
        </label>
        <label class="form-field">
          <span>Направление планируемой деятельности *</span>
          <select v-model="data.legal.direction">
            <option value="" disabled>—</option>
            <option v-for="d in LEGAL_DIRECTIONS" :key="d.code" :value="d.code">{{ d.name }}</option>
          </select>
        </label>
      </div>
      <div class="form-row">
        <label class="form-field">
          <span>Вид планируемого договора *</span>
          <select v-model="data.legal.contract_kind">
            <option value="" disabled>—</option>
            <option v-for="k in CONTRACT_KINDS" :key="k.code" :value="k.code">{{ k.name }}</option>
          </select>
        </label>
        <label class="form-field">
          <span>Объект, на котором планируется сотрудничество *</span>
          <select v-model="data.legal.place">
            <option value="" disabled>—</option>
            <option v-for="p in PLACES" :key="p.code" :value="p.code">{{ p.name }}</option>
          </select>
        </label>
      </div>
      <label class="form-field">
        <span>Иная информация{{ data.legal.place === 'multiple' ? ' *' : '' }}</span>
        <textarea
          v-model="data.legal.other_info" rows="3"
          :placeholder="data.legal.place === 'multiple' ? 'Перечислите объекты сотрудничества' : ''"
        />
      </label>
    </div>

    <!-- Раздел 1: физлицо -->
    <div v-else class="detail-card">
      <div class="detail-card-header">Раздел 1. Сведения о проверяемом лице</div>
      <div class="form-row">
        <label class="form-field"><span>Фамилия *</span><input v-model="data.individual.last_name" /></label>
        <label class="form-field"><span>Имя *</span><input v-model="data.individual.first_name" /></label>
        <label class="form-field"><span>Отчество</span><input v-model="data.individual.middle_name" /></label>
      </div>
      <div class="form-row">
        <label class="form-field">
          <span>Дата рождения *</span>
          <input v-model="data.individual.birth_date" type="date" :max="todayStr" />
        </label>
        <label class="form-field">
          <span>Данные паспорта *</span>
          <input
            v-model="data.individual.passport" @input="onPassportInput"
            inputmode="numeric" maxlength="11" placeholder="0000 000000"
          />
        </label>
      </div>
      <div class="form-row">
        <label class="form-field"><span>Должность *</span><input v-model="data.individual.position" /></label>
        <label class="form-field">
          <span>Место сотрудничества *</span>
          <select v-model="data.individual.place">
            <option value="" disabled>—</option>
            <option v-for="p in INDIVIDUAL_PLACES" :key="p.code" :value="p.code">{{ p.name }}</option>
          </select>
        </label>
      </div>
    </div>

    <!-- Раздел 2 -->
    <div class="detail-card">
      <div class="detail-card-header">Раздел 2. Сведения о сотрудничестве</div>
      <label v-if="isIndividual" class="form-field" style="margin-bottom:10px;max-width:360px">
        <span>Направление деятельности *</span>
        <select v-model="data.direction">
          <option value="" disabled>—</option>
          <option v-for="d in DIRECTIONS" :key="d.code" :value="d.code">{{ d.name }}</option>
        </select>
      </label>
      <label class="form-field">
        <span>Иная информация о сотрудничестве</span>
        <textarea v-model="data.coop_info" rows="3" />
      </label>
    </div>

    <!-- Раздел 3 -->
    <div class="detail-card">
      <div class="detail-card-header">Раздел 3. Приложения к заявке</div>
      <div class="attach-hint">
        Все приложения необязательны.<template v-if="props.id"> Уже загруженные файлы
        остаются в карточке — здесь добавляются новые.</template>
      </div>
      <div v-for="(a, i) in ATTACHMENTS" :key="a.code" class="attach-row">
        <span class="attach-name">{{ i + 1 }}. {{ a.name }}</span>
        <label class="btn btn--soft attach-btn">
          Загрузить
          <input type="file" multiple style="display:none" @change="onFiles(a.code, $event)" />
        </label>
        <span v-if="files[a.code]?.length" class="attach-ok">
          ✓ {{ files[a.code].map((f) => f.name).join(', ') }}
        </span>
      </div>
    </div>

    <p v-if="error" class="state state--error">{{ error }}</p>
    <div class="row-actions">
      <button class="btn btn--primary" :disabled="saving" @click="save">
        {{ saving ? 'Сохранение…' : props.id ? 'Сохранить' : 'Создать черновик' }}
      </button>
      <RouterLink v-if="props.id" :to="`/requests/${props.id}`" class="btn btn--ghost">Отмена</RouterLink>
    </div>
    <p v-if="!props.id" class="attach-hint" style="margin-top:8px">
      Черновик можно проверить в карточке и затем отправить на согласование.
    </p>
  </div>
</template>

<style scoped>
.check { display: block; font-size: 13px; margin: 3px 0; cursor: pointer; }
.check input { margin-right: 6px; }
.attach-hint { font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
.attach-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 6px 0; }
.attach-name { min-width: 300px; font-size: 13px; }
.attach-btn { cursor: pointer; padding: 4px 12px; font-size: 12.5px; }
.attach-ok { font-size: 12px; color: var(--green-main); }
</style>
