<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
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
  <section>
    <RouterLink to="/tasks" class="back-link">← К задачам</RouterLink>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>

    <template v-else-if="agreement">
      <div class="detail-header-main">
        <div>
          <h1 class="detail-title">#{{ agreement.id }} {{ agreement.title }}</h1>
          <div class="detail-meta" v-if="agreement.description">{{ agreement.description }}</div>
        </div>
        <span class="status-pill" :class="agreement.status">{{ STATUS_LABELS[agreement.status] }}</span>
      </div>

      <div class="detail-card">
        <div class="detail-card-header">Основное</div>
        <div class="item-tags">
          <span v-if="agreement.amount" class="tag-chip">Сумма: {{ agreement.amount }}</span>
          <span v-if="agreement.deadline" class="tag-chip">Дедлайн: {{ agreement.deadline }}</span>
          <a v-if="agreement.crm_link" :href="agreement.crm_link" target="_blank" rel="noopener" class="tag-chip">CRM-сделка ↗</a>
        </div>
      </div>

      <div class="detail-card">
        <div class="detail-card-header">Участники</div>
        <table class="round-table">
          <tbody>
            <tr v-for="p in agreement.participants" :key="p.id">
              <td>{{ p.type === 'internal' ? `USER #${p.b24_user_id}` : p.email }}</td>
              <td>
                <span class="participant-pill" :class="p.status">{{ p.status }}</span>
                <em v-if="p.comment"> — {{ p.comment }}</em>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="agreement.documents.length" class="detail-card">
        <div class="detail-card-header">Документы</div>
        <div class="item-tags" style="flex-direction:column;align-items:flex-start;gap:6px">
          <a v-for="d in agreement.documents" :key="d.id" :href="d.file || d.url" target="_blank" rel="noopener">
            {{ d.name }}
          </a>
        </div>
      </div>
    </template>
  </section>
</template>
