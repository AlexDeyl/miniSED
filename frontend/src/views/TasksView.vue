<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError } from '@/services/api'
import { type Agreement, STATUS_LABELS } from '@/types/models'

const items = ref<Agreement[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    // Согласования, где текущий пользователь должен принять решение.
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
  <section class="tasks">
    <h1 class="tasks__title">Мои задачи</h1>

    <p v-if="loading" class="tasks__state">Загрузка…</p>
    <p v-else-if="error" class="tasks__state tasks__state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="tasks__state">Нет задач, требующих решения.</p>

    <ul v-else class="tasks__list">
      <li v-for="a in items" :key="a.id" class="card">
        <RouterLink :to="`/agreements/${a.id}`" class="card__link">
          <div class="card__head">
            <span class="card__id">#{{ a.id }}</span>
            <span class="card__title">{{ a.title }}</span>
          </div>
          <div class="card__meta">
            <span class="badge" :data-status="a.status">{{ STATUS_LABELS[a.status] }}</span>
            <span v-if="a.amount" class="card__amount">{{ a.amount }}</span>
            <span v-if="a.deadline" class="card__deadline">до {{ a.deadline }}</span>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
