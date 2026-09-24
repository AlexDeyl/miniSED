<script setup lang="ts">
// Раздел «Работа службы безопасности»: исполнение согласованных заявок на
// проверку лица. Устроен как «Работа юристов» — Новые / В работе / Архив /
// Все; решение, комментарий и отчёт принимаются в карточке заявки.
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { requests } from '@/services/requests'
import { ApiError } from '@/services/api'
import { useAdminModeStore } from '@/stores/adminMode'
import { useSecurityUiStore } from '@/stores/securityUi'
import SearchBox from '@/components/SearchBox.vue'
import SecurityDelegationBar from '@/components/SecurityDelegationBar.vue'
import type { RegulatoryRequestListItem } from '@/types/request'

const ui = useSecurityUiStore()
const adminMode = useAdminModeStore()

// При непустом запросе вкладка выборку не сужает — статус заявки заранее
// неизвестен (как в очереди юротдела).
const query = ref('')
const items = ref<RegulatoryRequestListItem[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)

const emptyText = computed(() => ({
  new: 'Новых заявок на проверку нет.',
  work: 'В работе ничего нет.',
  archive: 'Архив пуст.',
  all: 'Заявок пока нет.',
}[ui.scope]))

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await requests.securityQueue(ui.scope, query.value || undefined)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

async function refreshBadge() {
  ui.newCount = (await requests.securityQueue('new').catch(() => [])).length
}

async function take(id: number) {
  busy.value = true
  error.value = null
  try {
    await requests.securityTake(id)
    await Promise.all([load(), refreshBadge()])
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
    <SecurityDelegationBar />
    <SearchBox v-model="query" placeholder="Поиск: номер, наименование, ФИО, ИНН, паспорт, имя файла" />
    <p v-if="query && !loading && !error" class="state" style="margin-bottom:8px">
      Поиск идёт по всем заявкам на проверку, независимо от вкладки. Найдено: {{ items.length }}.
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
              {{ r.number }} · {{ r.subject_name || '—' }}
            </RouterLink>
            <span class="status-pill" :class="r.status">{{ r.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ r.organization_name }} · {{ new Date(r.created_at).toLocaleDateString('ru-RU') }}
          </div>
          <div class="row-actions" style="margin-top:8px">
            <RouterLink :to="`/requests/${r.id}`" class="btn btn--ghost">
              {{ r.status === 'check_work' ? 'Открыть и исполнить' : 'Просмотреть' }}
            </RouterLink>
            <button v-if="r.status === 'approved'" class="btn btn--soft" :disabled="busy" @click="take(r.id)">
              Взять в работу
            </button>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
