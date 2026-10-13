<script setup lang="ts">
// Раздел «Заявки для отдела по работе с персоналом»: утверждённая заявка на
// ДИ не уходит письмом, а попадает сюда — её берут в работу, прикрепляют
// готовую ДИ и отмечают способ передачи (действия — в карточке заявки).
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { jobdesc } from '@/services/jobdesc'
import { ApiError } from '@/services/api'
import { useAdminModeStore } from '@/stores/adminMode'
import { useJobDescUiStore } from '@/stores/jobdescUi'
import SearchBox from '@/components/SearchBox.vue'
import type { HrStaffOption, JobDescListItem } from '@/types/jobdesc'

const adminMode = useAdminModeStore()
const ui = useJobDescUiStore()

const query = ref('')
const items = ref<JobDescListItem[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)

// Состав отдела (из Битрикса + назначенные вручную) — свёрнутая плашка.
const staff = ref<HrStaffOption[]>([])
const showStaff = ref(false)
const syncNote = ref('')

const emptyText = computed(() => ({
  new: 'Новых заявок нет.',
  work: 'В работе ничего нет.',
  signing: 'На подписании ничего нет.',
  done: 'Исполненных заявок пока нет.',
}[ui.hrScope]))

function fmt(dt: string | null): string {
  return dt ? new Date(dt).toLocaleDateString('ru') : ''
}

async function load() {
  loading.value = true
  error.value = null
  try {
    items.value = await jobdesc.hrQueue(ui.hrScope, query.value || undefined)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    loading.value = false
  }
}

async function refreshBadge() {
  ui.hrNewCount = (await jobdesc.hrQueue('new').catch(() => [])).length
}

async function take(id: number) {
  busy.value = true
  error.value = null
  try {
    await jobdesc.take(id)
    await Promise.all([load(), refreshBadge()])
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка операции'
  } finally {
    busy.value = false
  }
}

async function syncStaff() {
  busy.value = true
  syncNote.value = ''
  error.value = null
  try {
    const r = await jobdesc.syncHrStaff()
    staff.value = r.staff
    showStaff.value = true
    syncNote.value = `Из Битрикс24 (${r.departments.join(', ')}): ${r.total} чел., добавлено ${r.added}, снято ${r.removed}.`
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось обновить состав из Битрикс24'
  } finally {
    busy.value = false
  }
}

watch([() => ui.hrScope, query, () => adminMode.active], load)
onMounted(async () => {
  load()
  refreshBadge()
  staff.value = await jobdesc.hrStaff().catch(() => [])
})
</script>

<template>
  <section>
    <SearchBox v-model="query" placeholder="Поиск: номер, должность, ЦФО, организация, имя файла" />
    <p v-if="query && !loading && !error" class="state" style="margin-bottom:8px">
      Поиск идёт по всем заявкам раздела, независимо от вкладки. Найдено: {{ items.length }}.
    </p>

    <p v-if="loading" class="state">Загрузка…</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>
    <p v-else-if="items.length === 0" class="state">{{ query ? 'Ничего не найдено.' : emptyText }}</p>

    <ul v-else class="item-list">
      <li v-for="d in items" :key="d.id">
        <div class="item-card">
          <div class="item-title-row">
            <RouterLink :to="`/jobdesc/${d.id}`" class="item-title">{{ d.number }} · {{ d.position_name }}</RouterLink>
            <span class="status-pill" :class="d.status">{{ d.status_display }}</span>
          </div>
          <div class="item-sub">
            {{ [d.organization_name, d.cfo_name, d.facility_name].filter(Boolean).join(' · ') }}
            · от {{ fmt(d.created_at) }}
          </div>
          <div class="row-actions" style="margin-top:8px">
            <button v-if="d.status === 'to_hr'" class="btn btn--soft" :disabled="busy" @click="take(d.id)">
              Взять в работу
            </button>
            <RouterLink :to="`/jobdesc/${d.id}`" class="btn btn--ghost">Открыть</RouterLink>
          </div>
        </div>
      </li>
    </ul>

    <div class="detail-card staff-card">
      <div class="staff-head">
        <button type="button" class="link-btn" @click="showStaff = !showStaff">
          Сотрудники отдела: {{ staff.length }} {{ showStaff ? '▴' : '▾' }}
        </button>
        <button class="btn btn--ghost" style="font-size:13px" :disabled="busy" @click="syncStaff">
          Обновить из Битрикс24
        </button>
      </div>
      <p v-if="syncNote" class="detail-meta" style="margin:6px 0 0">{{ syncNote }}</p>
      <ul v-if="showStaff" class="staff-list">
        <li v-for="s in staff" :key="s.bitrix_id">{{ s.fio || `USER #${s.bitrix_id}` }}<span v-if="s.position"> · {{ s.position }}</span></li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.staff-card { margin-top: 18px; }
.staff-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.staff-list { margin: 8px 0 0; padding-left: 18px; font-size: 13px; color: var(--text-muted); }
.link-btn {
  background: none; border: none; padding: 0; color: var(--green-main); cursor: pointer;
  font: inherit; font-size: 13px; font-weight: 500;
}
</style>
