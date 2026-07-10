<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView, RouterLink } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

onMounted(() => {
  auth.init()
})
</script>

<template>
  <div class="app">
    <header class="app__header">
      <div class="app__brand">MiniSED</div>
      <nav class="app__nav">
        <RouterLink to="/tasks">Мои задачи</RouterLink>
      </nav>
      <div class="app__user">
        <template v-if="auth.b24UserId">Пользователь #{{ auth.b24UserId }}</template>
        <span v-else-if="auth.ready" class="app__user--warn">не определён</span>
      </div>
    </header>

    <main class="app__main">
      <RouterView v-if="auth.ready" />
      <p v-else class="app__loading">Загрузка…</p>
    </main>
  </div>
</template>
