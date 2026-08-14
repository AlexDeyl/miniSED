<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { contracts } from '@/services/contracts'
import { ApiError } from '@/services/api'
import { useContractsUiStore } from '@/stores/contractsUi'
import type { ContractListItem, ContractStatus } from '@/types/contract'

const ui = useContractsUiStore()

const items = ref<ContractListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

// Какие статусы показывает вкладка (todo грузится отдельным эндпоинтом).
const STATUS_BY_MODE: Record<string, ContractStatus[]> = {
  draft: ['draft'],
  in_progress: ['on_approval'],
  completed: ['approved'],
  rejected: ['rejected', 'returned'],
}

const emptyText = computed(() =>
  ui.mode === 'todo' ? 'Договоров, ждущих вашего решения, нет.' : 'Договоров пока нет.',
)

function money(v: string | null): string {
  if (!v) return ''
  const n = Number(v)
  return Number.isNaN(n) ? '' : n.toLocaleString('ru-RU') + ' ₽'
}

async function load() {
  loading.value = true
  error.value = null
  try {
    if (ui.mode === 'todo') {
      items.value = await contracts.todo()
    } else {
      // Черновики бывают только свои; в остальных вкладках показываем и те
      // договоры, где я согласующий (иначе после отправки они пропадают из вида).
      const all = await contracts.list(ui.mode === 'draft' ? 'mine' : 'all')
      const statuses = STATUS_BY_MODE[ui.mode]
      items.value = statuses ? all.filter((c) => statuses.includes(c.status)) : all
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

// Бейдж вкладки «Требуется действие» виден независимо от активной вкладки.
async function refreshBadge() {
  ui.todoCount = (await contracts.todo().catch(() => [])).length
}

watch(() => ui.mode, load)
onMounted(() => {
  load()
  refreshBadge()
})
</script>

<template>
  <section>
    <Teleport to="#header-actions">
      <RouterLink to="/contracts/new" class="btn btn--primary">Создать договор</RouterLink>
    </Teleport>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">{{ emptyText }}</p>

    <ul v-else class="item-list">
      <li v-for="c in items" :key="c.id">
        <RouterLink :to="`/contracts/${c.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">{{ c.number }} · {{ c.title }}</span>
            <span class="status-pill" :class="c.status">{{ c.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ c.organization_name }}<template v-if="c.cfo_name"> · {{ c.cfo_name }}</template>
            <template v-if="c.amount"> · {{ money(c.amount) }}</template>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
