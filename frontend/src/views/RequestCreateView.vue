<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { requests, type Cfo, type Facility, type Organization } from '@/services/requests'
import { ApiError } from '@/services/api'
import type { RequestType } from '@/types/request'
import AddressAutocomplete from '@/components/AddressAutocomplete.vue'
import { formatSnils, isValidInn, isValidSnils } from '@/utils/personal'

const router = useRouter()

// --- справочники анкеты (совпадают с backend requests_reg/constants.py) ---
const POA_TYPES = [
  { code: 'single', name: 'Разовая' }, { code: 'special', name: 'Специальная' },
  { code: 'general', name: 'Генеральная' }, { code: 'mchd', name: 'МЧД (машиночитаемая)' },
]
const URGENCY = [
  { code: 'standard', name: 'Стандартная (3 раб. дня)' },
  { code: 'urgent', name: 'Срочная (1-2 раб. дня, с обоснованием)' },
]
const REP_STATUS = [
  { code: 'employee', name: 'Сотрудник Общества' },
  { code: 'external', name: 'Лицо, не являющееся сотрудником' },
]
const POWERS = [
  { code: 'contracts', name: 'Подписание договоров, доп. соглашений, приложений' },
  { code: 'acts', name: 'Подписание актов работ / услуг' },
  { code: 'invoices', name: 'Подписание счетов, счетов-фактур, УПД' },
  { code: 'goods', name: 'Получение ТМЦ, документов' },
  { code: 'court', name: 'Представление в суде, арбитраже, госорганах' },
  { code: 'applications', name: 'Подача заявлений, запросов, получение ответов' },
]
const FORMS = [
  { code: 'standard', name: 'Стандартная форма (шаблон Общества)' },
  { code: 'counterparty', name: 'Форма контрагента / госоргана' },
  { code: 'mchd', name: 'МЧД' },
]
const ATTACHMENTS = [
  { code: 'sample', name: 'Образец / форма от контрагента' },
  { code: 'passport', name: 'Копия паспорта представителя' },
  { code: 'charter', name: 'Копия устава / доверенности' },
  { code: 'memo', name: 'Служебная записка (срочность)' },
]
// Приложения к заявке на ЭЦП (ТЗ, раздел 2) — свой список, у доверенности он
// про образец формы и устав, а здесь про документы физлица.
const ECP_ATTACHMENTS = [
  { code: 'passport', name: 'Копия паспорта представителя (для не-сотрудников)' },
  { code: 'snils', name: 'Копия СНИЛС представителя (для не-сотрудников)' },
  { code: 'inn', name: 'Копия ИНН представителя (для не-сотрудников)' },
  { code: 'memo', name: 'Служебная записка с обоснованием срочности' },
  { code: 'other', name: 'Иное' },
]
const ECP_RECEIVE = [
  { code: 'personally', name: 'Получить лично' },
  { code: 'courier', name: 'Получить через курьера (третье лицо)' },
  { code: 'other', name: 'Иным способом' },
]
const RECEIVE = [
  { code: 'electronic', name: 'Электронно (МЧД / файл с ЭП)' },
  { code: 'paper', name: 'Бумажный (лично / курьером)' },
  { code: 'edo', name: 'Направить по ЭДО' },
]

const requestType = ref<RequestType>('poa')
const organization = ref<number | null>(null)
const facility = ref<number | null>(null)
const cfo = ref<number | null>(null)
const basis = ref('')
const deptMsg = ref('')

// Код подразделения (XXX-XXX) → подтягиваем «кем выдан» из справочника ФМС (DaData).
async function onDeptCode() {
  const digits = (rep.passport_department_code || '').replace(/\D/g, '')
  if (digits.length !== 6) { deptMsg.value = ''; return }
  rep.passport_department_code = digits.slice(0, 3) + '-' + digits.slice(3)
  deptMsg.value = 'ищем подразделение…'
  try {
    const results = await requests.fmsUnit(rep.passport_department_code)
    if (results.length) {
      rep.passport_issued_by = results[0].value
      deptMsg.value = results.length > 1 ? `подставлено (найдено вариантов: ${results.length})` : 'подставлено автоматически'
    } else {
      deptMsg.value = 'подразделение не найдено — заполните вручную'
    }
  } catch {
    deptMsg.value = ''
  }
}

