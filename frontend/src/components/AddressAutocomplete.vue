<script setup lang="ts">
import { ref } from 'vue'
import { requests } from '@/services/requests'

// Поле адреса с подсказками DaData: пользователь печатает — выпадает список,
// который сужается по мере ввода. v-model — строка адреса.
defineProps<{ modelValue: string; placeholder?: string }>()
const emit = defineEmits<{ 'update:modelValue': [v: string] }>()

const suggestions = ref<string[]>([])
const open = ref(false)
const active = ref(-1)
let timer: ReturnType<typeof setTimeout> | null = null
let skipNext = false // после выбора пункта не дёргаем поиск повторно

function onInput(e: Event) {
  const v = (e.target as HTMLInputElement).value
  emit('update:modelValue', v)
  if (skipNext) { skipNext = false; return }
  if (timer) clearTimeout(timer)
  if (v.trim().length < 3) { suggestions.value = []; open.value = false; return }
  timer = setTimeout(async () => {
    try {
      const res = await requests.addressSuggest(v)
      suggestions.value = res.map((r) => r.value)
      open.value = suggestions.value.length > 0
      active.value = -1
    } catch {
      suggestions.value = []
      open.value = false
    }
  }, 250)
}

function pick(v: string) {
  skipNext = true
  emit('update:modelValue', v)
  suggestions.value = []
  open.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value || !suggestions.value.length) return
  if (e.key === 'ArrowDown') { e.preventDefault(); active.value = Math.min(active.value + 1, suggestions.value.length - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); active.value = Math.max(active.value - 1, 0) }
  else if (e.key === 'Enter' && active.value >= 0) { e.preventDefault(); pick(suggestions.value[active.value]) }
  else if (e.key === 'Escape') { open.value = false }
}

function onBlur() {
  setTimeout(() => { open.value = false }, 150)
}
</script>

<template>
  <div class="addr-ac">
    <input
      :value="modelValue"
      @input="onInput"
      @keydown="onKeydown"
      @blur="onBlur"
      @focus="open = suggestions.length > 0"
      :placeholder="placeholder"
      autocomplete="off"
    />
    <ul v-if="open" class="addr-list">
      <li
        v-for="(s, i) in suggestions"
        :key="i"
        :class="{ active: i === active }"
        @mousedown.prevent="pick(s)"
        @mouseenter="active = i"
      >{{ s }}</li>
    </ul>
  </div>
</template>

<style scoped>
.addr-ac { position: relative; }
.addr-list {
  position: absolute;
  z-index: 30;
  left: 0;
  right: 0;
  top: 100%;
  margin: 3px 0 0;
  padding: 4px 0;
  list-style: none;
  background: #fff;
  border: 1px solid #d7dee6;
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
  max-height: 260px;
  overflow-y: auto;
}
.addr-list li {
  padding: 8px 12px;
  font-size: 14px;
  cursor: pointer;
  line-height: 1.3;
}
.addr-list li.active { background: #eef6f0; }
</style>
