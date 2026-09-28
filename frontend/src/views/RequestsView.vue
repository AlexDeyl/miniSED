<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useAdminModeStore } from '@/stores/adminMode'
import { useRequestsUiStore } from '@/stores/requestsUi'
import SearchBox from '@/components/SearchBox.vue'
import RequestFilterPanel from '@/components/RequestFilterPanel.vue'
import type { RegulatoryRequestListItem, RequestFilters } from '@/types/request'

// Режим администратора: при переключении список надо перезагрузить —
// сервер отдаёт другую выборку.
const adminMode = useAdminModeStore()

// Поиск по номеру, ФИО сотрудника, организации и анкете доверенности.
const query = ref('')
// Отбор галочками: компания, инициатор, ЦФО, статус.
const filters = ref<RequestFilters>({})
const items = ref<RegulatoryRequestListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

// Фильтр типа — в сторе, кнопки живут в сайдбаре (App.vue).
const reqUi = useRequestsUiStore()

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await requests.list(
      reqUi.typeFilter || undefined, query.value || undefined, undefined, filters.value,
    )
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

watch([() => reqUi.typeFilter, query, () => adminMode.active, filters], load, { deep: true })
onMounted(load)
</script>

<template>
  <section>
    <!-- Основная кнопка — в фиксированной шапке приложения. Тип заявки несём
         с собой: нажали «Создать» на вкладке МЧД — форма и откроется на МЧД,
         а не заставит выбирать его заново в списке. -->
    <Teleport to="#header-actions">
      <RouterLink
        :to="reqUi.typeFilter ? `/requests/new?type=${reqUi.typeFilter}` : '/requests/new'"
        class="btn btn--primary"
      >Создать</RouterLink>
    </Teleport>

    <SearchBox v-model="query" placeholder="Поиск: номер, ФИО, паспорт, организация, имя файла" />
    <RequestFilterPanel
      v-model="filters" view="mine"
      :type="reqUi.typeFilter || undefined" :q="query || undefined"
    />

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">
      {{ query || Object.values(filters).some((v) => v?.length) ? 'Ничего не найдено.' : 'Заявок пока нет.' }}
    </p>

    <ul v-else class="item-list">
      <li v-for="r in items" :key="r.id">
        <RouterLink :to="`/requests/${r.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">{{ r.number }} · {{ r.type_display }}</span>
            <span class="status-pill" :class="r.status">{{ r.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ [r.subject_name || '—', r.organization_name, r.cfo_name].filter(Boolean).join(' · ') }}
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
