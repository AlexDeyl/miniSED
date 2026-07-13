import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/tasks' },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: 'Вход', public: true, noShell: true },
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
      path: '/legal',
      name: 'legal',
      component: () => import('@/views/LegalQueueView.vue'),
      meta: { title: 'Заявки для юристов' },
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
  ],
})

export default router
