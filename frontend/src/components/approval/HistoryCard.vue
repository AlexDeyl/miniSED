<script setup lang="ts">
// Лента «История согласования»: решения по кругам в хронологии.
import { fmtDateTime, type HistoryGroup } from '@/composables/useApprovalCard'

defineProps<{ history: HistoryGroup[] }>()

const RESULT_RU: Record<string, string> = {
  pending: 'В процессе', approved: 'Согласован', rejected: 'Отклонён', returned: 'Возвращён',
}
</script>

<template>
  <div v-if="history.length" class="detail-card">
    <div class="detail-card-header">История согласования</div>
    <div v-for="grp in history" :key="grp.round" style="margin-bottom:10px">
      <div style="font-weight:600;font-size:12px;margin-bottom:4px">
        Круг {{ grp.round }} · отправлен {{ fmtDateTime(grp.started_at) }}
        <span class="participant-pill" :class="grp.result">{{ RESULT_RU[grp.result] || grp.result }}</span>
      </div>
      <p v-if="!grp.events.length" class="detail-meta" style="margin:0">Решений пока нет.</p>
      <div v-for="ev in grp.events" :key="ev.key" class="log-item">
        <b>{{ ev.who }}</b>
        <span :style="{ color: ev.ok === null ? 'inherit' : ev.ok ? 'var(--green-main)' : 'var(--red-main)' }">
          {{ ev.what }}</span>
        · {{ fmtDateTime(ev.when) }}
        <div v-if="ev.comment" class="detail-meta">{{ ev.comment }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-item { font-size: 12px; margin-bottom: 8px; }
</style>
