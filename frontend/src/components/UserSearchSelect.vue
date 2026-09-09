<script setup lang="ts">
/**
 * Поиск и выбор сотрудника текстом (вместо длинного выпадающего списка).
 *
 * Печатаешь ФИО — подсказки приходят СРАЗУ из двух источников: локальная
 * матрица (UserProfile) фильтруется мгновенно, портал Битрикса опрашивается
 * с задержкой BX_DEBOUNCE, чтобы не дёргать его на каждую букву. Ответы
 * нумеруются: пришедший позже ответ на устаревший запрос отбрасывается.
 *
 * Если портал недоступен или медленный, авто-поиск выключается до конца
 * сессии и остаётся кнопка «Искать в Битриксе» — ввод не тормозит.
 *
 * v-model — строковый b24_user_id ('' = не выбран). @pick — полная запись.
 */
import { computed, ref, watch } from 'vue'
import { bitrix } from '@/services/bitrix'
import type { UserOption } from '@/services/contracts'

const props = defineProps<{ modelValue: string; users: UserOption[]; placeholder?: string }>()
const emit = defineEmits<{ 'update:modelValue': [v: string]; pick: [u: UserOption] }>()

interface Item { bitrix_id: number; fio: string; position: string; source: 'matrix' | 'bitrix' }

const MIN_CHARS = 2       // с одной буквы искать в портале бессмысленно
const BX_DEBOUNCE = 350   // мс тишины в наборе перед запросом к Битриксу

const query = ref('')
const local = ref<Item[]>([])
const bx = ref<Item[]>([])
const bxLoading = ref(false)
const bxSearched = ref(false)
// Портал ответил ошибкой — дальше не дёргаем его автоматически, показываем кнопку.
const bxAuto = ref(true)
const open = ref(false)
const active = ref(-1)
let timer: ReturnType<typeof setTimeout> | null = null
let bxTimer: ReturnType<typeof setTimeout> | null = null
let bxSeq = 0 // номер запроса: ответ на устаревший запрос игнорируем

function labelFor(id: string): string {
  const u = props.users.find((x) => String(x.bitrix_id) === id)
  return u ? u.fio : id ? `USER #${id}` : ''
}
watch(
  () => props.modelValue,
  (v) => { if (v && !query.value) query.value = labelFor(v) },
  { immediate: true },
)

function localMatches(q: string): Item[] {
  const s = q.toLowerCase()
  return props.users
    .filter((u) => u.fio.toLowerCase().includes(s) || (u.position_name || '').toLowerCase().includes(s))
    .slice(0, 12)
    .map((u) => ({ bitrix_id: u.bitrix_id, fio: u.fio, position: u.position_name || '', source: 'matrix' as const }))
}

const items = computed<Item[]>(() => [...local.value, ...bx.value])
const canBitrix = computed(() => query.value.trim().length >= MIN_CHARS)

function onInput(e: Event) {
  query.value = (e.target as HTMLInputElement).value
  emit('update:modelValue', '') // печатая — сбрасываем прежний выбор
  bx.value = []
  bxSearched.value = false
  active.value = -1
  if (timer) clearTimeout(timer)
  if (bxTimer) clearTimeout(bxTimer)
  const v = query.value.trim()
  if (!v) { local.value = []; open.value = false; bxLoading.value = false; return }
  timer = setTimeout(() => { local.value = localMatches(v); open.value = true }, 120)
  // Битрикс — тем же набором, только с задержкой: пока человек печатает,
  // запрос не уходит, а уйдёт один — на то, что он в итоге набрал.
  if (bxAuto.value && v.length >= MIN_CHARS) {
    bxLoading.value = true // сразу показываем «Поиск в Битриксе…», без мигания
    bxTimer = setTimeout(() => { void searchBitrix() }, BX_DEBOUNCE)
  } else {
    bxLoading.value = false
  }
}

