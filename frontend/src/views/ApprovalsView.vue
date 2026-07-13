<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { approvalflow } from '@/services/approvalflow'
import { ApiError } from '@/services/api'
import type { ApprovalListItem } from '@/types/approval'

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
  <section>
    <div class="page-head">
      <h1 class="page-title">Согласования</h1>
      <RouterLink to="/flow/new" class="btn btn--primary">Создать</RouterLink>
    </div>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">Пока нет согласований.</p>

    <ul v-else class="item-list">
      <li v-for="a in items" :key="a.id">
        <RouterLink :to="`/flow/${a.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">#{{ a.id }} {{ a.title || '(без названия)' }}</span>
            <span class="status-pill" :class="a.status">{{ a.status_display }}</span>
          </div>
          <div class="item-tags">
            <span class="tag-chip">{{ a.approval_type }}</span>
            <span v-if="a.current_round" class="tag-chip">круг {{ a.current_round }}</span>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
