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
      path: '/agreements/:id',
      name: 'agreement',
      component: () => import('@/views/AgreementDetailView.vue'),
      props: true,
      meta: { title: 'Согласование' },
    },
  ],
})

export default router
