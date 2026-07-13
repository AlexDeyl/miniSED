<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { approvalflow } from '@/services/approvalflow'
import { ApiError } from '@/services/api'
import { type ApprovalListItem, APPROVAL_STATUS_CLASS } from '@/types/approval'

const items = ref<ApprovalListItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await approvalflow.list()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="flow">
    <div class="flow__head">
      <h1 class="flow__title">Согласования</h1>
      <RouterLink to="/flow/new" class="btn btn--primary">Создать</RouterLink>
    </div>

    <p v-if="loading" class="flow__state">Загрузка…</p>
    <p v-else-if="error" class="flow__state flow__state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="flow__state">Пока нет согласований.</p>

    <ul v-else class="flow__list">
      <li v-for="a in items" :key="a.id" class="card">
        <RouterLink :to="`/flow/${a.id}`" class="card__link">
          <div class="card__head">
            <span class="card__id">#{{ a.id }}</span>
            <span class="card__title">{{ a.title || '(без названия)' }}</span>
          </div>
          <div class="card__meta">
            <span class="badge" :data-status="APPROVAL_STATUS_CLASS[a.status]">
              {{ a.status_display }}
            </span>
            <span>{{ a.approval_type }}</span>
            <span v-if="a.current_round">круг {{ a.current_round }}</span>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