const data = reactive<Record<string, unknown>>({
  poa_type: 'single', urgency: 'standard', planned_date: '',
  // ЭЦП: тип пока свободным текстом — перечень согласуется с ИТ (ТЗ: «нужно
  // обсудить с ИТ»), поэтому жёсткого справочника здесь намеренно нет.
  ecp_type: '',
  rep: {
    last_name: '', first_name: '', middle_name: '', birth_date: '', status: 'employee',
    position: '', phone: '', email: '', inn: '', snils: '',
    passport: '', passport_department_code: '',
    passport_issued_by: '', passport_issue_date: '', reg_address: '',
  },
  rep_legal: { name: '', ogrn: '', inn: '', kpp: '', address: '', acting_person: '' },
  target_org: '', powers: [], power_templates: [], powers_other: '',
  peredoverie: 'without', term_type: 'single', term_from: '', term_to: '',
  form: 'standard', attachments: [], receive: 'paper',
})
const rep = data.rep as Record<string, string>
const legal = data.rep_legal as Record<string, string>

const orgs = ref<Organization[]>([])
const facilities = ref<Facility[]>([])
const cfos = ref<Cfo[]>([])
const templates = ref<{ code: string; name: string; powers: string }[]>([])
const saving = ref(false)
const error = ref<string | null>(null)

// Файлы-приложения: по одному на пункт чек-листа + произвольные «прочие».
// Грузятся после создания заявки, чтобы у юристов был полный комплект.
const attachmentFiles = reactive<Record<string, File | null>>({})
const extraFiles = ref<File[]>([])
function onAttachmentFile(code: string, e: Event) {
  attachmentFiles[code] = (e.target as HTMLInputElement).files?.[0] || null
}
function onExtraFiles(e: Event) {
  extraFiles.value = Array.from((e.target as HTMLInputElement).files || [])
}
async function uploadAttachments(reqId: number) {
  const jobs: Promise<unknown>[] = []
  for (const a of ATTACHMENTS) {
    const f = attachmentFiles[a.code]
    if (f) jobs.push(requests.uploadDocument(reqId, f, a.name))
  }
  extraFiles.value.forEach((f) => jobs.push(requests.uploadDocument(reqId, f, f.name)))
  if (jobs.length) await Promise.all(jobs)
}

// Анкета (сведения о представителе) одинакова у всех трёх типов; различаются
// только «параметры» сверху и дополнительный раздел снизу.
const isAnketa = computed(() => ['poa', 'mchd', 'ecp'].includes(requestType.value))
const isEcp = computed(() => requestType.value === 'ecp')
// Список приложений зависит от типа заявки, механика загрузки файлов общая.
const attachmentList = computed(() => (isEcp.value ? ECP_ATTACHMENTS : ATTACHMENTS))
// ИНН и СНИЛС нужны только машиночитаемой доверенности: для бумажной
// представителя удостоверяет паспорт. «МЧД» в форме говорится в трёх местах —
// тип заявки, тип доверенности и форма выдачи; инициатор пользуется любым,
// поэтому смотрим на все три (та же логика на сервере).
const isMchd = computed(() =>
  requestType.value === 'mchd'
  || data.poa_type === 'mchd'
  || data.form === 'mchd',
)

// СНИЛС приводим к привычному виду XXX-XXX-XXX YY, как код подразделения.
function onSnilsBlur() {
  rep.snils = formatSnils(rep.snils)
}

// Максимальная дата окончания срока — не более 3 лет от даты начала.
const maxTermTo = computed(() => {
  if (!data.term_from) return ''
  const d = new Date(data.term_from as string)
  d.setFullYear(d.getFullYear() + 3)
  return d.toISOString().slice(0, 10)
})

// Даты в формате ISO (yyyy-mm-dd) сравниваются как строки — этого достаточно.
const todayStr = new Date().toISOString().slice(0, 10)
function isoMinusYears(years: number): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - years)
  return d.toISOString().slice(0, 10)
}

