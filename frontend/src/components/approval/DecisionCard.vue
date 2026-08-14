<script setup lang="ts">
// «Ваше решение» — общая карточка для всех модулей на движке approvalflow.
// Комментарий обязателен при отклонении (это же проверяет и сервер).
import { ref } from 'vue'
import { fmtDateTime } from '@/composables/useApprovalCard'
import type { ApprovalParticipant } from '@/types/approval'

const props = defineProps<{
  pending: ApprovalParticipant | null
  myPart: ApprovalParticipant | null
  myDecided: ApprovalParticipant | null
  isParticipant: boolean
  busy: boolean
  roleName: (code: string | undefined) => string
  label: (p: ApprovalParticipant) => string
}>()

const emit = defineEmits<{
  decide: [participant: ApprovalParticipant, decision: 'approve' | 'reject', comment: string]
  error: [message: string]
}>()

const DECISION_RU: Record<string, string> = {
  waiting: 'Ожидает', approved: 'Согласовано', rejected: 'Отклонено',
}

const comment = ref('')

function decide(decision: 'approve' | 'reject') {
  if (!props.myPart) return
  const text = comment.value.trim()
  if (decision === 'reject' && !text) {
    emit('error', 'При отклонении комментарий обязателен.')
    return
  }
  emit('decide', props.myPart, decision, text)
  comment.value = ''
}
</script>

<template>
  <div v-if="myPart || myDecided || isParticipant" class="detail-card">
    <div class="detail-card-header">Ваше решение</div>

    <template v-if="myPart">
      <div class="detail-meta" style="margin-bottom:6px">
        Сейчас очередь за вами<template v-if="myPart.role"> — как «{{ roleName(myPart.role) }}»</template>.
      </div>
      <textarea
        v-model="comment" rows="3" class="decision-comment"
        placeholder="Комментарий (при отклонении обязателен)"
      ></textarea>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <button class="btn btn--primary" :disabled="busy" @click="decide('approve')">Согласовать</button>
        <button class="btn btn--danger" :disabled="busy" @click="decide('reject')">Отклонить</button>
      </div>
    </template>

    <template v-else-if="myDecided">
      <div>
        Ваше решение:
        <span class="participant-pill" :class="myDecided.decision">
          {{ DECISION_RU[myDecided.decision] || myDecided.decision }}
        </span>
        <span class="detail-meta"> · {{ fmtDateTime(myDecided.decided_at) }}</span>
      </div>
      <div v-if="myDecided.decision_comment" class="detail-meta" style="margin-top:4px">
        {{ myDecided.decision_comment }}
      </div>
    </template>

    <div v-else class="detail-meta">
      <template v-if="pending">Ждём решения: {{ label(pending) }}.</template>
      <template v-else>Ваше решение сейчас не требуется.</template>
    </div>
  </div>
</template>

<style scoped>
.decision-comment {
  width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #d0d0d0;
  border-radius: 6px; font: inherit; font-size: 13px; resize: vertical;
}
</style>
