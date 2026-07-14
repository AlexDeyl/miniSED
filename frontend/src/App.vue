<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSvetoforStore, SVETOFOR_TABS } from '@/stores/svetofor'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const svet = useSvetoforStore()

const pageTitle = computed(() => (route.meta.title as string) || 'MiniSED')
const bare = computed(() => route.meta.noShell === true)
// Вкладки согласований показываем в сайдбаре только на странице «Согласования».
const onSvetofor = computed(() => route.name === 'svetofor')

async function doLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <!-- Страница входа — без оболочки -->
  <RouterView v-if="bare" />

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-logo">
        МиниСЭД 2.0
        <small>Электронный документооборот</small>
      </div>
      <nav class="sidebar-nav">
        <RouterLink to="/svetofor"><span>Согласования</span></RouterLink>
        <RouterLink to="/requests"><span>Регламентные заявки</span></RouterLink>
        <RouterLink to="/legal"><span>Заявки для юристов</span></RouterLink>
        <RouterLink to="/deals"><span>Поиск сделок</span></RouterLink>
      </nav>

      <!-- Фильтры согласований + текущий пользователь (как в старом app.html) -->
      <div v-if="onSvetofor" class="sidebar-block">
        <div class="sidebar-block-label">Разделы</div>
        <div class="sidebar-tabs">
          <button
            v-for="t in SVETOFOR_TABS" :key="t.code"
            class="sidebar-tab" :class="{ active: svet.mode === t.code }"
            @click="svet.mode = t.code"
          >{{ t.label }}</button>
        </div>
        <div class="sidebar-b24">ID Б24: <strong>{{ auth.b24UserId ?? '—' }}</strong></div>
      </div>

      <div class="sidebar-footer">
        <div v-if="auth.displayName" style="margin-bottom:6px">{{ auth.displayName }}</div>
        <button class="sidebar-logout" @click="doLogout">Выйти</button>
      </div>
    </aside>

    <main class="main">
      <header class="main-header">
        <div>
          <div class="main-header-title">{{ pageTitle }}</div>
          <div class="main-header-subtitle">Согласования, заявки, документы</div>
        </div>
      </header>

      <div class="main-body" :class="{ 'main-body--wide': route.meta.wide }">
        <div v-if="route.meta.wide" class="main-body-wide">
          <RouterView />
        </div>
        <div v-else class="main-body-inner">
          <RouterView />
        </div>
      </div>
    </main>
  </div>
</template>
