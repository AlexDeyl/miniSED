<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { compliments, type Facility } from '@/services/compliments'
import { ApiError } from '@/services/api'
import type { ComplimentCategory } from '@/types/compliment'

// id приходит только с /compliments/:id/edit — та же форма правит уже
// созданную заявку (возвращённую на доработку или отклонённую). Отдельная
// форма редактирования неизбежно разошлась бы с формой создания.
const props = defineProps<{ id?: string }>()
const isEdit = computed(() => !!props.id)

const router = useRouter()

const facilities = ref<Facility[]>([])
const categories = ref<{ code: string; name: string }[]>([])
const restaurants = ref<{ id: number; name: string }[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)

const form = ref({
  title: '',
  category: 'stay' as ComplimentCategory,
  category_details: '',
  company: '',
  guest_name: '',
  event_at: '',
  facility: null as number | null,
  restaurant: null as number | null,
  description: '',
  department: '',
  needs_ceo: false,
})

// Прикреплённые файлы грузятся после создания заявки.
const files = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)

// Кто согласует — зависит только от категории; показываем это сразу в форме,
// чтобы инициатор понимал маршрут ещё до отправки.
const ROUTE_HINT: Record<ComplimentCategory, string> = {
  confectionery: 'Руководитель отдела продаж → ресторанная служба. Выдаёт кондитерский цех.',
  restaurant: 'Руководитель отдела продаж → коммерческий директор → генеральный директор. Выдаёт ответственный выбранного ресторана.',
  stay: 'Руководитель отдела продаж → коммерческий директор → генеральный директор. Выдаёт помощник генерального директора.',
}
const routeHint = computed(() => ROUTE_HINT[form.value.category])
// Ресторан выбирают только для ресторанной категории — от него зависит исполнитель.
const isRestaurant = computed(() => form.value.category === 'restaurant')

