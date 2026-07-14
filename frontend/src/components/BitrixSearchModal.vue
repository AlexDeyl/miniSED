<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { bitrix, type BitrixUser, type BitrixDeal } from '@/services/bitrix'

// Поиск сотрудников/сделок через серверный Bitrix Connector — работает и вне
// iframe (с домена), по сохранённому токену портала.
const props = defineProps<{ kind: 'users' | 'deals' }>()
const emit = defineEmits<{ pickUser: [u: BitrixUser]; pickDeal: [d: BitrixDeal]; close: [] }>()

const q = ref('')
const busy = ref(false)
const error = ref('')
const users = ref<BitrixUser[]>([])
const deals = ref<BitrixDeal[]>([])
const input = ref<HTMLInputElement | null>(null)

async function search() {
  busy.value = true
  error.value = ''
  try {
    if (props.kind === 'users') users.value = (await bitrix.searchUsers(q.value)).results
    else deals.value = (await bitrix.searchDeals(q.value)).results
  } catch {
    error.value = 'Не удалось получить данные из Битрикса. Откройте приложение из портала хотя бы раз, чтобы подключить его.'
  } finally {
    busy.value = false
  }
}

function userName(u: BitrixUser) {
  return [u.LAST_NAME, u.NAME, u.SECOND_NAME].filter(Boolean).join(' ') || `#${u.ID}`
}

onMounted(() => {
  input.value?.focus()
  search() // сразу показываем активных (пустой запрос)
})
</script>

<template>
  <div class="bsm-overlay" @click.self="emit('close')">
    <div class="bsm">
      <div class="bsm-head">
        <strong>{{ kind === 'users' ? 'Выбор сотрудника' : 'Выбор сделки' }}</strong>
        <button type="button" class="bsm-x" @click="emit('close')">×</button>
      </div>
      <div class="bsm-search">
        <input
          ref="input" v-model="q" class="fr-input"
          :placeholder="kind === 'users' ? 'ФИО или должность' : 'Название сделки'"
          @keyup.enter="search"
        />
        <button type="button" class="btn btn--primary" :disabled="busy" @click="search">Найти</button>
      </div>

      <p v-if="error" class="state state--error" style="margin:8px 0">{{ error }}</p>
      <p v-else-if="busy" class="state">Поиск…</p>

      <ul v-else class="bsm-list">
        <template v-if="kind === 'users'">
          <li v-if="!users.length" class="bsm-empty">Ничего не найдено.</li>
          <li v-for="u in users" :key="u.ID" class="bsm-item" @click="emit('pickUser', u)">
            <span class="bsm-name">{{ userName(u) }}</span>
            <span v-if="u.WORK_POSITION" class="bsm-sub">{{ u.WORK_POSITION }}</span>
          </li>
        </template>
        <template v-else>
          <li v-if="!deals.length" class="bsm-empty">Ничего не найдено.</li>
          <li v-for="d in deals" :key="d.ID" class="bsm-item" @click="emit('pickDeal', d)">
            <span class="bsm-name">#{{ d.ID }} {{ d.TITLE }}</span>
            <span v-if="d.OPPORTUNITY" class="bsm-sub">{{ d.OPPORTUNITY }} {{ d.CURRENCY_ID || '' }}</span>
          </li>
        </template>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.bsm-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); display: flex; align-items: flex-start; justify-content: center; padding-top: 8vh; z-index: 100; }
.bsm { width: 460px; max-width: 94vw; max-height: 76vh; background: #fff; border-radius: 12px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25); display: flex; flex-direction: column; overflow: hidden; }
.bsm-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--gray-border); }
.bsm-x { border: none; background: transparent; font-size: 20px; line-height: 1; cursor: pointer; color: var(--text-muted); }
.bsm-search { display: flex; gap: 8px; padding: 12px 14px; }
.bsm-search .fr-input { flex: 1; }
.bsm-list { list-style: none; margin: 0; padding: 0 6px 10px; overflow-y: auto; }
.bsm-item { padding: 9px 10px; border-radius: 8px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.bsm-item:hover { background: var(--green-light); }
.bsm-name { font-size: 14px; }
.bsm-sub { font-size: 12px; color: var(--text-muted); }
.bsm-empty { padding: 10px; color: var(--text-muted); font-size: 13px; }
</style>
