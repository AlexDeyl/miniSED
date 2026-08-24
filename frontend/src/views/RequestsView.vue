<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useRequestsUiStore } from '@/stores/requestsUi'
import SearchBox from '@/components/SearchBox.vue'
import type { RegulatoryRequestListItem } from '@/types/request'

// Поиск по номеру, ФИО сотрудника, организации и анкете доверенности.
const query = ref('')
const items = ref<RegulatoryRequestListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

// Фильтр типа — в сторе, кнопки живут в сайдбаре (App.vue).
const reqUi = useRequestsUiStore()

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await requests.list(reqUi.typeFilter || undefined, query.value || undefined)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

watch([() => reqUi.typeFilter, query], load)
onMounted(load)
</script>

<template>
  <section>
    <!-- Основная кнопка — в фиксированной шапке приложения -->
    <Teleport to="#header-actions">
      <RouterLink to="/requests/new" class="btn btn--primary">Создать</RouterLink>
    </Teleport>

    <SearchBox v-model="query" placeholder="Поиск: номер, ФИО, паспорт, организация" />

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">
      {{ query ? 'Ничего не найдено.' : 'Заявок пока нет.' }}
    </p>

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
