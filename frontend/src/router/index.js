import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: '首页' }
  },
  {
    path: '/review/:taskId?',
    name: 'Review',
    component: () => import('@/views/ReviewView.vue'),
    meta: { title: '文档审阅' }
  },
  {
    path: '/result/:taskId',
    name: 'Result',
    component: () => import('@/views/ResultView.vue'),
    meta: { title: '审阅结果' }
  },
  {
    path: '/standards',
    name: 'Standards',
    component: () => import('@/views/StandardsView.vue'),
    meta: { title: '标准管理' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = `${to.meta.title || '法务文本审阅系统'} - 法务文本审阅系统`
  next()
})

export default router