async function loadContext() {
  const org = organization.value ?? undefined
  facilities.value = await requests.facilities(org)
  // Показываем ЦФО без организации (надорганизационные, напр. Отдел продаж —
  // доступны при любом юрлице) плюс ЦФО, привязанные к выбранной организации.
  cfos.value = (await requests.cfos()).filter(
    (c) => !org || c.organization == null || c.organization === org,
  )
}

onMounted(async () => {
  try {
    orgs.value = await requests.organizations()
    if (orgs.value.length) organization.value = orgs.value[0].id
    templates.value = await requests.powerTemplates()
    await loadContext()
  } catch { /* ошибку покажем при сохранении */ }
})

watch(organization, () => { facility.value = null; cfo.value = null; loadContext() })

// Проверка формы. Возвращает текст первой ошибки или null, если всё верно.
function validate(): string | null {
  if (!organization.value) return 'Выберите организацию.'

  if (isAnketa.value) {
    // Раздел 1 — представитель
    if (!rep.last_name.trim()) return 'Раздел 1: укажите фамилию представителя.'
    if (!rep.first_name.trim()) return 'Раздел 1: укажите имя представителя.'
    if (!rep.birth_date) return 'Раздел 1: укажите дату рождения представителя.'
    if (rep.birth_date > todayStr) return 'Раздел 1: дата рождения не может быть в будущем.'
    if (rep.birth_date > isoMinusYears(18)) return 'Раздел 1: представитель должен быть старше 18 лет.'
    if (!rep.position.trim()) return 'Раздел 1: укажите должность представителя.'

    // МЧД: ФНС опознаёт представителя по ИНН и СНИЛС — без них доверенность
    // не примут, поэтому оба поля обязательны и проверяются по контрольным
    // разрядам (те же правила на сервере).
    if (isMchd.value) {
      if (!rep.inn.trim()) return 'Раздел 1: для МЧД укажите ИНН представителя.'
      if (!isValidInn(rep.inn))
        return 'Раздел 1: проверьте ИНН — должно быть 12 цифр, контрольный разряд не сходится.'
      if (!rep.snils.trim()) return 'Раздел 1: для МЧД укажите СНИЛС представителя.'
      if (!isValidSnils(rep.snils))
        return 'Раздел 1: проверьте СНИЛС — должно быть 11 цифр, контрольное число не сходится.'
    }

    if (rep.phone.trim()) {
      const digits = rep.phone.replace(/\D/g, '')
      if (digits.length < 10 || digits.length > 11) return 'Раздел 1: проверьте номер телефона.'
    }
    if (rep.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(rep.email.trim()))
      return 'Раздел 1: некорректный email.'

    if (!rep.passport.trim()) return 'Раздел 1: укажите паспорт представителя (серия, №).'
    if (!/^[0-9 ]+$/.test(rep.passport.trim()))
      return 'Раздел 1: серия и номер паспорта — только цифры.'
    if (rep.passport.replace(/\s/g, '').length !== 10)
      return 'Раздел 1: серия и номер паспорта — 10 цифр (серия 4 + номер 6).'
    if (!rep.passport_issued_by.trim()) return 'Раздел 1: укажите, кем выдан паспорт.'
    if (!rep.passport_issue_date) return 'Раздел 1: укажите дату выдачи паспорта.'
    if (rep.passport_issue_date > todayStr) return 'Раздел 1: дата выдачи паспорта не может быть в будущем.'
    if (rep.passport_issue_date <= rep.birth_date)
      return 'Раздел 1: дата выдачи паспорта должна быть позже даты рождения.'
    if (!rep.reg_address.trim()) return 'Раздел 1: укажите адрес регистрации представителя.'

    // У ЭЦП своего «раздела полномочий» нет: по ТЗ там только сведения о
    // представителе, приложения и способ получения.
    if (isEcp.value) {
      if (!cfo.value) return 'Укажите ЦФО — по нему строится маршрут согласования.'
      if (!data.planned_date) return 'Укажите планируемую дату получения.'
      for (const a of attachmentList.value) {
        if ((data.attachments as string[]).includes(a.code) && !attachmentFiles[a.code])
          return `Приложите файл для «${a.name}» или снимите отметку.`
      }
      return null
    }

    // Раздел 2 — полномочия
    if (!(data.target_org as string).trim())
      return 'Раздел 2: укажите, куда направляется представитель (организация / госорган).'
    const powers = data.powers as string[]
    const tpls = data.power_templates as string[]
    if (!powers.length && !tpls.length && !(data.powers_other as string).trim())
      return 'Раздел 2: выберите хотя бы одно полномочие (или заполните «Иные полномочия»).'

    // Срок действия и правило «не более 3 лет»
    if (data.term_type === 'period') {
      if (!data.term_from) return 'Раздел 2: укажите дату начала срока действия.'
      if (!data.term_to) return 'Раздел 2: укажите дату окончания срока действия.'
      const from = new Date(data.term_from as string)
      const to = new Date(data.term_to as string)
      if (to <= from) return 'Раздел 2: дата окончания должна быть позже даты начала.'
      const max = new Date(from)
      max.setFullYear(max.getFullYear() + 3)
      if (to > max) return 'Раздел 2: срок доверенности не может превышать 3 года.'
    }

    // Раздел 3 — отмеченное приложение обязано иметь файл
    for (const a of attachmentList.value) {
      if ((data.attachments as string[]).includes(a.code) && !attachmentFiles[a.code])
        return `Раздел 3: приложите файл для «${a.name}» или снимите отметку.`
    }
  }

  // Основание оформления — реквизит доверенности; в бланке ЭЦП его нет.
  if (!isEcp.value && !basis.value.trim()) return 'Укажите основание оформления.'
  return null
}

