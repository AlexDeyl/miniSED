<script setup lang="ts">
/**
 * Онлайн-редактор документа (ТЗ п.7.2-7.3).
 *
 * Компонент намеренно тонкий: весь провайдер-специфичный конфиг приходит
 * с бэкенда (`/documents/:id/editor-config/`), включая serverUrl, с которого
 * грузится api.js сервера документов (OnlyOffice/Р7). Здесь — только загрузка
 * скрипта, монтирование DocsAPI.DocEditor и обработка закрытия.
 *
 * Сохранение НЕ здесь: сервер документов по закрытию/forcesave сам шлёт файл в
 * наш callback, тот создаёт новую версию. Поэтому по закрытию мы лишь сообщаем
 * наверх, что список версий стоит перечитать.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError } from '@/services/api'
import { documents } from '@/services/documents'

const props = defineProps<{ docId: number | string }>()
const emit = defineEmits<{ (e: 'close', changed: boolean): void }>()

const error = ref('')
const loading = ref(true)
// Меняется ли документ в этом сеансе — чтобы родитель перечитал версии.
let touched = false
// Экземпляр DocsAPI.DocEditor (для корректного destroyEditor при выходе).
let editor: { destroyEditor?: () => void } | null = null

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DocsApi = any
declare global {
  interface Window {
    DocsAPI?: DocsApi
  }
}

// Загрузка api.js сервера документов (один раз на serverUrl).
function loadDocsApi(serverUrl: string): Promise<void> {
  const src = `${serverUrl}/web-apps/apps/api/documents/api.js`
  if (window.DocsAPI) return Promise.resolve()
  const existing = document.querySelector(`script[data-docs-api]`)
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error('api.js')))
    })
  }
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = src
    s.async = true
    s.setAttribute('data-docs-api', '1')
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('Не удалось загрузить сервер документов.'))
    document.head.appendChild(s)
  })
}

async function mountEditor() {
  loading.value = true
  error.value = ''
  try {
    const data = await documents.editorConfig(props.docId)
    await loadDocsApi(data.serverUrl)
    if (!window.DocsAPI) throw new Error('DocsAPI недоступен.')

    // Подмешиваем колбэки состояния (сам конфиг подписан JWT на бэке —
    // события к подписи не относятся, их можно добавлять на клиенте).
    const config = {
      ...data.config,
      width: '100%',
      height: '100%',
      events: {
        onDocumentStateChange: (evt: { data?: boolean }) => {
          if (evt?.data) touched = true
        },
        onError: (evt: { data?: unknown }) => {
          error.value = `Ошибка редактора: ${JSON.stringify(evt?.data ?? '')}`
        },
      },
    }
    editor = new window.DocsAPI.DocEditor('docs-editor-placeholder', config)
    loading.value = false
  } catch (e) {
    loading.value = false
    error.value =
      e instanceof ApiError && e.status === 409
        ? 'Онлайн-редактирование недоступно для этого документа.'
        : e instanceof Error
          ? e.message
          : 'Не удалось открыть редактор.'
  }
}

function close() {
  try {
    editor?.destroyEditor?.()
  } catch {
    /* редактор мог не смонтироваться */
  }
  editor = null
  emit('close', touched)
}

onMounted(mountEditor)
onBeforeUnmount(() => {
  try {
    editor?.destroyEditor?.()
  } catch {
    /* no-op */
  }
})
</script>

<template>
  <div class="editor-overlay">
    <div class="editor-topbar">
      <span class="editor-title">Редактирование документа</span>
      <button class="close-btn" @click="close">Закрыть</button>
    </div>

    <div v-if="error" class="editor-msg error">{{ error }}</div>
    <div v-else-if="loading" class="editor-msg">Открываем редактор…</div>

    <div class="editor-frame">
      <div id="docs-editor-placeholder"></div>
    </div>
  </div>
</template>

<style scoped>
/* Светлая тема в духе app.html (см. memory frontend-design-parity). */
.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  background: #fff;
}
.editor-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: #0b7f5f;
  color: #fff;
  flex: 0 0 auto;
}
.editor-title {
  font-size: 14px;
  font-weight: 600;
}
.close-btn {
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.4);
  color: #fff;
  border-radius: 6px;
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
}
.close-btn:hover {
  background: rgba(255, 255, 255, 0.28);
}
.editor-msg {
  padding: 12px 16px;
  font-size: 14px;
  color: #70757a;
}
.editor-msg.error {
  color: #f44336;
}
.editor-frame {
  flex: 1 1 auto;
  min-height: 0;
}
#docs-editor-placeholder {
  width: 100%;
  height: 100%;
}
</style>
