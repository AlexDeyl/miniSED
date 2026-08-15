<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { compliments, type Facility } from '@/services/compliments'
import { ApiError } from '@/services/api'
import type { ComplimentCategory } from '@/types/compliment'

const router = useRouter()

const facilities = ref<Facility[]>([])
const categories = ref<{ code: string; name: string }[]>([])
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
  restaurant: 'Руководитель отдела продаж → коммерческий директор → генеральный директор. Выдаёт ресторанная служба.',
  stay: 'Руководитель отдела продаж → коммерческий директор → генеральный директор. Выдаёт помощник генерального директора.',
}
const routeHint = computed(() => ROUTE_HINT[form.value.category])

async function load() {
  loading.value = true
  try {
    const [f, meta] = await Promise.all([compliments.facilities(), compliments.meta()])
    facilities.value = f
    categories.value = meta.categories
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

async function create() {
  error.value = null
  if (!form.value.title.trim()) {
    error.value = 'Укажите наименование заявки'
    return
  }
  if (!form.value.company.trim()) {
    error.value = 'Укажите компанию — получателя комплимента'
    return
  }
  busy.value = true
  try {
    const c = await compliments.create({
      title: form.value.title.trim(),
      category: form.value.category,
      category_details: form.value.category_details.trim(),
      company: form.value.company.trim(),
      guest_name: form.value.guest_name.trim(),
      event_at: form.value.event_at || null,
      facility: form.value.facility,
      description: form.value.description,
      department: form.value.department.trim(),
      needs_ceo: form.value.needs_ceo,
    })
    for (const f of files.value) {
      await compliments.uploadDocument(c.id, f, f.name)
    }
    router.push(`/compliments/${c.id}`)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать заявку'
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="detail-narrow">
    <RouterLink to="/compliments" class="back-link">← К списку</RouterLink>
    <h1 class="detail-title">Новая заявка на комплимент</h1>

    <p v-if="error" class="state state--error">{{ error }}</p>
    <p v-if="loading" class="state">Загрузка…</p>

    <div v-else class="detail-card">
      <label class="form-field">
        <span>Наименование заявки *</span>
        <input v-model="form.title" type="text" placeholder="Напр.: Комплимент организатору бизнес-завтрака" />
      </label>

      <label class="form-field">
        <span>Категория комплимента *</span>
        <select v-model="form.category">
          <option v-for="c in categories" :key="c.code" :value="c.code">{{ c.name }}</option>
        </select>
      </label>
      <p class="detail-meta" style="margin:-4px 0 4px">Маршрут: {{ routeHint }}</p>

      <label class="form-field">
        <span>Что именно предоставляем</span>
        <textarea v-model="form.category_details" rows="2"
                  placeholder="Напр.: 2 сертификата на проживание в отеле SVET, «Стандарт», до 30.12.2026"></textarea>
      </label>

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

      <label class="form-field">
        <span>Подразделение инициатора</span>
        <input v-model="form.department" type="text" placeholder="Напр.: Отдел продаж" />
      </label>

      <label class="form-field">
        <span>Описание заявки</span>
        <textarea v-model="form.description" rows="3"
                  placeholder="Повод, мероприятие, дополнительная информация"></textarea>
      </label>

      <label class="check-line">
        <input v-model="form.needs_ceo" type="checkbox" />
        <span>Согласование с генеральным директором</span>
      </label>
      <p class="detail-meta" style="margin:-4px 0 8px">
        Добавит коммерческого и генерального директора там, где их нет по категории.
      </p>

      <div class="form-field">
        <span>Файлы</span>
        <input ref="fileInput" type="file" multiple @change="onFiles" />
        <ul v-if="files.length" class="item-tags" style="flex-direction:column;align-items:flex-start;gap:4px;margin-top:6px">
          <li v-for="(f, i) in files" :key="f.name + f.size">
            {{ f.name }}
            <button type="button" class="extra-x" title="Убрать" @click="removeFile(i)">×</button>
          </li>
        </ul>
      </div>

      <div style="margin-top:12px">
        <button class="btn btn--primary" :disabled="busy" @click="create">Создать заявку</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.check-line { display: flex; align-items: center; gap: 8px; margin: 8px 0 4px; font-size: 14px; }
.extra-x {
  border: none; background: #ffcdd2; color: #b71c1c; border-radius: 50%;
  width: 20px; height: 20px; cursor: pointer; line-height: 1; font-size: 14px;
}
</style>