async function searchBitrix() {
  const q = query.value.trim()
  if (q.length < MIN_CHARS) { bxLoading.value = false; return }
  const seq = ++bxSeq
  bxLoading.value = true
  try {
    const { results } = await bitrix.searchUsers(q)
    if (seq !== bxSeq) return // пока ждали, набрали дальше — ответ протух
    const seen = new Set(local.value.map((x) => x.bitrix_id))
    bx.value = results
      .map((u) => ({
        bitrix_id: Number(u.ID),
        fio: [u.LAST_NAME, u.NAME, u.SECOND_NAME].filter(Boolean).join(' ') || `USER #${u.ID}`,
        position: u.WORK_POSITION || '',
        source: 'bitrix' as const,
      }))
      .filter((x) => x.bitrix_id && !seen.has(x.bitrix_id))
    bxSearched.value = true
  } catch {
    if (seq !== bxSeq) return
    bx.value = []
    bxSearched.value = true
    bxAuto.value = false // портал недоступен — дальше только по кнопке
  } finally {
    if (seq === bxSeq) bxLoading.value = false
  }
}

function pick(it: Item) {
  emit('update:modelValue', String(it.bitrix_id))
  emit('pick', { id: it.bitrix_id, bitrix_id: it.bitrix_id, fio: it.fio, position_name: it.position })
  query.value = it.fio + (it.position ? ` — ${it.position}` : '')
  open.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value) return
  const n = items.value.length
  if (e.key === 'ArrowDown') { e.preventDefault(); active.value = Math.min(active.value + 1, n - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); active.value = Math.max(active.value - 1, 0) }
  else if (e.key === 'Enter') {
    if (active.value >= 0 && active.value < n) { e.preventDefault(); pick(items.value[active.value]) }
    else if (canBitrix.value && !bxSearched.value) { e.preventDefault(); void searchBitrix() }
  } else if (e.key === 'Escape') { open.value = false }
}
function onBlur() { setTimeout(() => { open.value = false }, 180) }
</script>

<template>
  <div class="user-ac">
    <input
      :value="query"
      @input="onInput"
      @keydown="onKeydown"
      @blur="onBlur"
      @focus="open = !!query.trim()"
      :placeholder="placeholder || 'начните вводить фамилию…'"
      autocomplete="off"
    />
    <ul v-if="open" class="user-ac-list">
      <li
        v-for="(it, i) in items"
        :key="it.source + '-' + it.bitrix_id"
        :class="{ active: i === active }"
        @mousedown.prevent="pick(it)"
        @mouseenter="active = i"
      >
        <span class="uac-fio">{{ it.fio }}</span>
        <span v-if="it.position" class="uac-pos"> — {{ it.position }}</span>
        <span class="uac-src" :class="it.source">{{ it.source === 'bitrix' ? 'Битрикс' : 'матрица' }}</span>
      </li>

      <li v-if="!local.length && !bxSearched && !bxLoading" class="uac-note">В матрице не найдено</li>

      <li v-if="bxLoading" class="uac-note">Поиск в Битриксе…</li>
      <li v-if="!bxAuto && canBitrix && !bxSearched && !bxLoading" class="uac-action" @mousedown.prevent="searchBitrix">
        🔍 Искать «{{ query.trim() }}» в Битриксе
      </li>
      <li v-if="bxSearched && !bxLoading && !bx.length && !bxAuto" class="uac-note">Битрикс недоступен</li>
      <li v-if="bxSearched && !bxLoading && !bx.length && bxAuto && !local.length" class="uac-note">В Битриксе тоже не найдено</li>
    </ul>
  </div>
</template>

<style scoped>
.user-ac { position: relative; }
.user-ac input { width: 100%; box-sizing: border-box; min-width: 240px; padding: 6px 8px; border: 1px solid var(--gray-border); border-radius: 6px; }
.user-ac-list {
  position: absolute; z-index: 40; left: 0; right: 0; top: 100%; margin: 3px 0 0;
  padding: 4px 0; list-style: none; background: #fff; border: 1px solid #d7dee6;
  border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.12); max-height: 300px; overflow-y: auto;
}
.user-ac-list li { padding: 7px 12px; font-size: 13.5px; line-height: 1.3; display: flex; align-items: center; gap: 6px; }
.user-ac-list li:not(.uac-note) { cursor: pointer; }
.user-ac-list li.active { background: #eef6f0; }
.uac-fio { font-weight: 500; }
.uac-pos { color: var(--text-muted); flex: 1; }
.uac-src { font-size: 10px; padding: 1px 6px; border-radius: 8px; white-space: nowrap; }
.uac-src.matrix { background: #e3f4ee; color: #0b7f5f; }
.uac-src.bitrix { background: #e3f0fb; color: #1976d2; }
.uac-action { color: #1976d2; font-weight: 500; }
.uac-action:hover { background: #eef6f0; }
.uac-note { color: var(--text-muted); font-size: 12.5px; }
</style>
