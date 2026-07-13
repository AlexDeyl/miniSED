<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterView, RouterLink, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

const pageTitle = computed(() => (route.meta.title as string) || 'MiniSED')

onMounted(() => {
  auth.init()
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-logo">
        MiniSED
        <small>Электронный документооборот</small>
      </div>
      <nav class="sidebar-nav">
        <RouterLink to="/tasks"><span>Мои задачи</span></RouterLink>
        <RouterLink to="/flow"><span>Согласования</span></RouterLink>
        <RouterLink to="/requests"><span>Регламентные заявки</span></RouterLink>
        <RouterLink to="/legal"><span>Заявки для юристов</span></RouterLink>
        <RouterLink to="/deals"><span>Поиск сделок</span></RouterLink>
      </nav>
      <div class="sidebar-footer">
        <template v-if="auth.b24UserId">Пользователь #{{ auth.b24UserId }}</template>
        <template v-else-if="auth.ready">не авторизован</template>
      </div>
    </aside>

    <main class="main">
      <header class="main-header">
        <div>
          <div class="main-header-title">{{ pageTitle }}</div>
          <div class="main-header-subtitle">Согласования, заявки, документы</div>
        </div>
        <div class="main-header-right">
          <span>ID Б24:</span> <strong>{{ auth.b24UserId ?? '—' }}</strong>
        </div>
      </header>

      <div class="main-body">
        <div class="main-body-inner">
          <RouterView v-if="auth.ready" />
          <p v-else class="state">Загрузка…</p>
        </div>
      </div>
    </main>
  </div>
</template>
