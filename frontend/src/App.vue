<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSvetoforStore, SVETOFOR_TABS } from '@/stores/svetofor'
import { useRequestsUiStore, REQUEST_TYPE_TABS } from '@/stores/requestsUi'
import { useLegalUiStore, LEGAL_TABS } from '@/stores/legalUi'
import { useContractsUiStore, CONTRACT_TABS } from '@/stores/contractsUi'
import { useComplimentsUiStore, COMPLIMENT_TABS, EXECUTION_TABS } from '@/stores/complimentsUi'
import { useOtherUiStore, OTHER_TABS } from '@/stores/otherUi'
import { useAdminModeStore } from '@/stores/adminMode'
import { useItUiStore, IT_TABS } from '@/stores/itUi'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const svet = useSvetoforStore()
const reqUi = useRequestsUiStore()
const legalUi = useLegalUiStore()
const contractsUi = useContractsUiStore()
const complimentsUi = useComplimentsUiStore()
const otherUi = useOtherUiStore()
const adminMode = useAdminModeStore()
const itUi = useItUiStore()

const pageTitle = computed(() => (route.meta.title as string) || 'MiniSED')
const bare = computed(() => route.meta.noShell === true)
// Под-вкладки показываем вложенно под своим пунктом меню.
const onSvetofor = computed(() => route.name === 'svetofor')
const onRequests = computed(() => route.name === 'requests')
const onLegal = computed(() => route.name === 'legal')
const onContracts = computed(() => route.name === 'contracts')
const onCompliments = computed(() => route.name === 'compliments')
const onExecution = computed(() => route.name === 'execution')
const onOther = computed(() => route.name === 'other')
const onIt = computed(() => route.name === 'it')
// Открыто из Битрикса (в iframe) — тогда «Выйти» не нужен (авто-вход портала).
const inBitrix = window.self !== window.top

async function doLogout() {
  await auth.logout()
  router.push('/login')
}

// Бейдж-счётчик для под-вкладки согласований (голубой кружок).
function tabBadge(code: string): number {
  if (code === 'todo') return svet.todoCount
  if (code === 'rejected') return svet.rejectedUnseen
  if (code === 'completed') return svet.completedUnseen
  return 0
}
</script>

