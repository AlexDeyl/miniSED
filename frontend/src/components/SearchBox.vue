<script setup lang="ts">
// Строка поиска по списку. Значение отдаётся наружу с задержкой — чтобы не
// дёргать сервер на каждую букву; Enter отправляет сразу.
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{ modelValue: string; placeholder?: string; delay?: number }>(),
  { placeholder: 'Поиск', delay: 350 },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const text = ref(props.modelValue)
let timer: ReturnType<typeof setTimeout> | undefined

// Родитель может сбросить поиск (например при смене раздела).
watch(() => props.modelValue, (v) => { if (v !== text.value) text.value = v })

function push(immediate = false) {
  clearTimeout(timer)
  const value = text.value.trim()
  if (immediate) {
    emit('update:modelValue', value)
    return
  }
  timer = setTimeout(() => emit('update:modelValue', value), props.delay)
}

function clear() {
  text.value = ''
  push(true)
}
</script>

<template>
  <div class="search-box">
    <input
      v-model="text" type="search" class="search-input" :placeholder="placeholder"
      @input="push()" @keyup.enter="push(true)"
    />
    <button v-if="text" type="button" class="search-clear" title="Очистить" @click="clear">×</button>
  </div>
</template>

<style scoped>
.search-box { position: relative; margin-bottom: 12px; }
.search-input {
  width: 100%; box-sizing: border-box; padding: 8px 30px 8px 10px;
  border: 1px solid var(--gray-border, #d0d0d0); border-radius: 6px;
  font: inherit; font-size: 13px; background: #fff;
}
.search-input:focus { outline: none; border-color: var(--green-main, #0b7f5f); }
/* у type=search в вебките свой крестик — прячем, у нас собственный */
.search-input::-webkit-search-cancel-button { display: none; }
.search-clear {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  border: 0; background: transparent; cursor: pointer; font-size: 18px; line-height: 1;
  color: var(--text-muted, #5a6675); padding: 0 4px;
}
</style>
