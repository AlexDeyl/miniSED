<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { requests, type Organization } from '@/services/requests'
import { ApiError } from '@/services/api'
import type { RequestType } from '@/types/request'

const router = useRouter()

const requestType = ref<RequestType>('ecp')
const organization = ref<number | null>(null)
const subjectName = ref('')
const position = ref('')
const department = ref('')
const basis = ref('')

const orgs = ref<Organization[]>([])
const saving = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    orgs.value = await requests.organizations()
    if (orgs.value.length) organization.value = orgs.value[0].id
  } catch {
    /* пусто — покажем ошибку при сохранении */
  }
})

async function save() {
  error.value = null
  if (!organization.value) {
    error.value = 'Выберите организацию (сначала заведите её в справочнике)'
    return
  }
  saving.value = true
  try {
    const created = await requests.create({
      request_type: requestType.value,
      organization: organization.value,
      subject_name: subjectName.value.trim(),
      position: position.value.trim(),
      department: department.value.trim(),
      basis: basis.value.trim(),
    })
    router.push(`/requests/${created.id}`)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось создать'
    saving.value = false
  }
}
</script>

<template>
  <section>
    <RouterLink to="/requests" class="back-link">← К заявкам</RouterLink>
    <h1 class="page-title" style="margin-bottom:14px">Новая регламентная заявка</h1>

    <div class="form">
      <div class="form-row">
        <label class="form-field">
          <span>Тип заявки</span>
          <select v-model="requestType">
            <option value="ecp">Заявка на ЭЦП</option>
            <option value="mchd">Заявка на МЧД</option>
            <option value="poa">Заявка на доверенность</option>
          </select>
        </label>
        <label class="form-field">
          <span>Организация</span>
          <select v-model="organization">
            <option v-for="o in orgs" :key="o.id" :value="o.id">{{ o.short_name }}</option>
          </select>
        </label>
      </div>

      <label class="form-field">
        <span>Сотрудник (на кого оформляется)</span>
        <input v-model="subjectName" type="text" placeholder="Иванов Иван Иванович" />
      </label>

      <div class="form-row">
        <label class="form-field">
          <span>Должность</span>
          <input v-model="position" type="text" />
        </label>
        <label class="form-field">
          <span>Подразделение</span>
          <input v-model="department" type="text" />
        </label>
      </div>

      <label class="form-field">
        <span>Основание оформления</span>
        <input v-model="basis" type="text" placeholder="Приказ №… / служебная записка" />
      </label>

      <p v-if="error" class="state state--error">{{ error }}</p>

      <div>
        <button class="btn btn--primary" :disabled="saving" @click="save">
          {{ saving ? 'Сохранение…' : 'Создать черновик' }}
        </button>
      </div>
    </div>
  </section>
</template>
