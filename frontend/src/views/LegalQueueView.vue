<script setup lang="ts">
import { onMounted, ref, watch, computed } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useLegalUiStore } from '@/stores/legalUi'
import SearchBox from '@/components/SearchBox.vue'
import type { RegulatoryRequestListItem } from '@/types/request'

// Поиск по номеру, ФИО, паспорту, организации и анкете доверенности.
// При непустом запросе сервер ищет по ВСЕМ статусам, а не только по вкладке:
// когда ищут дубль, статус заранее неизвестен.
const query = ref('')
const items = ref<RegulatoryRequestListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

// вкладка (Новые/В работе/Архив) — в сторе, кнопки в сайдбаре
const legalUi = useLegalUiStore()
const emptyText = computed(() => ({
  new: 'Нет новых заявок.',
  work: 'Нет заявок в работе.',
  archive: 'Архив пуст.',
  all: 'Заявок пока нет.',
}[legalUi.scope]))

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await requests.legalQueue(legalUi.scope, query.value || undefined)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

watch([() => legalUi.scope, query], load)
onMounted(load)
</script>

<template>
  <section>
    <SearchBox v-model="query" placeholder="Поиск: номер, ФИО, паспорт, организация" />
    <p v-if="query && !loading && !error" class="state" style="margin-bottom:8px">
      Поиск идёт по всем заявкам юротдела, независимо от вкладки. Найдено: {{ items.length }}.
    </p>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">
      {{ query ? 'Ничего не найдено.' : emptyText }}
    </p>

    <ul v-else class="item-list">
      <li v-for="r in items" :key="r.id">
        <RouterLink :to="`/requests/${r.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">{{ r.number }} · {{ r.type_display }}</span>
            <span class="status-pill" :class="r.status">{{ r.status_display }}</span>
          </div>
          <div class="item-sub">{{ r.subject_name || '—' }} · {{ r.organization_name }}</div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
