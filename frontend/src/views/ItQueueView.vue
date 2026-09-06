<script setup lang="ts">
// Раздел «Работа ИТ»: исполнение согласованных заявок на ЭЦП.
// Устроен как раздел юристов — Новые / В работе / Архив / Все, — потому что
// процесс тот же: заявка после согласования падает исполнителю, он берёт её
// в работу и закрывает.
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useAdminModeStore } from '@/stores/adminMode'
import { useItUiStore } from '@/stores/itUi'
import SearchBox from '@/components/SearchBox.vue'
import type { RegulatoryRequestListItem } from '@/types/request'

const ui = useItUiStore()
const adminMode = useAdminModeStore()

// Поиск по номеру, ФИО, организации, анкете и именам вложенных файлов.
// При непустом запросе вкладка выборку не сужает — статус заявки заранее
// неизвестен (как в очереди юротдела).
const query = ref('')
const items = ref<RegulatoryRequestListItem[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)

const emptyText = computed(() => ({
  new: 'Новых заявок на ЭЦП нет.',
  work: 'В работе ничего нет.',
  archive: 'Архив пуст.',
  all: 'Заявок пока нет.',
}[ui.scope]))

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await requests.itQueue(ui.scope, query.value || undefined)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

// Бейдж «Новые» виден независимо от активной вкладки.
async function refreshBadge() {
  ui.newCount = (await requests.itQueue('new').catch(() => [])).length
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

watch([() => ui.scope, query, () => adminMode.active], load)
onMounted(() => {
  load()
  refreshBadge()
})
</script>

<template>
  <section>
    <SearchBox v-model="query" placeholder="Поиск: номер, ФИО, организация, имя файла" />
    <p v-if="query && !loading && !error" class="state" style="margin-bottom:8px">
      Поиск идёт по всем заявкам на ЭЦП, независимо от вкладки. Найдено: {{ items.length }}.
    </p>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">
      {{ query ? 'Ничего не найдено.' : emptyText }}
    </p>

    <ul v-else class="item-list">
      <li v-for="r in items" :key="r.id">
        <div class="item-card">
          <div class="item-title-row">
            <RouterLink :to="`/requests/${r.id}`" class="item-title">
              {{ r.number }} · {{ r.type_display }}
            </RouterLink>
            <span class="status-pill" :class="r.status">{{ r.status_display }}</span>
          </div>
          <div class="item-sub">{{ r.subject_name || '—' }} · {{ r.organization_name }}</div>

          <div v-if="r.status === 'to_it' || r.status === 'it_work'" class="row-actions" style="margin-top:8px">
            <button
              v-if="r.status === 'to_it'" class="btn btn--soft" :disabled="busy"
              @click="act(() => requests.itTake(r.id))"
            >Взять в работу</button>
            <button class="btn btn--primary" :disabled="busy" @click="act(() => requests.itExecute(r.id))">
              Исполнена
            </button>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
