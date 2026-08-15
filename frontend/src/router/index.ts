import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/svetofor' },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: 'Вход', public: true, noShell: true },
    },
    {
      path: '/svetofor',
      name: 'svetofor',
      component: () => import('@/views/SvetoforView.vue'),
      meta: { title: 'Согласования', wide: true },
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: () => import('@/views/TasksView.vue'),
      meta: { title: 'Мои задачи' },
    },
    {
      path: '/flow',
      name: 'flow',
      component: () => import('@/views/ApprovalsView.vue'),
      meta: { title: 'Согласования' },
    },
    {
      path: '/flow/new',
      name: 'flow-new',
      component: () => import('@/views/ApprovalCreateView.vue'),
      meta: { title: 'Новое согласование' },
    },
    {
      path: '/flow/:id',
      name: 'flow-detail',
      component: () => import('@/views/ApprovalDetailView.vue'),
      props: true,
      meta: { title: 'Согласование' },
    },
    {
      path: '/requests',
      name: 'requests',
      component: () => import('@/views/RequestsView.vue'),
      meta: { title: 'Регламентные заявки' },
    },
    {
      path: '/requests/new',
      name: 'request-new',
      component: () => import('@/views/RequestCreateView.vue'),
      meta: { title: 'Новая заявка' },
    },
    {
      path: '/requests/:id',
      name: 'request-detail',
      component: () => import('@/views/RequestDetailView.vue'),
      props: true,
      meta: { title: 'Заявка' },
    },
    {
      path: '/contracts',
      name: 'contracts',
      component: () => import('@/views/ContractsView.vue'),
      meta: { title: 'Договоры' },
    },
    {
      path: '/contracts/new',
      name: 'contract-new',
      component: () => import('@/views/ContractCreateView.vue'),
      meta: { title: 'Новый договор' },
    },
    {
      path: '/contracts/:id',
      name: 'contract-detail',
      component: () => import('@/views/ContractDetailView.vue'),
      props: true,
      meta: { title: 'Договор' },
    },
    {
      path: '/compliments',
      name: 'compliments',
      component: () => import('@/views/ComplimentsView.vue'),
      meta: { title: 'Комплименты' },
    },
    {
      path: '/compliments/new',
      name: 'compliment-new',
      component: () => import('@/views/ComplimentCreateView.vue'),
      meta: { title: 'Новая заявка на комплимент' },
    },
    {
      path: '/compliments/:id',
      name: 'compliment-detail',
      component: () => import('@/views/ComplimentDetailView.vue'),
      props: true,
      meta: { title: 'Заявка на комплимент' },
    },
    {
      path: '/execution',
      name: 'execution',
      component: () => import('@/views/ExecutionQueueView.vue'),
      meta: { title: 'Заявки для исполнения' },
    },
    {
      path: '/legal',
      name: 'legal',
      component: () => import('@/views/LegalQueueView.vue'),
      meta: { title: 'Работа юристов', lawyerOnly: true },
    },
    {
      path: '/deals',
      name: 'deals',
      component: () => import('@/views/DealSearchView.vue'),
      meta: { title: 'Поиск сделок' },
    },
    {
      path: '/agreements/:id',
      name: 'agreement',
      component: () => import('@/views/AgreementDetailView.vue'),
      props: true,
      meta: { title: 'Согласование' },
    },
    // запуск из Битрикс24 приходит на /app — уводим в приложение
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router
