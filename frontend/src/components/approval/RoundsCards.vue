<script setup lang="ts">
// Круги согласования: кто, роль, решение, дата, комментарий.
import { fmtDateTime } from '@/composables/useApprovalCard'
import type { ApprovalParticipant, ApprovalRound } from '@/types/approval'

defineProps<{
  rounds: ApprovalRound[]
  pendingId: number | null
  roleName: (code: string | undefined) => string
  label: (p: ApprovalParticipant) => string
}>()

const DECISION_RU: Record<string, string> = {
  waiting: 'Ожидает', approved: 'Согласовано', rejected: 'Отклонено',
}
const RESULT_RU: Record<string, string> = {
  pending: 'В процессе', approved: 'Согласован', rejected: 'Отклонён', returned: 'Возвращён',
}
</script>

<template>
  <div v-for="rnd in rounds" :key="rnd.id" class="detail-card">
    <div class="detail-card-header">
      Круг {{ rnd.round_number }}
      <span class="participant-pill" :class="rnd.result">{{ RESULT_RU[rnd.result] || rnd.result }}</span>
    </div>
    <table class="round-table">
      <tbody>
        <tr v-for="p in rnd.participants" :key="p.id">
          <td>{{ roleName(p.role) }}</td>
          <td>
            {{ label(p) }}
            <span v-if="pendingId === p.id" class="participant-pill" style="background:#fff3cd">сейчас решает</span>
          </td>
          <td>
            <span class="participant-pill" :class="p.decision">{{ DECISION_RU[p.decision] || p.decision }}</span>
            <!-- Решение проставил администратор за согласующего: место в
                 маршруте остаётся за ним, но виза не его. -->
            <span v-if="p.admin_override_by_b24_id" class="participant-pill admin-mark">
              администратором
            </span>
            <span v-if="p.decided_at" class="detail-meta"> · {{ fmtDateTime(p.decided_at) }}</span>
            <em v-if="p.decision_comment"> — {{ p.decision_comment }}</em>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
