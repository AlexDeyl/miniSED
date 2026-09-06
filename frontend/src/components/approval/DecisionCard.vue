<script setup lang="ts">
// «Ваше решение» — общая карточка для всех модулей на движке approvalflow.
// Комментарий обязателен при отклонении (это же проверяет и сервер).
import { ref } from 'vue'
import { fmtDateTime } from '@/composables/useApprovalCard'
import { useAdminModeStore } from '@/stores/adminMode'
import type { ApprovalParticipant } from '@/types/approval'

const adminMode = useAdminModeStore()

const props = defineProps<{
  pending: ApprovalParticipant | null
  myPart: ApprovalParticipant | null
  myDecided: ApprovalParticipant | null
  isParticipant: boolean
  /** Ещё не решившие участники круга — для режима администратора. */
  waiting?: ApprovalParticipant[]
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
  submit(props.myPart, decision)
}

// Режим администратора: решение за конкретного согласующего. Комментарий свой
// на каждого — иначе один текст уехал бы во все визы сразу.
const adminComment = ref<Record<number, string>>({})

function decideFor(p: ApprovalParticipant, decision: 'approve' | 'reject') {
  submit(p, decision, adminComment.value[p.id] || '')
  delete adminComment.value[p.id]
}

function submit(p: ApprovalParticipant, decision: 'approve' | 'reject', text?: string) {
  const value = (text ?? comment.value).trim()
  if (decision === 'reject' && !value) {
    emit('error', 'При отклонении комментарий обязателен.')
    return
  }
  emit('decide', p, decision, value)
  if (text === undefined) comment.value = ''
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

  <!-- Режим администратора: решение за любого согласующего, на любом этапе.
       Каждое такое решение сохраняется с пометкой «администратором». -->
  <div v-if="adminMode.active && (waiting || []).length" class="detail-card admin-card">
    <div class="detail-card-header">Решение за согласующего · режим администратора</div>
    <div class="detail-meta" style="margin-bottom:8px">
      Виза сохранится с пометкой, что её проставил администратор.
    </div>
    <div v-for="p in waiting" :key="p.id" class="admin-row">
      <div class="admin-row-who">
        {{ label(p) }}<template v-if="p.role"> · {{ roleName(p.role) }}</template>
        <span v-if="pending && pending.id === p.id" class="participant-pill" style="background:#fff3cd">
          сейчас его очередь
        </span>
      </div>
      <textarea
        v-model="adminComment[p.id]" rows="2" class="decision-comment"
        placeholder="Комментарий (при отклонении обязателен)"
      ></textarea>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">
        <button class="btn btn--soft" :disabled="busy" @click="decideFor(p, 'approve')">
          Согласовать за него
        </button>
        <button class="btn btn--danger" :disabled="busy" @click="decideFor(p, 'reject')">
          Отклонить за него
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-card { border: 1px solid #ffd9a8; }
.admin-row { padding: 10px 0; border-top: 1px solid #f1f1f1; }
.admin-row:first-of-type { border-top: 0; }
.admin-row-who { font-size: 13px; margin-bottom: 6px; }
.decision-comment {
  width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #d0d0d0;
  border-radius: 6px; font: inherit; font-size: 13px; resize: vertical;
}
</style>