async function load() {
  loading.value = true
  try {
    const [f, meta] = await Promise.all([compliments.facilities(), compliments.meta()])
    facilities.value = f
    categories.value = meta.categories
    restaurants.value = meta.restaurants || []
    if (props.id) {
      const c = await compliments.get(props.id)
      form.value = {
        title: c.title,
        category: c.category,
        category_details: c.category_details || '',
        company: c.company || '',
        guest_name: c.guest_name || '',
        // input[type=datetime-local] понимает только «YYYY-MM-DDTHH:MM»
        event_at: c.event_at ? c.event_at.slice(0, 16) : '',
        facility: c.facility,
        restaurant: c.restaurant,
        description: c.description || '',
        department: c.department || '',
        needs_ceo: c.needs_ceo,
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
  if (!form.value.title.trim()) {
    error.value = 'Укажите наименование заявки'
    return
  }
  if (!form.value.company.trim()) {
    error.value = 'Укажите компанию — получателя комплимента'
    return
  }
  if (isRestaurant.value && !form.value.restaurant) {
    error.value = 'Выберите ресторан'
    return
  }
  busy.value = true
  const payload = {
    title: form.value.title.trim(),
    category: form.value.category,
    category_details: form.value.category_details.trim(),
    company: form.value.company.trim(),
    guest_name: form.value.guest_name.trim(),
    event_at: form.value.event_at || null,
    facility: form.value.facility,
    restaurant: isRestaurant.value ? form.value.restaurant : null,
    description: form.value.description,
    department: form.value.department.trim(),
    needs_ceo: form.value.needs_ceo,
  }
  try {
    const c = props.id
      ? await compliments.update(props.id, payload)
      : await compliments.create(payload)
    // при правке прикреплённые файлы добавляются к уже загруженным
    for (const f of files.value) {
      await compliments.uploadDocument(c.id, f, f.name)
    }
    router.push(`/compliments/${c.id}`)
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
    <RouterLink :to="isEdit ? `/compliments/${props.id}` : '/compliments'" class="back-link">
      {{ isEdit ? '← К заявке' : '← К списку' }}
    </RouterLink>
    <h1 class="detail-title">
      {{ isEdit ? 'Редактирование заявки на комплимент' : 'Новая заявка на комплимент' }}
    </h1>
    <p class="cform-lead">Поля со звёздочкой обязательны.</p>

    <p v-if="error" class="state state--error">{{ error }}</p>
    <p v-if="loading" class="state">Загрузка…</p>

    <template v-else>
      <!-- 1. Что дарим: от категории зависит весь маршрут -->
      <div class="cform-card">
        <div class="cform-head">
          <span class="cform-num">1</span>
          <div>
            <div class="cform-title">Комплимент</div>
            <div class="cform-sub">Что предоставляем — от категории зависит маршрут согласования</div>
          </div>
        </div>

        <label class="form-field">
          <span>Наименование заявки *</span>
          <input v-model="form.title" type="text" placeholder="Напр.: Комплимент организатору бизнес-завтрака" />
        </label>

        <div class="form-row">
          <label class="form-field">
            <span>Категория комплимента *</span>
            <select v-model="form.category">
              <option v-for="c in categories" :key="c.code" :value="c.code">{{ c.name }}</option>
            </select>
          </label>
          <label v-if="isRestaurant" class="form-field">
            <span>Ресторан *</span>
            <select v-model="form.restaurant">
              <option :value="null">— выберите ресторан —</option>
              <option v-for="r in restaurants" :key="r.id" :value="r.id">{{ r.name }}</option>
            </select>
          </label>
        </div>

        <div class="cform-route">
          <span class="cform-route-label">Маршрут</span>
          {{ routeHint }}
        </div>

        <label class="form-field">
          <span>Что именно предоставляем</span>
          <textarea v-model="form.category_details" rows="2"
                    placeholder="Напр.: 2 сертификата на проживание в отеле SVET, «Стандарт», до 30.12.2026"></textarea>
        </label>
      </div>

      <!-- 2. Кому и когда -->
      <div class="cform-card">
        <div class="cform-head">
          <span class="cform-num">2</span>
          <div>
            <div class="cform-title">Получатель</div>
            <div class="cform-sub">Кому, где и когда вручаем</div>
          </div>
        </div>

        <div class="form-row">
          <label class="form-field">
            <span>Компания (получатель) *</span>
            <input v-model="form.company" type="text" placeholder="Напр.: ООО «Туроператор Невские Сезоны»" />
          </label>
          <label class="form-field">
            <span>Ф.И.О. гостя</span>
            <input v-model="form.guest_name" type="text" placeholder="если известно" />
          </label>
        </div>

        <div class="form-row">
          <label class="form-field">
            <span>Дата и время комплимента</span>
            <input v-model="form.event_at" type="datetime-local" />
          </label>
          <label class="form-field">
            <span>Отель</span>
            <select v-model="form.facility">
              <option :value="null">— не выбран —</option>
              <option v-for="f in facilities" :key="f.id" :value="f.id">{{ f.name }}</option>
            </select>
          </label>
        </div>
      </div>

      <!-- 3. Подробности и вложения -->
      <div class="cform-card">
        <div class="cform-head">
          <span class="cform-num">3</span>
          <div>
            <div class="cform-title">Подробности</div>
            <div class="cform-sub">Повод, согласование и файлы</div>
          </div>
        </div>

        <label class="form-field">
          <span>Подразделение инициатора</span>
          <input v-model="form.department" type="text" placeholder="Напр.: Отдел продаж" />
        </label>

        <label class="form-field">
          <span>Описание заявки</span>
          <textarea v-model="form.description" rows="3"
                    placeholder="Повод, мероприятие, дополнительная информация"></textarea>
        </label>

        <label class="cform-option" :class="{ 'is-on': form.needs_ceo }">
          <input v-model="form.needs_ceo" type="checkbox" />
          <span>
            <b>Согласование с генеральным директором</b>
            <small>Добавит коммерческого и генерального директора там, где их нет по категории.</small>
          </span>
        </label>

        <div class="form-field">
          <span>Файлы</span>
          <label class="cform-drop">
            <input ref="fileInput" type="file" multiple @change="onFiles" />
            <span class="cform-drop-btn">Выбрать файлы</span>
            <span class="cform-drop-hint">
              {{ files.length ? `Выбрано: ${files.length}` : 'Бланк, макет сертификата, письмо партнёра…' }}
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
        <RouterLink :to="isEdit ? `/compliments/${props.id}` : '/compliments'" class="btn btn--ghost">
          Отмена
        </RouterLink>
        <p v-if="isEdit" class="cform-note">
          Маршрут строится по категории при отправке — после правок проверьте его
          в карточке заявки и отправьте на согласование заново.
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cform { max-width: 820px; }
.cform-lead { margin: 0 0 14px; font-size: 12px; color: var(--text-muted); }

/* Смысловой блок формы: заголовок с номером шага + поля с воздухом,
   чтобы форма не сливалась в одно сплошное поле. */
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

/* Подсказка о маршруте — выделенная плашка, а не серая строчка между полями. */
.cform-route {
  background: var(--green-light); border-left: 3px solid var(--green-main);
  border-radius: 6px; padding: 9px 12px; font-size: 13px; color: #1e4d3f; line-height: 1.45;
}
.cform-route-label {
  display: inline-block; margin-right: 6px; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.04em; color: var(--green-main);
}

/* Флажок — кликабельная плитка с пояснением. */
.cform-option {
  display: flex; align-items: flex-start; gap: 10px; cursor: pointer;
  border: 1px solid #dadce0; border-radius: 8px; padding: 12px 14px; background: #fcfcfd;
}
.cform-option.is-on { border-color: var(--green-main); background: var(--green-light); }
.cform-option input { margin-top: 2px; accent-color: var(--green-main); width: 16px; height: 16px; }
.cform-option b { display: block; font-size: 14px; font-weight: 500; }
.cform-option small { display: block; font-size: 12px; color: var(--text-muted); margin-top: 2px; }

/* Загрузка файлов. */
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
