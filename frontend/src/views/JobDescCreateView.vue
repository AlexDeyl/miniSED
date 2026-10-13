<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { jobdesc } from '@/services/jobdesc'
import { ApiError } from '@/services/api'
import type { JobDescMeta } from '@/types/jobdesc'

// id приходит только с /jobdesc/:id/edit — та же форма правит заявку,
// возвращённую на доработку или отклонённую.
const props = defineProps<{ id?: string }>()
const isEdit = computed(() => !!props.id)

const router = useRouter()

const meta = ref<JobDescMeta | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)

const form = ref({
  position_name: '',
  organization: null as number | null,
  facility: null as number | null,
  cfo: null as number | null,
  is_nonstandard: false,
  description: '',
})

// Прикреплённые файлы (проект ДИ — можно несколько) грузятся после создания.
const files = ref<File[]>([])

// ЦФО — общие (без юрлица) и ЦФО выбранной организации; объекты — её же.
const cfos = computed(() =>
  (meta.value?.cfos || []).filter((c) => !c.organization || c.organization === form.value.organization),
)
const facilities = computed(() =>
  (meta.value?.facilities || []).filter((f) => !form.value.organization || f.organization === form.value.organization),
)
const selectedCfo = computed(() => cfos.value.find((c) => c.id === form.value.cfo) || null)

// Сменили организацию — ЦФО и объект другой организации сбрасываем.
watch(() => form.value.organization, () => {
  if (form.value.cfo && !cfos.value.some((c) => c.id === form.value.cfo)) form.value.cfo = null
  if (form.value.facility && !facilities.value.some((f) => f.id === form.value.facility)) form.value.facility = null
})

// Доп. согласующие по категории ЦФО — подсказка до отправки, точный маршрут
// с людьми покажет карточка заявки.
const EXTRA_BY_CATEGORY: Record<string, string> = {
  sales: 'коммерческий директор',
  revenue: 'коммерческий директор',
  marketing: 'коммерческий директор',
  booking: 'коммерческий директор',
  accounting: 'главный бухгалтер',
  its_it: 'технический директор',
  sgh: 'операционный директор',
  reception: 'операционный директор',
  territory: 'операционный директор',
  warehouse: 'операционный директор',
  restaurant: 'директор ресторанной службы',
  finance: 'финансовый директор',
  mts: 'руководитель отдела снабжения',
}
const routeHint = computed(() => {
  const steps = ['Сотрудник отдела персонала', 'руководитель ЦФО', 'административный и функциональный руководители (при наличии)']
  const extra = selectedCfo.value ? EXTRA_BY_CATEGORY[selectedCfo.value.category] : ''
  if (extra) steps.push(extra)
  const org = meta.value?.organizations.find((o) => o.id === form.value.organization)
  if (org?.name.includes('Невесомость') && extra !== 'директор ресторанной службы') steps.push('директор ресторанной службы')
  if (form.value.is_nonstandard) steps.push('юридический отдел', 'финансовый директор')
  steps.push('руководитель отдела по работе с персоналом', 'подписант организации')
  return steps.join(' → ')
})

async function load() {
  loading.value = true
  try {
    meta.value = await jobdesc.meta()
    if (props.id) {
      const d = await jobdesc.get(props.id)
      form.value = {
        position_name: d.position_name,
        organization: d.organization,
        facility: d.facility,
        cfo: d.cfo,
        is_nonstandard: d.is_nonstandard,
        description: d.description || '',
      }
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить справочники'
  } finally {
    loading.value = false
  }
}

function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  for (const f of Array.from(input.files || [])) {
    if (!files.value.some((x) => x.name === f.name && x.size === f.size)) files.value.push(f)
  }
  input.value = ''
}
function removeFile(i: number) {
  files.value.splice(i, 1)
}

