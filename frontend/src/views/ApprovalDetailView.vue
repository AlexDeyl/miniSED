<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { approvalflow } from '@/services/approvalflow'
import { api, ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { ApprovalDetail, ApprovalParticipant } from '@/types/approval'
import DocumentEditor from '@/components/DocumentEditor.vue'

const props = defineProps<{ id: string }>()
const auth = useAuthStore()

const approval = ref<ApprovalDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    approval.value = await approvalflow.get(props.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

function canDecide(p: ApprovalParticipant): boolean {
  return (
    approval.value?.status === 'in_progress' &&
    p.decision === 'waiting' &&
    p.type === 'internal' &&
    p.b24_user_id === auth.b24UserId
  )
}

async function run(fn: () => Promise<ApprovalDetail>) {
  busy.value = true
  error.value = null
  try {
    approval.value = await fn()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

function decide(p: ApprovalParticipant, decision: 'approve' | 'reject') {
  let comment = ''
  if (decision === 'reject') {
    comment = window.prompt('Комментарий (обязателен при отклонении):') || ''
    if (!comment.trim()) return
  }
  run(() => approvalflow.decide(approval.value!.id, p.id, decision, comment))
}

async function generateSheet() {
  busy.value = true
  error.value = null
  try {
    await approvalflow.generateSheet(approval.value!.id)
    approval.value = await approvalflow.get(props.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сформировать лист'
  } finally {
    busy.value = false
  }
}

function dl(url: string | null, name: string) {
  if (url) api.download(url, name).catch((e) => (error.value = e.message))
}

// Онлайн-редактирование (ТЗ п.7.2-7.3): открываем оверлей редактора по id документа.
const editingDocId = ref<number | null>(null)
function onEditorClose(changed: boolean) {
  editingDocId.value = null
  // если документ правился — перечитать, чтобы показать новую версию
  if (changed) load()
}

const fileInput = ref<HTMLInputElement | null>(null)
async function uploadFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  error.value = null
  try {
    await approvalflow.uploadDocument(approval.value!.id, file)
    approval.value = await approvalflow.get(props.id)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Не удалось загрузить файл'
  } finally {
    busy.value = false
    input.value = ''
  }
}

const isInitiator = computed(() => approval.value?.initiator_b24_id === auth.b24UserId)

onMounted(load)
</script>

<template>
  <section>
    <RouterLink to="/flow" class="back-link">← К списку</RouterLink>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error && !approval" class="state state--error">{{ error }}</p>

    <template v-else-if="approval">
      <div class="detail-header-main">
        <div>
          <h1 class="detail-title">#{{ approval.id }} {{ approval.title || '(без названия)' }}</h1>
          <div class="detail-meta">
            {{ approval.approval_type }} ·
            {{ approval.flow_type === 'parallel' ? 'параллельное' : 'последовательное' }}
            · инициатор #{{ approval.initiator_b24_id }}
          </div>
        </div>
        <span class="status-pill" :class="approval.status">{{ approval.status_display }}</span>
      </div>

      <p v-if="error" class="state state--error">{{ error }}</p>

      <!-- Круги -->
      <div v-for="rnd in approval.rounds" :key="rnd.id" class="detail-card">
        <div class="detail-card-header">
          Круг {{ rnd.round_number }}
          <span class="participant-pill" :class="rnd.result">{{ rnd.result }}</span>
        </div>
        <table class="round-table">
          <thead>
            <tr><th>Согласующий</th><th>Роль</th><th>Решение</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="p in rnd.participants" :key="p.id">
              <td>{{ p.type === 'internal' ? `USER #${p.b24_user_id}` : p.email }}</td>
              <td>{{ p.role || '—' }}</td>
              <td>
                <span class="participant-pill" :class="p.decision">{{ p.decision }}</span>
                <em v-if="p.decision_comment"> — {{ p.decision_comment }}</em>
              </td>
              <td class="row-actions">
                <template v-if="canDecide(p)">
                  <button class="btn btn--ok" :disabled="busy" @click="decide(p, 'approve')">✓</button>
                  <button class="btn btn--no" :disabled="busy" @click="decide(p, 'reject')">✕</button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="rnd.comment" class="muted" style="margin:8px 0 0">Комментарий круга: {{ rnd.comment }}</p>
      </div>

      <!-- Документы (несколько) -->
      <div class="detail-card">
        <div class="detail-card-header">Документы</div>
        <ul v-if="approval.documents.length" class="item-tags" style="flex-direction:column;align-items:flex-start;gap:6px;margin-bottom:8px">
          <li v-for="d in approval.documents" :key="d.id">
            <a href="#" @click.prevent="dl(d.download_url, d.title)">{{ d.title }} (в{{ d.current_version_number }})</a>
            <button
              v-if="d.can_edit_online"
              class="btn btn--ghost"
              style="margin-left:8px;font-size:12px;padding:2px 8px"
              @click="editingDocId = d.id"
            >
              ✏️ Онлайн
            </button>
          </li>
        </ul>
        <p v-else class="muted" style="margin:0 0 8px">Файлов пока нет.</p>
        <input ref="fileInput" type="file" style="display:none" @change="uploadFile" />
        <button class="btn btn--ghost" :disabled="busy" @click="fileInput?.click()">Прикрепить документ</button>
      </div>

      <!-- Лист согласования -->
      <div class="detail-card">
        <div class="detail-card-header">Лист согласования</div>
        <ul v-if="approval.sheets.length" class="item-tags" style="flex-direction:column;align-items:flex-start;gap:6px;margin-bottom:8px">
          <li v-for="s in approval.sheets" :key="s.id">
            <a href="#" @click.prevent="dl(s.file_url, `Лист_${approval.id}.pdf`)">
              Лист от {{ new Date(s.generated_at).toLocaleString('ru') }} (PDF)
            </a>
          </li>
        </ul>
        <button v-if="isInitiator" class="btn btn--ghost" :disabled="busy" @click="generateSheet">
          Сформировать лист (PDF)
        </button>
      </div>
    </template>

    <!-- Оверлей онлайн-редактора (ТЗ п.7.2-7.3) -->
    <DocumentEditor
      v-if="editingDocId"
      :doc-id="editingDocId"
      @close="onEditorClose"
    />
  </section>
</template>
