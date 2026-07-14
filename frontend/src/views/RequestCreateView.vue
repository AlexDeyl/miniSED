<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { requests, type Cfo, type Facility, type Organization } from '@/services/requests'
import { ApiError } from '@/services/api'
import type { RequestType } from '@/types/request'

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

const data = reactive<Record<string, unknown>>({
  poa_type: 'single', urgency: 'standard', planned_date: '',
  rep: {
    last_name: '', first_name: '', middle_name: '', birth_date: '', status: 'employee',
    position: '', phone: '', email: '', passport: '', passport_issued_by: '',
    passport_issue_date: '', reg_address: '',
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

const isAnketa = computed(() => requestType.value === 'poa' || requestType.value === 'mchd')

async function loadContext() {
  const org = organization.value ?? undefined
  facilities.value = await requests.facilities(org)
  cfos.value = (await requests.cfos()).filter((c) => !org || c.organization === org)
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

async function save() {
  error.value = null
  if (!organization.value) { error.value = 'Выберите организацию'; return }
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
        <!-- Параметры доверенности -->
        <div class="detail-card">
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
            <label class="form-field"><span>Фамилия</span><input v-model="rep.last_name" /></label>
            <label class="form-field"><span>Имя</span><input v-model="rep.first_name" /></label>
            <label class="form-field"><span>Отчество</span><input v-model="rep.middle_name" /></label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Дата рождения</span><input v-model="rep.birth_date" type="date" /></label>
            <label class="form-field">
              <span>Статус</span>
              <select v-model="rep.status">
                <option v-for="s in REP_STATUS" :key="s.code" :value="s.code">{{ s.name }}</option>
              </select>
            </label>
            <label class="form-field"><span>Должность</span><input v-model="rep.position" /></label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Телефон</span><input v-model="rep.phone" /></label>
            <label class="form-field"><span>Email</span><input v-model="rep.email" type="email" /></label>
          </div>
          <div class="form-row">
            <label class="form-field"><span>Паспорт (серия, №)</span><input v-model="rep.passport" /></label>
            <label class="form-field"><span>Кем выдан</span><input v-model="rep.passport_issued_by" /></label>
            <label class="form-field"><span>Дата выдачи</span><input v-model="rep.passport_issue_date" type="date" /></label>
          </div>
          <label class="form-field"><span>Адрес регистрации</span><input v-model="rep.reg_address" /></label>
        </div>

        <!-- Раздел 2: полномочия -->
        <div class="detail-card">
          <div class="detail-card-header">Раздел 2. Полномочия и цель</div>
          <label class="form-field" style="margin-bottom:10px">
            <span>Куда направляется представитель (организация / госорган)</span>
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
            <label class="form-field"><span>с</span><input v-model="data.term_from" type="date" /></label>
            <label class="form-field"><span>по</span><input v-model="data.term_to" type="date" /></label>
          </div>
        </div>

        <!-- Раздел 3: доп. сведения -->
        <div class="detail-card">
          <div class="detail-card-header">Раздел 3. Дополнительно</div>
          <label class="form-field" style="margin-bottom:10px">
            <span>Форма доверенности</span>
            <select v-model="data.form">
              <option v-for="f in FORMS" :key="f.code" :value="f.code">{{ f.name }}</option>
            </select>
          </label>
          <div class="form-field" style="margin-bottom:10px">
            <span>Приложения к заявке</span>
            <div class="attach-hint">Отметьте нужные документы и приложите файлы — юристы получат полный комплект.</div>
            <div v-for="a in ATTACHMENTS" :key="a.code" class="attach-row">
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
            <span>Способ получения готовой доверенности</span>
            <select v-model="data.receive">
              <option v-for="r in RECEIVE" :key="r.code" :value="r.code">{{ r.name }}</option>
            </select>
          </label>
        </div>
      </template>

      <label class="form-field">
        <span>Основание оформления</span>
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
