<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { bitrix, type BitrixDeal } from '@/services/bitrix'
import { ApiError } from '@/services/api'

const query = ref('')
const deals = ref<BitrixDeal[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const connected = ref<boolean | null>(null)

onMounted(async () => {
  try {
    connected.value = (await bitrix.status()).connected
  } catch {
    connected.value = false
  }
})

let timer: ReturnType<typeof setTimeout> | undefined
function onInput() {
  clearTimeout(timer)
  timer = setTimeout(search, 350)
}

async function search() {
  const q = query.value.trim()
  if (!q) {
    deals.value = []
    return
  }
  loading.value = true
  error.value = null
  try {
    deals.value = (await bitrix.searchDeals(q)).results
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Ошибка поиска'
    deals.value = []
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="deals">
    <h1 class="deals__title">Поиск CRM-сделок</h1>

    <p v-if="connected === false" class="deals__hint">
      Портал Битрикс24 не подключён. Откройте MiniSED из Битрикс24 или пройдите
      авторизацию — тогда поиск будет работать и напрямую с домена.
    </p>

    <input
      v-model="query"
      class="deals__input"
      type="search"
      placeholder="Название сделки…"
      @input="onInput"
    />

    <p v-if="loading" class="deals__state">Поиск…</p>
    <p v-else-if="error" class="deals__state deals__state--error">{{ error }}</p>
    <p v-else-if="query && deals.length === 0" class="deals__state">Ничего не найдено.</p>

    <ul v-else class="deals__list">
      <li v-for="d in deals" :key="d.ID" class="card">
        <div class="card__link">
          <div class="card__head">
            <span class="card__id">#{{ d.ID }}</span>
            <span class="card__title">{{ d.TITLE }}</span>
          </div>
          <div v-if="d.OPPORTUNITY" class="card__meta">
            <span>{{ d.OPPORTUNITY }} {{ d.CURRENCY_ID }}</span>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
