import { createRouter, createWebHistory } from 'vue-router'

// 动态导入包装器 - 处理模块加载失败并自动重试
function lazyLoadView(importFn, viewName) {
  return () => {
    return importFn().catch(error => {
      console.error(`[Router] 加载 ${viewName} 失败:`, error)

      // 检查是否是动态导入失败（通常是部署后哈希变化导致）
      if (error.message.includes('Failed to fetch dynamically imported module') ||
          error.message.includes('Loading chunk') ||
          error.message.includes('Loading CSS chunk')) {

        console.log(`[Router] 检测到模块加载失败，可能是部署更新导致，将刷新页面...`)

        // 显示用户提示
        const shouldReload = window.confirm(
          '应用已更新，需要刷新页面以加载最新版本。\n\n点击"确定"刷新页面。'
        )

        if (shouldReload) {
          // 清除缓存并刷新
          window.location.reload()
        }

        // 返回一个永远不会 resolve 的 Promise，防止路由继续
        return new Promise(() => {})
      }

      // 其他错误则抛出
      throw error
    })
  }
}

const routes = [
  {
    path: '/',
    name: 'Home',
    component: lazyLoadView(() => import('@/views/HomeView.vue'), 'HomeView'),
    meta: { title: '首页' }
  },
  {
    path: '/documents',
    name: 'Documents',
    component: lazyLoadView(() => import('@/views/DocumentsView.vue'), 'DocumentsView'),
    meta: { title: '文档管理' }
  },
  {
    path: '/review/:taskId?',
    name: 'Review',
    component: lazyLoadView(() => import('@/views/ReviewView.vue'), 'ReviewView'),
    meta: { title: '文档审阅' }
  },
  {
    path: '/result/:taskId',
    name: 'Result',
    component: lazyLoadView(() => import('@/views/ResultView.vue'), 'ResultView'),
    meta: { title: '审阅结果' }
  },
  {
    path: '/standards',
    name: 'Standards',
    component: lazyLoadView(() => import('@/views/StandardsView.vue'), 'StandardsView'),
    meta: { title: '标准管理' }
  },
  {
    path: '/skills',
    name: 'Skills',
    component: lazyLoadView(() => import('@/views/SkillsView.vue'), 'SkillsView'),
    meta: { title: 'Skills 管理' }
  },
  {
    path: '/business',
    name: 'Business',
    component: lazyLoadView(() => import('@/views/BusinessView.vue'), 'BusinessView'),
    meta: { title: '业务管理' }
  },
  {
    path: '/interactive/:taskId',
    name: 'InteractiveReview',
    component: lazyLoadView(() => import('@/views/InteractiveReviewView.vue'), 'InteractiveReviewView'),
    meta: { title: '深度交互审阅' }
  },
  {
    path: '/gen3/:taskId?',
    name: 'Gen3Review',
    component: lazyLoadView(() => import('@/views/Gen3ReviewView.vue'), 'Gen3ReviewView'),
    meta: { title: 'Gen 3.0 智能审阅' }
  },
  {
    path: '/review-result/:taskId',
    name: 'UnifiedResult',
    component: lazyLoadView(() => import('@/views/UnifiedResultView.vue'), 'UnifiedResultView'),
    meta: { title: '审阅结果' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局路由错误处理
router.onError((error, to, from) => {
  console.error('[Router] 路由错误:', error)

  // 检查是否是动态导入失败
  if (error.message.includes('Failed to fetch dynamically imported module') ||
      error.message.includes('Loading chunk')) {

    console.log('[Router] 模块加载失败，尝试刷新页面...')

    // 保存当前要去的路由，刷新后可以恢复
    sessionStorage.setItem('pendingRoute', to.fullPath)
    window.location.reload()
  }
})

router.beforeEach((to, from, next) => {
  document.title = `${to.meta.title || '十行合同'} - 十行合同`
  next()
})

// 路由加载完成后，检查是否有待恢复的路由
router.afterEach((to) => {
  const pendingRoute = sessionStorage.getItem('pendingRoute')
  if (pendingRoute && to.path === '/' && pendingRoute !== '/') {
    sessionStorage.removeItem('pendingRoute')
    // 延迟执行，确保应用已初始化
    setTimeout(() => {
      router.push(pendingRoute)
    }, 100)
  }
})

export default router
