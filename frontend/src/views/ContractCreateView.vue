<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { contracts, type Cfo, type Organization } from '@/services/contracts'
import { bitrix, type BitrixDeal } from '@/services/bitrix'
import { ApiError } from '@/services/api'
import BitrixSearchModal from '@/components/BitrixSearchModal.vue'

// id приходит только с /contracts/:id/edit — та же форма правит существующий
// договор. Отдельная форма редактирования разошлась бы с формой создания
// (поля, подсказки, валидация), и вернувшийся с доработки инициатор видел бы
// не то, что заполнял.
const props = defineProps<{ id?: string }>()
const isEdit = computed(() => !!props.id)

const router = useRouter()

const orgs = ref<Organization[]>([])
const cfos = ref<Cfo[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)
const portalDomain = ref('')

const form = ref({
  title: '',
  organization: null as number | null,
  cfo: null as number | null,
  amount: '',
  is_nonstandard: false,
  has_disagreement_protocol: false,
  crm_link: '',
  comment: '',
})

// прикреплённые файлы (грузятся после создания договора)
const files = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
// выбор сделки из CRM (через коннектор)
const showDealPicker = ref(false)

async function load() {
  loading.value = true
  try {
    ;[orgs.value, cfos.value] = await Promise.all([
      contracts.organizations(),
      contracts.cfos(),
    ])
    try { portalDomain.value = (await bitrix.status()).domain || '' } catch { /* не критично */ }
    if (props.id) {
      const c = await contracts.get(props.id)
      form.value = {
        title: c.title,
        organization: c.organization,
        cfo: c.cfo,
        // сумма приходит строкой «150000.00» — в поле type=number пустая
        // строка означает «не указана», и такой её и отправим обратно
        amount: c.amount == null ? '' : String(c.amount),
        is_nonstandard: c.is_nonstandard,
        has_disagreement_protocol: c.has_disagreement_protocol,
        crm_link: c.crm_link || '',
        comment: c.comment || '',
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

function onPickDeal(d: BitrixDeal) {
  const dom = portalDomain.value
  form.value.crm_link = dom ? `https://${dom}/crm/deal/details/${d.ID}/` : String(d.ID)
  showDealPicker.value = false
}

async function save() {
  error.value = null
  if (!form.value.title.trim()) {
    error.value = 'Укажите название договора'
    return
  }
  if (!form.value.organization) {
    error.value = 'Выберите юрлицо (ЮО)'
    return
  }
  busy.value = true
  const payload = {
    title: form.value.title.trim(),
    organization: form.value.organization,
    cfo: form.value.cfo,
    amount: form.value.amount || null,
    is_nonstandard: form.value.is_nonstandard,
    has_disagreement_protocol: form.value.has_disagreement_protocol,
    crm_link: form.value.crm_link.trim(),
    comment: form.value.comment,
  }
  try {
    const c = props.id
      ? await contracts.update(props.id, payload)
      : await contracts.create(payload)
    // прикреплённые файлы загружаем к договору (при правке — как дополнение:
    // ранее загруженные остаются на месте)
    for (const f of files.value) {
      await contracts.uploadDocument(c.id, f, f.name)
    }
    router.push(`/contracts/${c.id}`)
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : props.id ? 'Не удалось сохранить договор' : 'Не удалось создать договор'
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="detail-narrow">
    <RouterLink :to="isEdit ? `/contracts/${props.id}` : '/contracts'" class="back-link">
      {{ isEdit ? '← К договору' : '← К списку' }}
    </RouterLink>
    <h1 class="detail-title">{{ isEdit ? 'Редактирование договора' : 'Новый договор' }}</h1>

    <p v-if="error" class="state state--error">{{ error }}</p>
    <p v-if="loading" class="state">Загрузка…</p>

    <div v-else class="detail-card">
      <label class="form-field">
        <span>Название договора *</span>
        <input v-model="form.title" type="text" placeholder="Напр.: Поставка мебели, ООО «Ромашка»" />
      </label>

      <div class="form-row">
        <label class="form-field">
          <span>Юрлицо (ЮО) *</span>
          <select v-model="form.organization">
            <option :value="null" disabled>— выберите —</option>
            <option v-for="o in orgs" :key="o.id" :value="o.id">{{ o.short_name }}</option>
          </select>
        </label>
        <label class="form-field">
          <span>ЦФО</span>
          <select v-model="form.cfo">
            <option :value="null">— не указан —</option>
            <option v-for="c in cfos" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
      </div>

      <label class="form-field" style="max-width:260px">
        <span>Сумма договора, ₽</span>
        <input v-model="form.amount" type="number" step="0.01" min="0" placeholder="напр. 150000" />
      </label>

      <!-- Ссылка на CRM / сделку -->
      <label class="form-field">
        <span>Ссылка на CRM / сделку</span>
        <div style="display:flex;gap:8px">
          <input v-model="form.crm_link" type="text" placeholder="Вставьте ссылку или выберите из CRM" style="flex:1" />
          <button type="button" class="btn btn--soft" @click="showDealPicker = true">Выбрать из CRM</button>
        </div>
        <a v-if="form.crm_link" :href="form.crm_link" target="_blank" rel="noopener"
           style="font-size:12px;color:#1976d2;word-break:break-all">{{ form.crm_link }}</a>
      </label>

      <div class="check-row">
        <label class="check">
          <input v-model="form.is_nonstandard" type="checkbox" />
          <span>Нестандартный (не по шаблону)</span>
        </label>
        <label class="check">
          <input v-model="form.has_disagreement_protocol" type="checkbox" />
          <span>С протоколом разногласий</span>
        </label>
      </div>
      <p class="muted" style="margin:2px 0 0;font-size:12px">
        Любой из флажков включает в маршрут этап юридического отдела.
      </p>

      <!-- Файлы договора -->
      <div class="form-field">
        <span>Документы (файлы договора)</span>
        <input ref="fileInput" type="file" multiple style="display:none" @change="onFiles" />
        <div>
          <button type="button" class="btn btn--ghost" @click="fileInput?.click()">Прикрепить файл</button>
        </div>
        <ul v-if="files.length" class="file-list">
          <li v-for="(f, i) in files" :key="i" class="file-row">
            <span>{{ f.name }}</span>
            <button type="button" class="file-x" @click="removeFile(i)">×</button>
          </li>
        </ul>
      </div>

      <label class="form-field">
        <span>Комментарий</span>
        <textarea v-model="form.comment" rows="3"></textarea>
      </label>

      <div class="row-actions" style="margin-top:12px">
        <button class="btn btn--primary" :disabled="busy" @click="save">
          {{ isEdit ? 'Сохранить' : 'Создать' }}
        </button>
        <RouterLink :to="isEdit ? `/contracts/${props.id}` : '/contracts'" class="btn btn--ghost">
          Отмена
        </RouterLink>
      </div>
      <p class="muted" style="margin:10px 0 0;font-size:12px">
        <template v-if="isEdit">
          Маршрут пересобирается по ЮО и ЦФО при отправке — после правок проверьте
          его в карточке договора и отправьте на согласование заново.
        </template>
        <template v-else>
          После создания маршрут согласования построится автоматически по ЮО и ЦФО —
          его можно будет проверить и отправить на согласование.
        </template>
      </p>
    </div>

    <!-- Поиск сделки через коннектор (вне iframe портала) -->
    <BitrixSearchModal
      v-if="showDealPicker"
      kind="deals"
      @pick-deal="onPickDeal"
      @close="showDealPicker = false"
    />
  </section>
</template>

<style scoped>
.check-row { display: flex; gap: 20px; flex-wrap: wrap; margin: 10px 0 0; }
.check { display: flex; align-items: center; gap: 6px; font-size: 14px; cursor: pointer; }
.check input { width: auto; }
.file-list { list-style: none; padding: 0; margin: 8px 0 0; display: flex; flex-direction: column; gap: 4px; }
.file-row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.file-x { border: none; background: #eee; border-radius: 50%; width: 18px; height: 18px; cursor: pointer; line-height: 1; }
</style>