async function save() {
  error.value = null
  const problem = validate()
  if (problem) { error.value = problem; return }
  const subject = [rep.last_name, rep.first_name, rep.middle_name].filter(Boolean).join(' ')
  saving.value = true
  let created
  try {
    created = await requests.create({
      request_type: requestType.value,
      organization: organization.value,
      facility: facility.value,
      cfo: cfo.value,
      subject_name: subject,
      position: rep.position,
      basis: basis.value.trim(),
      ...(isAnketa.value ? { data: JSON.parse(JSON.stringify(data)) } : {}),
    } as never)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать'
    saving.value = false
    return
  }
  // Заявка создана — прикладываем файлы (не блокируем переход, если часть не загрузилась).
  try {
    await uploadAttachments(created.id)
  } catch {
    error.value = 'Заявка создана, но некоторые файлы не загрузились — добавьте их в карточке заявки.'
  }
  router.push(`/requests/${created.id}`)
}
</script>

<template>
  <section>
    <RouterLink to="/requests" class="back-link">← К заявкам</RouterLink>
    <h1 class="page-title" style="margin-bottom:14px">Новая регламентная заявка</h1>

    <div class="form" style="max-width:760px">
      <!-- Базовое -->
      <div class="form-row">
        <label class="form-field">
          <span>Тип заявки</span>
          <select v-model="requestType">
            <option value="poa">Заявка на доверенность</option>
            <option value="mchd">Заявка на МЧД</option>
            <option value="ecp">Заявка на ЭЦП</option>
          </select>
        </label>
        <label class="form-field">
          <span>Организация</span>
          <select v-model="organization">
            <option v-for="o in orgs" :key="o.id" :value="o.id">{{ o.short_name }}</option>
          </select>
        </label>
      </div>
      <div class="form-row">
        <label class="form-field">
          <span>Проект / объект</span>
          <select v-model="facility">
            <option :value="null">—</option>
            <option v-for="f in facilities" :key="f.id" :value="f.id">{{ f.name }}</option>
          </select>
        </label>
        <label class="form-field">
          <span>ЦФО</span>
          <select v-model="cfo">
            <option :value="null">—</option>
            <option v-for="c in cfos" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
      </div>

      <template v-if="isAnketa">
        <!-- Параметры ЭЦП -->
        <div v-if="isEcp" class="detail-card">
          <div class="detail-card-header">Параметры ЭЦП</div>
          <label class="form-field" style="margin-bottom:10px">
            <span>Тип ЭЦП</span>
            <input v-model="data.ecp_type" placeholder="Уточняется с ИТ" />
          </label>
          <div class="form-row">
            <label class="form-field">
              <span>Планируемая дата получения *</span>
              <input v-model="data.planned_date" type="date" />
            </label>
            <label class="form-field">
              <span>Срочность</span>
              <select v-model="data.urgency">
                <option v-for="u in URGENCY" :key="u.code" :value="u.code">{{ u.name }}</option>
              </select>
            </label>
          </div>
        </div>

        <!-- Параметры доверенности -->
        <div v-if="!isEcp" class="detail-card">
          <div class="detail-card-header">Параметры доверенности</div>
          <div class="form-row">
            <label class="form-field">
              <span>Тип доверенности</span>
              <select v-model="data.poa_type">
                <option v-for="t in POA_TYPES" :key="t.code" :value="t.code">{{ t.name }}</option>
              </select>
            </label>
            <label class="form-field">
              <span>Срочность</span>
              <select v-model="data.urgency">
                <option v-for="u in URGENCY" :key="u.code" :value="u.code">{{ u.name }}</option>
              </select>
            </label>
            <label class="form-field">
              <span>Планируемая дата получения</span>
              <input v-model="data.planned_date" type="date" />
            </label>
          </div>
        </div>

        <!-- Раздел 1: представитель -->
        <div class="detail-card">
          <div class="detail-card-header">Раздел 1. Представитель</div>
          <div class="form-row">
            <label class="form-field"><span>Фамилия *</span><input v-model="rep.last_name" /></label>
            <label class="form-field"><span>Имя *</span><input v-model="rep.first_name" /></label>
            <label class="form-field"><span>Отчество</span><input v-model="rep.middle_name" /></label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Дата рождения *</span><input v-model="rep.birth_date" type="date" :max="todayStr" /></label>
            <label class="form-field">
              <span>Статус</span>
              <select v-model="rep.status">
                <option v-for="s in REP_STATUS" :key="s.code" :value="s.code">{{ s.name }}</option>
              </select>
            </label>
            <label class="form-field"><span>Должность *</span><input v-model="rep.position" /></label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Телефон</span><input v-model="rep.phone" /></label>
            <label class="form-field"><span>Email</span><input v-model="rep.email" type="email" /></label>
          </div>
          <div v-if="isMchd" class="form-row">
            <label class="form-field">
              <span>ИНН представителя *</span>
              <input v-model="rep.inn" inputmode="numeric" maxlength="12" placeholder="12 цифр" />
            </label>
            <label class="form-field">
              <span>СНИЛС представителя *</span>
              <input
                v-model="rep.snils" @blur="onSnilsBlur"
                inputmode="numeric" maxlength="14" placeholder="123-456-789 01"
              />
            </label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Паспорт (серия, №) *</span><input v-model="rep.passport" inputmode="numeric" maxlength="11" placeholder="1234 567890" /></label>
            <label class="form-field">
              <span>Код подразделения</span>
              <input v-model="rep.passport_department_code" @change="onDeptCode" @blur="onDeptCode" inputmode="numeric" maxlength="7" placeholder="770-053" />
            </label>
            <label class="form-field"><span>Дата выдачи *</span><input v-model="rep.passport_issue_date" type="date" :max="todayStr" /></label>
          </div>
          <label class="form-field">
            <span>Кем выдан *<template v-if="deptMsg"> — <em style="color:#6b7a8d;font-style:normal">{{ deptMsg }}</em></template></span>
            <input v-model="rep.passport_issued_by" />
          </label>
          <label class="form-field"><span>Адрес регистрации *</span>
            <AddressAutocomplete v-model="rep.reg_address" placeholder="Начните вводить адрес…" />
          </label>
        </div>

        <!-- Раздел 2: полномочия (у ЭЦП полномочий нет) -->
        <div v-if="!isEcp" class="detail-card">
          <div class="detail-card-header">Раздел 2. Полномочия и цель</div>
          <label class="form-field" style="margin-bottom:10px">
            <span>Куда направляется представитель (организация / госорган) *</span>
            <input v-model="data.target_org" />
          </label>
          <div class="form-field" style="margin-bottom:10px">
            <span>Перечень полномочий</span>
            <label v-for="p in POWERS" :key="p.code" class="check">
              <input type="checkbox" :value="p.code" v-model="(data.powers as string[])" /> {{ p.name }}
            </label>
          </div>
          <label class="form-field" style="margin-bottom:10px">
            <span>Иные полномочия</span>
            <input v-model="data.powers_other" />
          </label>
          <div class="form-field" style="margin-bottom:10px">
            <span>Шаблоны полномочий (матрица)</span>
            <label v-for="t in templates" :key="t.code" class="check" :title="t.powers">
              <input type="checkbox" :value="t.code" v-model="(data.power_templates as string[])" />
              <b>{{ t.code }}</b> — {{ t.name }}
            </label>
          </div>
          <div class="form-row">
            <label class="form-field">
              <span>Право передоверия</span>
              <select v-model="data.peredoverie">
                <option value="without">Без права передоверия</option>
                <option value="with">С правом передоверия</option>
              </select>
            </label>
            <label class="form-field">
              <span>Срок действия</span>
              <select v-model="data.term_type">
                <option value="single">Разовая</option>
                <option value="period">На определённый срок</option>
              </select>
            </label>
          </div>
          <div v-if="data.term_type === 'period'" class="form-row">
            <label class="form-field"><span>с *</span><input v-model="data.term_from" type="date" /></label>
            <label class="form-field">
              <span>по *</span>
              <input v-model="data.term_to" type="date" :min="data.term_from as string" :max="maxTermTo" />
            </label>
          </div>
          <div v-if="data.term_type === 'period'" class="attach-hint">
            Срок доверенности — не более 3 лет от даты начала.
          </div>
        </div>

        <!-- Доп. сведения: приложения и способ получения -->
        <div class="detail-card">
          <div class="detail-card-header">
            {{ isEcp ? 'Раздел 2. Дополнительные сведения' : 'Раздел 3. Дополнительно' }}
          </div>
          <label v-if="!isEcp" class="form-field" style="margin-bottom:10px">
            <span>Форма доверенности</span>
            <select v-model="data.form">
              <option v-for="f in FORMS" :key="f.code" :value="f.code">{{ f.name }}</option>
            </select>
          </label>
          <div class="form-field" style="margin-bottom:10px">
            <span>Приложения к заявке</span>
            <div class="attach-hint">
              Отметьте нужные документы и приложите файлы — исполнитель получит полный комплект.
            </div>
            <div v-for="a in attachmentList" :key="a.code" class="attach-row">
              <label class="check">
                <input type="checkbox" :value="a.code" v-model="(data.attachments as string[])" /> {{ a.name }}
              </label>
              <div v-if="(data.attachments as string[]).includes(a.code)" class="attach-file">
                <input type="file" @change="onAttachmentFile(a.code, $event)" />
                <span v-if="attachmentFiles[a.code]" class="attach-ok">✓ {{ attachmentFiles[a.code]?.name }}</span>
              </div>
            </div>
          </div>
          <div class="form-field" style="margin-bottom:10px">
            <span>Другие документы (по необходимости)</span>
            <input type="file" multiple @change="onExtraFiles" />
            <span v-if="extraFiles.length" class="attach-ok">Выбрано файлов: {{ extraFiles.length }}</span>
          </div>
          <label class="form-field">
            <span>{{ isEcp ? 'Способ получения ЭЦП' : 'Способ получения готовой доверенности' }}</span>
            <select v-model="data.receive">
              <option
                v-for="r in (isEcp ? ECP_RECEIVE : RECEIVE)" :key="r.code" :value="r.code"
              >{{ r.name }}</option>
            </select>
          </label>
        </div>
      </template>

      <label v-if="!isEcp" class="form-field">
        <span>Основание оформления *</span>
        <input v-model="basis" placeholder="Приказ №… / служебная записка" />
      </label>

      <p v-if="error" class="state state--error">{{ error }}</p>
      <div>
        <button class="btn btn--primary" :disabled="saving" @click="save">
          {{ saving ? 'Сохранение…' : 'Создать черновик' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.check { display: block; font-size: 13px; margin: 3px 0; cursor: pointer; }
.check input { margin-right: 6px; }
.attach-hint { font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
.attach-row { margin: 4px 0; }
.attach-file { margin: 2px 0 8px 22px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.attach-file input[type=file] { font-size: 12px; }
.attach-ok { font-size: 12px; color: var(--green-main); }
</style>
