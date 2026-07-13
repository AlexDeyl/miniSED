<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { approvalflow } from '@/services/approvalflow'
import { ApiError } from '@/services/api'
import type { FlowType, ParticipantInput } from '@/types/approval'

const router = useRouter()

const title = ref('')
const approvalType = ref('generic')
const flowType = ref<FlowType>('parallel')
const rows = ref<{ b24_user_id: string; role: string }[]>([{ b24_user_id: '', role: '' }])
const saving = ref(false)
const error = ref<string | null>(null)

function addRow() {
  rows.value.push({ b24_user_id: '', role: '' })
}
function removeRow(i: number) {
  rows.value.splice(i, 1)
}

async function save() {
  error.value = null
  const participants: ParticipantInput[] = rows.value
    .map((r, idx) => ({
      type: 'internal' as const,
      b24_user_id: parseInt(r.b24_user_id, 10),
      role: r.role.trim(),
      order: idx,
    }))
    .filter((p) => !Number.isNaN(p.b24_user_id))

  if (!title.value.trim()) {
    error.value = 'Укажите название'
    return
  }
  if (participants.length === 0) {
    error.value = 'Добавьте хотя бы одного согласующего (ID Б24)'
    return
  }

  saving.value = true
  try {
    const created = await approvalflow.create({
      approval_type: approvalType.value.trim() || 'generic',
      title: title.value.trim(),
      flow_type: flowType.value,
    })
    await approvalflow.submit(created.id, participants)
    router.push(`/flow/${created.id}`)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать'
    saving.value = false
  }
}
</script>

<template>
  <section>
    <RouterLink to="/flow" class="back-link">← К списку</RouterLink>
    <h1 class="page-title" style="margin-bottom:14px">Новое согласование</h1>

    <div class="form">
      <label class="form-field">
        <span>Название</span>
        <input v-model="title" type="text" placeholder="Скидка 10% по сделке №42" />
      </label>

      <div class="form-row">
        <label class="form-field">
          <span>Тип</span>
          <input v-model="approvalType" type="text" placeholder="discount / generic" />
        </label>
        <label class="form-field">
          <span>Порядок согласования</span>
          <select v-model="flowType">
            <option value="parallel">Параллельное</option>
            <option value="sequential">Последовательное</option>
          </select>
        </label>
      </div>

      <div class="form-field">
        <span>Согласующие (ID сотрудника Б24)</span>
        <div v-for="(row, i) in rows" :key="i" class="form-participant">
          <input v-model="row.b24_user_id" type="number" placeholder="ID Б24" />
          <input v-model="row.role" type="text" placeholder="роль (опц.)" />
          <button type="button" class="btn btn--ghost" :disabled="rows.length === 1" @click="removeRow(i)">✕</button>
        </div>
        <button type="button" class="btn btn--ghost" @click="addRow">+ участник</button>
      </div>

      <p v-if="error" class="state state--error">{{ error }}</p>

      <div>
        <button class="btn btn--primary" :disabled="saving" @click="save">
          {{ saving ? 'Отправка…' : 'Создать и отправить' }}
        </button>
      </div>
    </div>
  </section>
</template>
