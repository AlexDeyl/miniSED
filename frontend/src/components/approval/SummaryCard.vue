<script setup lang="ts">
// Сводка: где сейчас документ и по каким датам он двигался.
import { fmtDateTime } from '@/composables/useApprovalCard'

defineProps<{
  roundNumber: number | null
  progress: { done: number; total: number }
  waitingFor: string
  createdAt: string | null | undefined
  submittedAt: string | null | undefined
  completedAt: string | null | undefined
  // Дополнительные строки модуля (напр. «Исполнена» у заявок на доверенность).
  extraRows?: { label: string; value: string }[]
}>()
</script>

<template>
  <div class="detail-card">
    <div class="detail-card-header">Сводка</div>
    <table class="round-table">
      <tbody>
        <tr v-if="roundNumber">
          <td>Круг</td>
          <td>{{ roundNumber }} · согласовали {{ progress.done }} из {{ progress.total }}</td>
        </tr>
        <tr><td>Сейчас решает</td><td>{{ waitingFor || '—' }}</td></tr>
        <tr><td>Создан</td><td>{{ fmtDateTime(createdAt) }}</td></tr>
        <tr><td>Отправлен</td><td>{{ fmtDateTime(submittedAt) }}</td></tr>
        <tr><td>Завершён</td><td>{{ fmtDateTime(completedAt) }}</td></tr>
        <tr v-for="r in extraRows || []" :key="r.label"><td>{{ r.label }}</td><td>{{ r.value }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
