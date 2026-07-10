<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError } from '@/services/api'
import { type Agreement, STATUS_LABELS } from '@/types/models'

const props = defineProps<{ id: string }>()

const agreement = ref<Agreement | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    agreement.value = await api.get<Agreement>(`/agreements/${props.id}/`)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить карточку'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="detail">
    <RouterLink to="/tasks" class="detail__back">← К задачам</RouterLink>

    <p v-if="loading" class="detail__state">Загрузка…</p>
    <p v-else-if="error" class="detail__state detail__state--error">{{ error }}</p>

    <template v-else-if="agreement">
      <header class="detail__head">
        <h1>#{{ agreement.id }} {{ agreement.title }}</h1>
        <span class="badge" :data-status="agreement.status">
          {{ STATUS_LABELS[agreement.status] }}
        </span>
      </header>

      <p v-if="agreement.description" class="detail__desc">{{ agreement.description }}</p>

      <dl class="detail__grid">
        <template v-if="agreement.amount">
          <dt>Сумма</dt><dd>{{ agreement.amount }}</dd>
        </template>
        <template v-if="agreement.deadline">
          <dt>Дедлайн</dt><dd>{{ agreement.deadline }}</dd>
        </template>
        <template v-if="agreement.crm_link">
          <dt>CRM</dt>
          <dd><a :href="agreement.crm_link" target="_blank" rel="noopener">сделка</a></dd>
        </template>
      </dl>

      <h2 class="detail__subtitle">Участники</h2>
      <ul class="detail__participants">
        <li v-for="p in agreement.participants" :key="p.id">
          <span class="badge" :data-pstatus="p.status">{{ p.status }}</span>
          {{ p.type === 'internal' ? `USER #${p.b24_user_id}` : p.email }}
          <em v-if="p.comment">— {{ p.comment }}</em>
        </li>
      </ul>

      <h2 v-if="agreement.documents.length" class="detail__subtitle">Документы</h2>
      <ul v-if="agreement.documents.length" class="detail__docs">
        <li v-for="d in agreement.documents" :key="d.id">
          <a :href="d.file || d.url" target="_blank" rel="noopener">{{ d.name }}</a>
        </li>
      </ul>
    </template>
  </section>
</template>
