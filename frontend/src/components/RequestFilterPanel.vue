<script setup lang="ts">
// Отбор регламентных заявок «как в 1С»: галочки по компании (юрлицу),
// инициатору, ЦФО и статусу. Варианты и счётчики приходят с сервера (facets):
// только то, что реально есть в выборке, а счётчик поля пересчитывается с
// учётом галочек в остальных полях. ИЛИ внутри поля, И между полями.
import { computed, reactive, ref, watch } from 'vue'
import { requests } from '@/services/requests'
import type {
  FacetOption, RequestFacets, RequestFilterField, RequestFilters,
} from '@/types/request'

const props = defineProps<{
  modelValue: RequestFilters
  view: 'mine' | 'legal'
  type?: string
  q?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: RequestFilters] }>()

const FIELDS: { code: RequestFilterField; label: string }[] = [
  { code: 'organization', label: 'Компания' },
  { code: 'initiator', label: 'Инициатор' },
  { code: 'cfo', label: 'ЦФО' },
  { code: 'status', label: 'Статус' },
]

const open = ref(false)
const facets = ref<RequestFacets | null>(null)
const loading = ref(false)
// строка поиска внутри каждого столбца (инициаторов бывают десятки)
const find = reactive<Record<RequestFilterField, string>>({
  organization: '', initiator: '', cfo: '', status: '',
})

const selectedCount = computed(() =>
  Object.values(props.modelValue).reduce((n, v) => n + (v?.length || 0), 0),
)

async function loadFacets() {
  if (!open.value) return
  loading.value = true
  try {
    facets.value = await requests.facets(props.view, {
      type: props.type, q: props.q, filters: props.modelValue,
    })
  } catch {
    facets.value = null
  } finally {
    loading.value = false
  }
}
watch([open, () => props.modelValue, () => props.type, () => props.q], loadFacets, { deep: true })

function isOn(f: RequestFilterField, v: string) {
  return (props.modelValue[f] || []).includes(v)
}
function toggle(f: RequestFilterField, v: string) {
  const cur = props.modelValue[f] || []
  const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]
  emit('update:modelValue', { ...props.modelValue, [f]: next })
}
function clearField(f: RequestFilterField) {
  emit('update:modelValue', { ...props.modelValue, [f]: [] })
}
function clearAll() {
  emit('update:modelValue', {})
}

// Отмеченное значение показываем, даже если при других галочках его счётчик
// стал нулём и сервер его не прислал, — иначе галочку было бы не снять.
function options(f: RequestFilterField): FacetOption[] {
  const list = [...(facets.value?.[f] || [])]
  for (const v of props.modelValue[f] || []) {
    if (!list.some((o) => o.value === v)) list.push({ value: v, label: labelOf(f, v), count: 0 })
  }
  const needle = find[f].trim().toLowerCase()
  return needle ? list.filter((o) => o.label.toLowerCase().includes(needle)) : list
}

// Подписи выбранного для чипов, когда панель закрыта: запоминаем их, пока
// варианты загружены, чтобы не показывать голые id.
const known = reactive<Record<string, string>>({})
watch(facets, (fc) => {
  if (!fc) return
  for (const f of FIELDS) for (const o of fc[f.code] || []) known[`${f.code}:${o.value}`] = o.label
})
function labelOf(f: RequestFilterField, v: string) {
  return known[`${f}:${v}`] || v
}
const chips = computed(() =>
  FIELDS.flatMap((f) =>
    (props.modelValue[f.code] || []).map((v) => ({ field: f.code, fieldLabel: f.label, value: v })),
  ),
)
</script>

<template>
  <div class="rf">
    <div class="rf-bar">
      <button type="button" class="btn btn--soft" :class="{ 'rf-on': open }" @click="open = !open">
        Отбор<template v-if="selectedCount"> ({{ selectedCount }})</template>
        <span class="rf-caret">{{ open ? '▲' : '▼' }}</span>
      </button>
      <span v-for="c in chips" :key="c.field + c.value" class="rf-chip">
        <span class="rf-chip-f">{{ c.fieldLabel }}:</span> {{ labelOf(c.field, c.value) }}
        <button type="button" title="Снять" @click="toggle(c.field, c.value)">×</button>
      </span>
      <button v-if="selectedCount" type="button" class="rf-link" @click="clearAll">Сбросить отбор</button>
    </div>

    <div v-if="open" class="rf-panel">
      <p v-if="loading && !facets" class="rf-muted">Загрузка…</p>
      <div v-else class="rf-grid">
        <div v-for="f in FIELDS" :key="f.code" class="rf-col">
          <div class="rf-col-head">
            <span>{{ f.label }}</span>
            <button v-if="(modelValue[f.code] || []).length" type="button" class="rf-link" @click="clearField(f.code)">
              снять
            </button>
          </div>
          <input
            v-if="(facets?.[f.code]?.length || 0) > 6"
            v-model="find[f.code]" class="rf-find" placeholder="найти…"
          />
          <div class="rf-list">
            <label v-for="o in options(f.code)" :key="o.value" class="rf-opt" :class="{ 'rf-zero': !o.count }">
              <input type="checkbox" :checked="isOn(f.code, o.value)" @change="toggle(f.code, o.value)" />
              <span class="rf-opt-label">{{ o.label }}</span>
              <span class="rf-count">{{ o.count }}</span>
            </label>
            <p v-if="!options(f.code).length" class="rf-muted">—</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rf { margin-bottom: 12px; }
.rf-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.rf-on { background: var(--green-light); color: var(--green-main); }
.rf-caret { font-size: 9px; margin-left: 4px; }
.rf-chip {
  display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
  background: var(--green-light); color: var(--green-main); border-radius: 999px; padding: 2px 4px 2px 10px;
}
.rf-chip-f { color: var(--text-muted); }
.rf-chip button {
  border: none; background: none; color: var(--green-main); cursor: pointer;
  font-size: 14px; line-height: 1; padding: 0 4px;
}
.rf-link {
  border: none; background: none; padding: 0; color: var(--green-main);
  cursor: pointer; font: inherit; font-size: 12px; text-decoration: underline;
}
.rf-panel {
  margin-top: 8px; padding: 12px; background: #fff; border: 1px solid var(--gray-border);
  border-radius: 8px; box-shadow: 0 1px 3px rgba(0, 0, 0, .08);
}
.rf-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
.rf-col-head {
  display: flex; justify-content: space-between; align-items: baseline;
  font-weight: 600; font-size: 13px; margin-bottom: 6px;
}
.rf-find {
  width: 100%; box-sizing: border-box; margin-bottom: 6px; padding: 4px 8px;
  border: 1px solid var(--gray-border); border-radius: 6px; font: inherit; font-size: 12.5px;
}
.rf-list { max-height: 220px; overflow-y: auto; }
.rf-opt { display: flex; align-items: flex-start; gap: 6px; font-size: 13px; padding: 2px 0; cursor: pointer; }
.rf-opt input { margin-top: 2px; flex: none; }
.rf-opt-label { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.rf-count { color: var(--text-muted); font-size: 12px; }
.rf-zero .rf-opt-label { color: var(--text-muted); }
.rf-muted { color: var(--text-muted); font-size: 12px; margin: 0; }
</style>
