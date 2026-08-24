<script setup lang="ts">
// Просмотр PDF прямо в карточке — чтобы не скачивать файл ради того, чтобы
// на него взглянуть. Показываем во встроенной смотрелке браузера; файл тянем
// через fetch с заголовками авторизации и отдаём iframe как blob-URL.
import { onBeforeUnmount, ref, watch } from 'vue'
import { api, ApiError } from '@/services/api'

const props = withDefaults(
  defineProps<{ src: string; title?: string; filename?: string; height?: string }>(),
  { title: 'Просмотр', filename: 'document.pdf', height: 'calc(100vh - 190px)' },
)

// Параметры встроенной смотрелки браузера (Chrome/Edge читают их из #-части):
// navpanes=0 убирает панель миниатюр слева — она съедала половину ширины,
// view=FitH подгоняет страницу по ширине, чтобы не было горизонтальной
// прокрутки. Панель инструментов оставляем: в ней зум и печать.
const VIEWER_PARAMS = '#toolbar=1&navpanes=0&scrollbar=1&pagemode=none&view=FitH'

const url = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const collapsed = ref(false)

function release() {
  if (url.value) {
    // revokeObjectURL ждёт ЧИСТЫЙ blob-адрес — с #-хвостом объект не освободится.
    URL.revokeObjectURL(url.value.split('#')[0])
    url.value = ''
  }
}

async function load() {
  release()
  if (!props.src) return
  loading.value = true
  error.value = null
  try {
    url.value = (await api.blobUrl(props.src)) + VIEWER_PARAMS
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить документ'
  } finally {
    loading.value = false
  }
}

function download() {
  api.download(props.src, props.filename).catch((e) => (error.value = e.message))
}

// Открыть крупно: blob-URL живёт, пока открыта эта вкладка приложения.
function openFull() {
  // В отдельной вкладке открываем без наших параметров: там места много,
  // пусть работает полная смотрелка со всеми панелями.
  if (url.value) window.open(url.value.split('#')[0], '_blank', 'noopener')
}

watch(() => props.src, load, { immediate: true })
onBeforeUnmount(release)

defineExpose({ reload: load })
</script>

<template>
  <div class="detail-card pdf-card">
    <div class="detail-card-header pdf-header">
      <span>{{ title }}</span>
      <span class="pdf-actions">
        <button class="btn btn--ghost btn--sm" @click="collapsed = !collapsed">
          {{ collapsed ? 'Показать' : 'Свернуть' }}
        </button>
        <button class="btn btn--ghost btn--sm" :disabled="!url" @click="openFull">Крупно</button>
        <button class="btn btn--ghost btn--sm" @click="download">Скачать</button>
      </span>
    </div>

    <template v-if="!collapsed">
      <p v-if="loading" class="state">Загрузка документа…</p>
      <p v-else-if="error" class="state state--error">{{ error }}</p>
      <iframe
        v-else-if="url" :src="url" class="pdf-frame" :style="{ height }" :title="title"
      ></iframe>
    </template>
  </div>
</template>

<style scoped>
.pdf-card { padding-bottom: 10px; }
.pdf-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.pdf-actions { display: flex; gap: 6px; }
.btn--sm { padding: 3px 8px; font-size: 12px; font-weight: 400; }
.pdf-frame {
  width: 100%; min-height: 320px; border: 1px solid var(--gray-border, #e0e0e0);
  border-radius: 6px; background: #fff;
}
</style>
