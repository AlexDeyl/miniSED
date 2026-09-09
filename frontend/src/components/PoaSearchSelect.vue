<script setup lang="ts">
/**
 * Выбор отзываемой доверенности/МЧД текстом.
 *
 * Список приходит с сервера (/reg/requests/revocable/) уже отфильтрованным:
 * только выданные доверенности и только те, что мне видны. Поэтому здесь нет
 * локальной фильтрации — печатаем и спрашиваем сервер, с задержкой DEBOUNCE.
 *
 * v-model — id карточки (null = не выбрана). @pick — сама запись: вызывающему
 * нужны ФИО и организация, чтобы подставить их в заявку.
 */
import { onMounted, ref } from 'vue'
import { requests } from '@/services/requests'
import type { RegulatoryRequestListItem } from '@/types/request'

const DEBOUNCE = 300

defineProps<{ modelValue: number | null }>()
const emit = defineEmits<{
  'update:modelValue': [v: number | null]
  pick: [r: RegulatoryRequestListItem]
}>()

const query = ref('')
const items = ref<RegulatoryRequestListItem[]>([])
const loading = ref(false)
const loaded = ref(false)
const open = ref(false)
const active = ref(-1)
let timer: ReturnType<typeof setTimeout> | null = null
let seq = 0

async function fetchList(q: string) {
  const mine = ++seq
  loading.value = true
  try {
    const res = await requests.revocable(q || undefined)
    if (mine !== seq) return // пока ждали, набрали дальше — ответ протух
    items.value = res
    loaded.value = true
  } catch {
    if (mine === seq) items.value = []
  } finally {
    if (mine === seq) loading.value = false
  }
}

// Первую выборку тянем сразу: у большинства инициаторов доверенностей единицы,
// и список без единой буквы уже отвечает на вопрос «что я вообще могу отозвать».
onMounted(() => fetchList(''))

function onInput(e: Event) {
  query.value = (e.target as HTMLInputElement).value
  emit('update:modelValue', null) // печатая — сбрасываем прежний выбор
  active.value = -1
  open.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => fetchList(query.value.trim()), DEBOUNCE)
}

function pick(r: RegulatoryRequestListItem) {
  emit('update:modelValue', r.id)
  emit('pick', r)
  query.value = `${r.number} — ${r.subject_name || r.type_display}`
  open.value = false
}

function clear() {
  query.value = ''
  emit('update:modelValue', null)
  fetchList('')
  open.value = true
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value) return
  const n = items.value.length
  if (e.key === 'ArrowDown') { e.preventDefault(); active.value = Math.min(active.value + 1, n - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); active.value = Math.max(active.value - 1, 0) }
  else if (e.key === 'Enter' && active.value >= 0 && active.value < n) {
    e.preventDefault()
    pick(items.value[active.value])
  } else if (e.key === 'Escape') { open.value = false }
}
function onBlur() { setTimeout(() => { open.value = false }, 180) }
</script>

<template>
  <div class="poa-ac">
    <input
      :value="query"
      @input="onInput"
      @keydown="onKeydown"
      @blur="onBlur"
      @focus="open = true"
      placeholder="номер, ФИО или организация…"
      autocomplete="off"
    />
    <button v-if="modelValue || query" type="button" class="poa-clear" title="Очистить"
            @mousedown.prevent="clear">×</button>

    <ul v-if="open" class="poa-ac-list">
      <li
        v-for="(r, i) in items"
        :key="r.id"
        :class="{ active: i === active }"
        @mousedown.prevent="pick(r)"
        @mouseenter="active = i"
      >
        <span class="poa-num">{{ r.number }}</span>
        <span class="poa-name">{{ r.subject_name || '—' }}</span>
        <span class="poa-org">{{ r.organization_name }}</span>
        <span class="poa-status">{{ r.status_display }}</span>
      </li>

      <li v-if="loading" class="poa-note">Ищем…</li>
      <li v-else-if="loaded && !items.length" class="poa-note">
        Доверенностей не найдено. Если она бумажная и в системе её нет —
        заполните реквизиты вручную ниже.
      </li>
    </ul>
  </div>
</template>

<style scoped>
.poa-ac { position: relative; }
.poa-ac input { width: 100%; box-sizing: border-box; padding: 6px 26px 6px 8px; border: 1px solid var(--gray-border); border-radius: 6px; }
.poa-clear { position: absolute; right: 4px; top: 4px; width: 22px; height: 22px; border: 0; background: none; cursor: pointer; color: var(--text-muted); font-size: 16px; line-height: 1; }
.poa-ac-list {
  position: absolute; z-index: 40; left: 0; right: 0; top: 100%; margin: 3px 0 0;
  padding: 4px 0; list-style: none; background: #fff; border: 1px solid #d7dee6;
  border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.12); max-height: 320px; overflow-y: auto;
}
.poa-ac-list li { padding: 7px 12px; font-size: 13.5px; line-height: 1.3; display: flex; align-items: center; gap: 8px; }
.poa-ac-list li:not(.poa-note) { cursor: pointer; }
.poa-ac-list li.active { background: #eef6f0; }
.poa-num { font-weight: 500; white-space: nowrap; }
.poa-name { flex: 1; }
.poa-org { color: var(--text-muted); font-size: 12.5px; white-space: nowrap; }
.poa-status { font-size: 10px; padding: 1px 6px; border-radius: 8px; background: #e3f0fb; color: #1976d2; white-space: nowrap; }
.poa-note { color: var(--text-muted); font-size: 12.5px; display: block; }
</style>
