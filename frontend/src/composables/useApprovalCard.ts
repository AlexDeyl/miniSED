import { computed, type ComputedRef } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { ApprovalDetail, ApprovalParticipant, RoundResult } from '@/types/approval'

// Одно событие ленты «История согласования».
export interface HistoryEvent {
  key: string
  when: string
  who: string
  what: string
  ok: boolean | null
  comment: string
}

export interface HistoryGroup {
  round: number
  result: RoundResult
  started_at: string
  events: HistoryEvent[]
}

export function isGroupLegal(p: ApprovalParticipant): boolean {
  return p.role === 'legal_dept' && !p.b24_user_id
}

/**
 * Общая логика карточки согласования: чья очередь, моё решение, лента истории,
 * прогресс круга. Одинакова для договоров, регламентных заявок и будущих
 * модулей — движок под ними один (approvalflow).
 *
 * approval — источник данных карточки; active — идёт ли согласование прямо
 * сейчас (у каждого модуля свой код статуса); label — как подписывать участника.
 */
export function useApprovalCard(
  approval: () => ApprovalDetail | null | undefined,
  active: () => boolean,
  label: (p: ApprovalParticipant) => string,
) {
  const auth = useAuthStore()

  const rounds = computed(() => approval()?.rounds || [])
  const currentRound = computed(() => rounds.value[rounds.value.length - 1] || null)

  // Маршрут последовательный: решает первый ожидающий по order — ровно это
  // проверяет и движок (approvalflow.services._is_turn).
  const pendingPart: ComputedRef<ApprovalParticipant | null> = computed(() => {
    if (!active() || !currentRound.value) return null
    return [...currentRound.value.participants]
      .sort((a, b) => a.order - b.order)
      .find((p) => p.decision === 'waiting') || null
  })

  function isMine(p: ApprovalParticipant): boolean {
    if (p.type !== 'internal') return false
    // Групповой юрэтап закреплён не за человеком, а за юротделом.
    return isGroupLegal(p) ? auth.isLawyer : p.b24_user_id === auth.b24UserId
  }

  const myPart = computed(() =>
    pendingPart.value && isMine(pendingPart.value) ? pendingPart.value : null,
  )
  const myDecided = computed(
    () => currentRound.value?.participants.find((p) => isMine(p) && p.decision !== 'waiting') || null,
  )
  const iAmParticipant = computed(() => rounds.value.some((r) => r.participants.some(isMine)))

  // Все, кто ещё не принял решение в текущем круге — для режима администратора:
  // он закрывает любой этап, в том числе не наступивший.
  const waitingParts = computed(() => {
    if (!active() || !currentRound.value) return []
    return [...currentRound.value.participants]
      .filter((p) => p.decision === 'waiting')
      .sort((a, b) => a.order - b.order)
  })

  const progress = computed(() => {
    const parts = currentRound.value?.participants || []
    return { done: parts.filter((p) => p.decision !== 'waiting').length, total: parts.length }
  })

  const history = computed<HistoryGroup[]>(() =>
    rounds.value.map((rnd) => {
      const events: HistoryEvent[] = rnd.participants
        .filter((p) => p.decided_at)
        .map((p) => ({
          key: `p${p.id}`,
          when: p.decided_at as string,
          who: label(p),
          // Решение за согласующего проставил администратор — в ленте это
          // должно читаться сразу, а не только по значку в маршруте.
          what: (p.decision === 'approved' ? 'согласовал(а)' : 'отклонил(а)')
            + (p.admin_override_by_b24_id ? ' (администратором)' : ''),
          ok: p.decision === 'approved',
          comment: p.decision_comment,
        }))
        .sort((a, b) => a.when.localeCompare(b.when))
      // Чем инициатор открыл круг: пояснение согласующим, что изменилось после
      // доработки. Идёт первым событием — это начало круга.
      if (rnd.opening_comment) {
        events.unshift({
          key: `o${rnd.id}`, when: rnd.started_at, who: 'Инициатор',
          what: rnd.round_number > 1 ? 'направил(а) повторно' : 'направил(а) на согласование',
          ok: null, comment: rnd.opening_comment,
        })
      }
      if (rnd.result === 'returned' && rnd.completed_at) {
        events.push({
          key: `r${rnd.id}`, when: rnd.completed_at, who: 'Инициатор',
          what: 'вернул(а) на доработку', ok: null, comment: rnd.comment,
        })
      }
      return { round: rnd.round_number, result: rnd.result, started_at: rnd.started_at, events }
    }),
  )

  return {
    rounds, currentRound, pendingPart, myPart, myDecided, iAmParticipant,
    waitingParts, progress, history,
  }
}

export function fmtDateTime(dt: string | null | undefined): string {
  return dt ? new Date(dt).toLocaleString('ru') : '—'
}
