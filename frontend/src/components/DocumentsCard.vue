<script setup lang="ts">
// Документы карточки: история версий, загрузка новой версии, онлайн-правка.
// Общий блок для договоров, регламентных заявок и будущих модулей.
import type { DocumentVersion } from '@/types/document'

export interface CardDocument {
  id: number
  title: string
  document_type?: string
  current_version_number: number | null
  download_url: string | null
  versions: DocumentVersion[]
  can_edit_online: boolean
}

withDefaults(defineProps<{
  docs: CardDocument[]
  busy: boolean
  canUpload?: boolean
  canAddVersion?: boolean
  uploadLabel?: string
  emptyText?: string
  hint?: string
}>(), {
  canUpload: true,
  canAddVersion: true,
  uploadLabel: 'Прикрепить документ',
  emptyText: 'Файлов пока нет.',
  hint: '',
})

defineEmits<{
  download: [url: string | null, name: string]
  upload: []
  addVersion: [docId: number]
  edit: [docId: number]
}>()
</script>

<template>
  <div class="detail-card">
    <div class="detail-card-header">Документы</div>

    <div v-for="d in docs" :key="d.id" class="doc-item">
      <div class="doc-name">
        {{ d.title }}
        <span class="detail-meta">· актуальная v{{ d.current_version_number }}</span>
      </div>
      <div class="doc-actions">
        <a
          v-for="v in d.versions" :key="v.id" href="#" class="doc-link" :title="v.change_comment"
          @click.prevent="$emit('download', v.download_url, `${d.title} v${v.version_number}`)"
        >v{{ v.version_number }}{{ v.is_current ? ' ✓' : '' }}</a>
        <button
          v-if="canAddVersion" type="button" class="doc-link doc-linkbtn"
          :disabled="busy" @click="$emit('addVersion', d.id)"
        >＋ новая версия</button>
        <button
          v-if="d.can_edit_online" type="button" class="doc-link doc-linkbtn"
          @click="$emit('edit', d.id)"
        >✏️ Редактировать онлайн</button>
      </div>
      <template v-for="v in d.versions" :key="'c' + v.id">
        <div v-if="v.change_comment" class="detail-meta">v{{ v.version_number }}: {{ v.change_comment }}</div>
      </template>
    </div>

    <p v-if="!docs.length" class="muted" style="margin:0 0 8px">{{ emptyText }}</p>

    <div class="row-actions">
      <button v-if="canUpload" class="btn btn--ghost" :disabled="busy" @click="$emit('upload')">
        {{ uploadLabel }}
      </button>
      <slot name="actions"></slot>
    </div>

    <div v-if="hint" class="detail-meta" style="margin-top:6px">{{ hint }}</div>
  </div>
</template>

<style scoped>
.doc-item { background: #fff; border-radius: 8px; border: 1px solid #e0e0e0; padding: 8px 10px; margin-bottom: 8px; }
.doc-name { font-size: 14px; font-weight: 500; margin-bottom: 4px; overflow-wrap: anywhere; word-break: break-word; }
.doc-actions { font-size: 12px; display: flex; gap: 14px; flex-wrap: wrap; }
.doc-link { color: var(--green-main); text-decoration: none; cursor: pointer; }
.doc-link:hover { text-decoration: underline; }
.doc-linkbtn { border: none; background: transparent; padding: 0; cursor: pointer; color: var(--green-main); font: inherit; font-size: 12px; }
.doc-linkbtn:hover { text-decoration: underline; }
.doc-linkbtn:disabled { opacity: 0.5; cursor: default; text-decoration: none; }
</style>
