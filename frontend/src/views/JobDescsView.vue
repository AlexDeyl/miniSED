<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { jobdesc } from '@/services/jobdesc'
import { ApiError } from '@/services/api'
import { useAdminModeStore } from '@/stores/adminMode'
import { useJobDescUiStore } from '@/stores/jobdescUi'
import SearchBox from '@/components/SearchBox.vue'
import type { JobDescListItem, JobDescStatus } from '@/types/jobdesc'

// Режим администратора: при переключении список надо перезагрузить —
// сервер отдаёт другую выборку.
const adminMode = useAdminModeStore()

// Поиск по должности, ЦФО, юрлицу и именам вложенных файлов. При непустом
// запросе вкладка выборку не сужает — статус искомой заявки неизвестен.
const query = ref('')

const ui = useJobDescUiStore()

const items = ref<JobDescListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const STATUS_BY_MODE: Record<string, JobDescStatus[]> = {
  draft: ['draft'],
  in_progress: ['on_approval', 'returned', 'rejected'],
  hr: ['to_hr', 'hr_work', 'signing'],
  done: ['executed', 'closed'],
}

const emptyText = computed(() =>
  ui.mode === 'todo' ? 'Заявок, ждущих вашего действия, нет.' : 'Заявок пока нет.',
)

async function load() {
  loading.value = true
  error.value = null
  try {
    if (query.value) {
      items.value = await jobdesc.list('all', query.value)
    } else if (ui.mode === 'todo') {
      items.value = await jobdesc.todo()
    } else {
      // Черновики бывают только свои; в остальных вкладках — всё доступное.
      const all = await jobdesc.list(ui.mode === 'draft' ? 'mine' : 'all')
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
  ui.todoCount = (await jobdesc.todo().catch(() => [])).length
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
      <RouterLink to="/jobdesc/new" class="btn btn--primary">Создать заявку</RouterLink>
    </Teleport>

    <SearchBox v-model="query" placeholder="Поиск: номер, должность, ЦФО, организация, имя файла" />
    <p v-if="query && !loading && !error" class="state" style="margin-bottom:8px">
      Поиск идёт по всем доступным заявкам, независимо от вкладки. Найдено: {{ items.length }}.
    </p>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">
      {{ query ? 'Ничего не найдено.' : emptyText }}
    </p>

    <ul v-else class="item-list">
      <li v-for="d in items" :key="d.id">
        <RouterLink :to="`/jobdesc/${d.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">{{ d.number }} · {{ d.position_name }}</span>
            <span class="status-pill" :class="d.status">{{ d.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ [d.organization_name, d.cfo_name, d.facility_name].filter(Boolean).join(' · ') }}
            <template v-if="d.is_nonstandard"> · нестандартная форма</template>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
