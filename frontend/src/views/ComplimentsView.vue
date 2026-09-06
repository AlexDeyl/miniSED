<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { compliments } from '@/services/compliments'
import { ApiError } from '@/services/api'
import { useAdminModeStore } from '@/stores/adminMode'
import { useComplimentsUiStore } from '@/stores/complimentsUi'
import SearchBox from '@/components/SearchBox.vue'
import type { ComplimentListItem, ComplimentStatus } from '@/types/compliment'

// Режим администратора: при переключении список надо перезагрузить —
// сервер отдаёт другую выборку.
const adminMode = useAdminModeStore()

// Поиск по компании, гостю, отелю, содержанию и ИМЕНАМ вложенных файлов.
// При непустом запросе вкладка выборку не сужает — статус заранее неизвестен.
const query = ref('')

const ui = useComplimentsUiStore()

const items = ref<ComplimentListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const STATUS_BY_MODE: Record<string, ComplimentStatus[]> = {
  draft: ['draft'],
  in_progress: ['on_approval', 'returned'],
  approved: ['approved', 'in_work'],
  executed: ['executed'],
}

const emptyText = computed(() =>
  ui.mode === 'todo' ? 'Заявок, ждущих вашего решения, нет.' : 'Заявок пока нет.',
)

function fmt(dt: string | null): string {
  return dt ? new Date(dt).toLocaleString('ru') : ''
}

async function load() {
  loading.value = true
  error.value = null
  try {
    if (query.value) {
      items.value = await compliments.list('all', query.value)
    } else if (ui.mode === 'todo') {
      items.value = await compliments.todo()
    } else {
      // Черновики бывают только свои; в остальных вкладках показываем всё,
      // что мне доступно (руководителю продаж — все заявки).
      const all = await compliments.list(ui.mode === 'draft' ? 'mine' : 'all')
      const statuses = STATUS_BY_MODE[ui.mode]
      items.value = statuses ? all.filter((c) => statuses.includes(c.status)) : all
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

async function refreshBadge() {
  ui.todoCount = (await compliments.todo().catch(() => [])).length
}

watch([() => ui.mode, query, () => adminMode.active], load)
onMounted(() => {
  load()
  refreshBadge()
})
</script>

<template>
  <section>
    <Teleport to="#header-actions">
      <RouterLink to="/compliments/new" class="btn btn--primary">Создать заявку</RouterLink>
    </Teleport>

    <SearchBox v-model="query" placeholder="Поиск: номер, компания, гость, отель, имя файла" />
    <p v-if="query && !loading && !error" class="state" style="margin-bottom:8px">
      Поиск идёт по всем доступным заявкам, независимо от вкладки. Найдено: {{ items.length }}.
    </p>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">
      {{ query ? 'Ничего не найдено.' : emptyText }}
    </p>

    <ul v-else class="item-list">
      <li v-for="c in items" :key="c.id">
        <RouterLink :to="`/compliments/${c.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">{{ c.number }} · {{ c.title }}</span>
            <span class="status-pill" :class="c.status">{{ c.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ c.category_display }} · {{ c.company }}
            <template v-if="c.facility_name"> · {{ c.facility_name }}</template>
            <template v-if="c.event_at"> · {{ fmt(c.event_at) }}</template>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