<template>
  <!-- Страница входа — без оболочки -->
  <RouterView v-if="bare" />

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-logo">
        Мини-СЭД
        <small>Электронный документооборот</small>
      </div>
      <nav class="sidebar-nav">
        <RouterLink to="/svetofor">
          <span>Рабочее место визирования</span>
          <span v-if="svet.todoCount" class="nav-badge" title="Требует действия">{{ svet.todoCount }}</span>
        </RouterLink>
        <!-- под-вкладки визирования — вложенно под своим пунктом -->
        <div v-if="onSvetofor" class="sidebar-subtabs">
          <button
            v-for="t in SVETOFOR_TABS" :key="t.code"
            class="sidebar-subtab" :class="{ active: svet.mode === t.code }"
            @click="svet.mode = t.code"
          >{{ t.label }}<span v-if="tabBadge(t.code)" class="subtab-badge">{{ tabBadge(t.code) }}</span></button>
        </div>

        <RouterLink to="/requests"><span>Регламентные заявки</span></RouterLink>
        <!-- под-вкладки (фильтры типов) заявок — под своим пунктом -->
        <div v-if="onRequests" class="sidebar-subtabs">
          <button
            v-for="t in REQUEST_TYPE_TABS" :key="t.code || 'all'"
            class="sidebar-subtab" :class="{ active: reqUi.typeFilter === t.code }"
            @click="reqUi.typeFilter = t.code"
          >{{ t.label }}</button>
        </div>

        <RouterLink to="/contracts"><span>Договоры</span></RouterLink>
        <!-- под-вкладки договоров -->
        <div v-if="onContracts" class="sidebar-subtabs">
          <button
            v-for="t in CONTRACT_TABS" :key="t.code"
            class="sidebar-subtab" :class="{ active: contractsUi.mode === t.code }"
            @click="contractsUi.mode = t.code"
          >{{ t.label }}<span v-if="t.code === 'todo' && contractsUi.todoCount" class="subtab-badge">{{ contractsUi.todoCount }}</span></button>
        </div>

        <RouterLink to="/compliments">
          <span>Комплименты</span>
          <span v-if="complimentsUi.todoCount" class="nav-badge" title="Требует действия">{{ complimentsUi.todoCount }}</span>
        </RouterLink>
        <!-- под-вкладки комплиментов -->
        <div v-if="onCompliments" class="sidebar-subtabs">
          <button
            v-for="t in COMPLIMENT_TABS" :key="t.code"
            class="sidebar-subtab" :class="{ active: complimentsUi.mode === t.code }"
            @click="complimentsUi.mode = t.code"
          >{{ t.label }}<span v-if="t.code === 'todo' && complimentsUi.todoCount" class="subtab-badge">{{ complimentsUi.todoCount }}</span></button>
        </div>

        <!-- Раздел исполнителя: согласованные заявки не уходят письмом, а падают сюда -->
        <RouterLink v-if="auth.isComplimentExecutor" to="/execution">
          <span>Заявки для исполнения</span>
          <span v-if="complimentsUi.executionCount" class="nav-badge" title="Ждут исполнения">{{ complimentsUi.executionCount }}</span>
        </RouterLink>
        <div v-if="onExecution" class="sidebar-subtabs">
          <button
            v-for="t in EXECUTION_TABS" :key="t.code"
            class="sidebar-subtab" :class="{ active: complimentsUi.executionMode === t.code }"
            @click="complimentsUi.executionMode = t.code"
          >{{ t.label }}<span v-if="t.code === 'new' && complimentsUi.executionCount" class="subtab-badge">{{ complimentsUi.executionCount }}</span></button>
        </div>

        <RouterLink v-if="auth.isLawyer || auth.canViewAll" to="/legal"><span>Работа юристов</span></RouterLink>
        <!-- под-вкладки работы юристов -->
        <div v-if="onLegal" class="sidebar-subtabs">
          <button
            v-for="t in LEGAL_TABS" :key="t.code"
            class="sidebar-subtab" :class="{ active: legalUi.scope === t.code }"
            @click="legalUi.scope = t.code"
          >{{ t.label }}</button>
        </div>

        <!-- Исполнение заявок на ЭЦП: ИТ-специалист объекта -->
        <RouterLink v-if="auth.isItSpecialist || auth.canViewAll" to="/it">
          <span>Работа ИТ</span>
          <span v-if="itUi.newCount" class="nav-badge" title="Ждут исполнения">{{ itUi.newCount }}</span>
        </RouterLink>
        <div v-if="onIt" class="sidebar-subtabs">
          <button
            v-for="t in IT_TABS" :key="t.code"
            class="sidebar-subtab" :class="{ active: itUi.scope === t.code }"
            @click="itUi.scope = t.code"
          >{{ t.label }}<span v-if="t.code === 'new' && itUi.newCount" class="subtab-badge">{{ itUi.newCount }}</span></button>
        </div>

        <RouterLink to="/deals"><span>Поиск сделок</span></RouterLink>

        <!-- «Иное» — то, что не относится к визированию: создание свободного
             согласования и шаблоны маршрутов для него -->
        <RouterLink to="/other"><span>Иное</span></RouterLink>
        <div v-if="onOther" class="sidebar-subtabs">
          <button
            v-for="t in OTHER_TABS" :key="t.code"
            class="sidebar-subtab" :class="{ active: otherUi.mode === t.code }"
            @click="otherUi.mode = t.code"
          >{{ t.label }}</button>
        </div>
      </nav>

      <!-- Текущий пользователь -->
      <div class="sidebar-block">
        <div class="sidebar-block-label">Текущий пользователь</div>
        <div v-if="auth.profile?.fio" class="sidebar-user-name">{{ auth.profile.fio }}</div>
        <div class="sidebar-user-id">ID Б24: <strong>{{ auth.b24UserId ?? '—' }}</strong></div>
        <button v-if="!inBitrix" class="sidebar-logout" style="margin-top:8px" @click="doLogout">Выйти</button>
      </div>

      <div class="sidebar-footer">
        ©Mini-SED by Alexander Rodionov, v. 2.0, 2026
      </div>
    </aside>

    <main class="main">
      <header class="main-header">
        <div>
          <div class="main-header-title">{{ pageTitle }}</div>
          <div class="main-header-subtitle">Согласования, заявки, документы</div>
        </div>
        <div class="main-header-actions">
          <!-- Режим администратора виден только тем, у кого есть право
               сквозного просмотра; сервер проверяет право отдельно. -->
          <button
            v-if="adminMode.available"
            class="admin-toggle" :class="{ on: adminMode.active }"
            :title="adminMode.active
              ? 'Видны все карточки; решение можно принять за любого согласующего'
              : 'Показать все карточки и разрешить решения за других'"
            @click="adminMode.toggle()"
          >
            <span class="admin-dot"></span>
            Режим администратора
          </button>
          <!-- сюда вью телепортируют свою основную кнопку (Создать / …) -->
          <div id="header-actions" class="header-actions-slot"></div>
        </div>
      </header>

      <div v-if="adminMode.active" class="admin-banner">
        Режим администратора включён: видны чужие карточки, а решения по ним
        сохраняются с пометкой «согласовано администратором».
      </div>

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
