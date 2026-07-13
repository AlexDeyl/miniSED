<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, ApiError } from '@/services/api'
import { type Agreement, STATUS_LABELS } from '@/types/models'

const items = ref<Agreement[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await api.get<Agreement[]>('/agreements/todo/')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить задачи'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-head"><h1 class="page-title">Мои задачи</h1></div>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">Нет задач, требующих решения.</p>

    <ul v-else class="item-list">
      <li v-for="a in items" :key="a.id">
        <RouterLink :to="`/agreements/${a.id}`" class="item-card">
          <div class="item-title-row">
            <span class="item-title">#{{ a.id }} {{ a.title }}</span>
            <span class="status-pill" :class="a.status">{{ STATUS_LABELS[a.status] }}</span>
          </div>
          <div class="item-tags">
            <span v-if="a.amount" class="tag-chip">{{ a.amount }}</span>
            <span v-if="a.deadline" class="tag-chip">до {{ a.deadline }}</span>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
