import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/tasks' },
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
