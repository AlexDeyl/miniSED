<script setup lang="ts">
// Раздел «Заявки для исполнения»: согласованная заявка не уходит письмом, а
// попадает сюда — исполнитель берёт её в работу и закрывает.
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { compliments } from '@/services/compliments'
import { ApiError } from '@/services/api'
import { useComplimentsUiStore } from '@/stores/complimentsUi'
import type { ComplimentListItem } from '@/types/compliment'

const ui = useComplimentsUiStore()

const items = ref<ComplimentListItem[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)

const emptyText = computed(() => ({
  new: 'Новых заявок на исполнение нет.',
  work: 'В работе ничего нет.',
  archive: 'Исполненных заявок пока нет.',
}[ui.executionMode]))

function fmt(dt: string | null): string {
  return dt ? new Date(dt).toLocaleString('ru') : ''
}

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await compliments.executionQueue(ui.executionMode)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

async function refreshBadge() {
  ui.executionCount = (await compliments.executionQueue('new').catch(() => [])).length
}

async function act(fn: () => Promise<unknown>) {
  busy.value = true
  error.value = null
  try {
    await fn()
    await load()
    await refreshBadge()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

watch(() => ui.executionMode, load)
onMounted(() => {
  load()
  refreshBadge()
})
</script>

<template>
  <section>
    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">{{ emptyText }}</p>

    <ul v-else class="item-list">
      <li v-for="c in items" :key="c.id">
        <div class="item-card">
          <div class="item-title-row">
            <RouterLink :to="`/compliments/${c.id}`" class="item-title">
              {{ c.number }} · {{ c.title }}
            </RouterLink>
            <span class="status-pill" :class="c.status">{{ c.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ c.category_display }} · {{ c.company }}
            <template v-if="c.facility_name"> · {{ c.facility_name }}</template>
            <template v-if="c.event_at"> · вручить {{ fmt(c.event_at) }}</template>
          </div>
          <div v-if="c.status !== 'executed'" class="row-actions" style="margin-top:8px">
            <button
              v-if="c.status === 'approved'" class="btn btn--soft" :disabled="busy"
              @click="act(() => compliments.take(c.id))"
            >Взять в работу</button>
            <button class="btn btn--primary" :disabled="busy" @click="act(() => compliments.execute(c.id))">
              Исполнена
            </button>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