async function save() {
  error.value = null
  if (!form.value.position_name.trim()) return void (error.value = 'Укажите должность')
  if (!form.value.organization) return void (error.value = 'Выберите организацию')
  if (!form.value.cfo) return void (error.value = 'Выберите ЦФО (подразделение)')
  busy.value = true
  const payload = {
    position_name: form.value.position_name.trim(),
    organization: form.value.organization,
    facility: form.value.facility,
    cfo: form.value.cfo,
    is_nonstandard: form.value.is_nonstandard,
    description: form.value.description,
  }
  try {
    const d = props.id ? await jobdesc.update(props.id, payload) : await jobdesc.create(payload)
    for (const f of files.value) {
      await jobdesc.uploadDocument(d.id, f, f.name)
    }
    router.push(`/jobdesc/${d.id}`)
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : props.id ? 'Не удалось сохранить заявку' : 'Не удалось создать заявку'
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="cform">
    <RouterLink :to="isEdit ? `/jobdesc/${props.id}` : '/jobdesc'" class="back-link">
      {{ isEdit ? '← К заявке' : '← К списку' }}
    </RouterLink>
    <h1 class="detail-title">
      {{ isEdit ? 'Редактирование заявки на согласование ДИ' : 'Новая заявка на согласование должностной инструкции' }}
    </h1>
    <p class="cform-lead">Поля со звёздочкой обязательны.</p>

    <p v-if="error" class="state state--error">{{ error }}</p>
    <p v-if="loading" class="state">Загрузка…</p>

    <template v-else-if="meta">
      <!-- 1. Чья инструкция: от организации и ЦФО зависит маршрут -->
      <div class="cform-card">
        <div class="cform-head">
          <span class="cform-num">1</span>
          <div>
            <div class="cform-title">Должностная инструкция</div>
            <div class="cform-sub">Организация и ЦФО определяют маршрут согласования</div>
          </div>
        </div>

        <label class="form-field">
          <span>Должность *</span>
          <input v-model="form.position_name" type="text" placeholder="Напр.: Менеджер отдела продаж" />
        </label>

        <div class="form-row">
          <label class="form-field">
            <span>Организация *</span>
            <select v-model="form.organization">
              <option :value="null">— выберите —</option>
              <option v-for="o in meta.organizations" :key="o.id" :value="o.id">{{ o.name }}</option>
            </select>
          </label>
          <label class="form-field">
            <span>Объект / проект</span>
            <select v-model="form.facility">
              <option :value="null">— не выбран —</option>
              <option v-for="f in facilities" :key="f.id" :value="f.id">{{ f.name }}</option>
            </select>
          </label>
        </div>

        <label class="form-field">
          <span>ЦФО (подразделение) *</span>
          <select v-model="form.cfo">
            <option :value="null">— выберите —</option>
            <option v-for="c in cfos" :key="c.id" :value="c.id">
              {{ c.name }}{{ c.category_name ? ` · ${c.category_name}` : '' }}
            </option>
          </select>
        </label>

        <label class="cform-option" :class="{ 'is-on': form.is_nonstandard }">
          <input v-model="form.is_nonstandard" type="checkbox" />
          <span>
            <b>Нестандартная форма или изменены шаблонные условия</b>
            <small>Добавит в маршрут юридический отдел и финансового директора.</small>
          </span>
        </label>

        <div class="cform-route">
          <span class="cform-route-label">Маршрут</span>
          {{ routeHint }}
        </div>
      </div>

      <!-- 2. Документы и пояснения -->
      <div class="cform-card">
        <div class="cform-head">
          <span class="cform-num">2</span>
          <div>
            <div class="cform-title">Документы</div>
            <div class="cform-sub">Проект ДИ и сопутствующие файлы — можно несколько</div>
          </div>
        </div>

        <label class="form-field">
          <span>Комментарий</span>
          <textarea v-model="form.description" rows="3"
                    placeholder="Что изменилось, почему нужна новая редакция, сроки"></textarea>
        </label>

        <div class="form-field">
          <span>Файлы</span>
          <label class="cform-drop">
            <input type="file" multiple @change="onFiles" />
            <span class="cform-drop-btn">Выбрать файлы</span>
            <span class="cform-drop-hint">
              {{ files.length ? `Выбрано: ${files.length}` : 'Проект ДИ (.docx — можно править онлайн), приложения…' }}
            </span>
          </label>
          <ul v-if="files.length" class="cform-files">
            <li v-for="(f, i) in files" :key="f.name + f.size">
              <span>{{ f.name }}</span>
              <button type="button" class="extra-x" title="Убрать" @click="removeFile(i)">×</button>
            </li>
          </ul>
        </div>
      </div>

      <div class="cform-actions">
        <button class="btn btn--primary" :disabled="busy" @click="save">
          {{ isEdit ? 'Сохранить' : 'Создать заявку' }}
        </button>
        <RouterLink :to="isEdit ? `/jobdesc/${props.id}` : '/jobdesc'" class="btn btn--ghost">Отмена</RouterLink>
        <p class="cform-note">
          После создания откроется карточка: там виден маршрут с конкретными людьми,
          его можно поправить и отправить на согласование.
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cform { max-width: 820px; }
.cform-lead { margin: 0 0 14px; font-size: 12px; color: var(--text-muted); }
.cform-card {
  background: #fff; border: 1px solid #eceff1; border-radius: 12px;
  box-shadow: var(--shadow-soft); padding: 18px 20px 20px; margin-bottom: 14px;
  display: flex; flex-direction: column; gap: 16px;
}
.cform-head {
  display: flex; align-items: center; gap: 12px;
  padding-bottom: 12px; border-bottom: 1px solid #f1f3f4;
}
.cform-num {
  flex: none; width: 28px; height: 28px; border-radius: 50%;
  background: var(--green-light); color: var(--green-main);
  display: grid; place-items: center; font-weight: 700; font-size: 13px;
}
.cform-title { font-size: 15px; font-weight: 600; color: var(--text-main); }
.cform-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.cform .form-row { gap: 16px; }
.cform .form-field { gap: 6px; min-width: 220px; }
.cform .form-field > span { font-size: 13px; font-weight: 500; color: #3c4043; }
.cform .form-field input, .cform .form-field select, .cform .form-field textarea {
  padding: 10px 12px; border-color: #dadce0; background: #fcfcfd;
}
.cform .form-field input, .cform .form-field select { height: 42px; box-sizing: border-box; }
.cform .form-field input:focus, .cform .form-field select:focus, .cform .form-field textarea:focus {
  background: #fff; box-shadow: 0 0 0 3px rgba(11, 127, 95, 0.12);
}
.cform-route {
  background: var(--green-light); border-left: 3px solid var(--green-main);
  border-radius: 6px; padding: 9px 12px; font-size: 13px; color: #1e4d3f; line-height: 1.45;
}
.cform-route-label {
  display: inline-block; margin-right: 6px; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.04em; color: var(--green-main);
}
.cform-option {
  display: flex; align-items: flex-start; gap: 10px; cursor: pointer;
  border: 1px solid #dadce0; border-radius: 8px; padding: 12px 14px; background: #fcfcfd;
}
.cform-option.is-on { border-color: var(--green-main); background: var(--green-light); }
.cform-option input { margin-top: 2px; accent-color: var(--green-main); width: 16px; height: 16px; }
.cform-option b { display: block; font-size: 14px; font-weight: 500; }
.cform-option small { display: block; font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.cform-drop {
  display: flex; align-items: center; gap: 12px; cursor: pointer;
  border: 1px dashed #c4c7c5; border-radius: 8px; padding: 12px 14px; background: #fcfcfd;
}
.cform-drop:hover { border-color: var(--green-main); }
.cform-drop input { display: none; }
.cform-drop-btn {
  border: 1px solid var(--green-main); color: var(--green-main); border-radius: 6px;
  padding: 6px 12px; font-size: 13px; font-weight: 500; background: #fff;
}
.cform-drop-hint { font-size: 13px; color: var(--text-muted); }
.cform-files { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.cform-files li {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  background: #f5f5f5; border-radius: 6px; padding: 6px 10px; font-size: 13px;
}
.extra-x {
  border: none; background: #ffcdd2; color: #b71c1c; border-radius: 50%;
  width: 20px; height: 20px; cursor: pointer; line-height: 1; font-size: 14px;
}
.cform-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 4px 0 24px; }
.cform-actions .btn { padding: 9px 20px; font-size: 14px; }
.cform-note { flex-basis: 100%; margin: 4px 0 0; font-size: 12px; color: var(--text-muted); }
</style>
