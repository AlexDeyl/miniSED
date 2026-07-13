<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import type { RegulatoryRequestListItem, RequestType } from '@/types/request'

const items = ref<RegulatoryRequestListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const filter = ref<'' | RequestType>('')

const TYPE_TABS: { code: '' | RequestType; label: string }[] = [
  { code: '', label: 'Все' },
  { code: 'ecp', label: 'ЭЦП' },
  { code: 'mchd', label: 'МЧД' },
  { code: 'poa', label: 'Доверенности' },
]

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await requests.list(filter.value || undefined)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

function setFilter(code: '' | RequestType) {
  filter.value = code
  load()
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-head">
      <h1 class="page-title">Регламентные заявки</h1>
      <RouterLink to="/requests/new" class="btn btn--primary">Создать</RouterLink>
    </div>

    <div class="filter-tabs">
      <button
        v-for="t in TYPE_TABS"
        :key="t.code"
        class="filter-tab"
        :class="{ active: filter === t.code }"
        @click="setFilter(t.code)"
      >
        {{ t.label }}
      </button>
    </div>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">Заявок пока нет.</p>

    <ul v-else class="item-list">
      <li v-for="r in items" :key="r.id">
        <RouterLink :to="`/requests/${r.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">{{ r.number }} · {{ r.type_display }}</span>
            <span class="status-pill" :class="r.status">{{ r.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ r.subject_name || '—' }} · {{ r.organization_name }}
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
