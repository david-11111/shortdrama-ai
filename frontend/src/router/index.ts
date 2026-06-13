import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/login/index.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/pages/register/index.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/pages/dashboard/index.vue'),
    meta: { requiresAuth: true, title: 'Dashboard' },
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('@/pages/tasks/index.vue'),
    meta: { requiresAuth: true, title: 'Tasks' },
  },
  {
    path: '/tasks/submit-video',
    name: 'submit-video',
    component: () => import('@/pages/tasks/submit-video.vue'),
    meta: { requiresAuth: true, title: 'Submit Video' },
  },
  {
    path: '/tasks/submit-image',
    name: 'submit-image',
    component: () => import('@/pages/tasks/submit-image.vue'),
    meta: { requiresAuth: true, title: 'Submit Image' },
  },
  {
    path: '/tasks/submit-tts',
    name: 'submit-tts',
    component: () => import('@/pages/tasks/submit-tts.vue'),
    meta: { requiresAuth: true, title: 'Submit TTS' },
  },
  {
    path: '/tasks/:id',
    name: 'task-detail',
    component: () => import('@/pages/tasks/[id].vue'),
    meta: { requiresAuth: true, title: 'Task Detail' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/pages/settings/index.vue'),
    meta: { requiresAuth: true, title: 'Settings' },
  },
  {
    path: '/recharge',
    name: 'recharge',
    component: () => import('@/pages/recharge/index.vue'),
    meta: { requiresAuth: true, title: 'Recharge' },
  },
  {
    path: '/reports',
    name: 'reports',
    component: () => import('@/pages/reports/index.vue'),
    meta: { requiresAuth: true, title: 'Reports' },
  },
  {
    path: '/payment/success',
    name: 'payment-success',
    component: () => import('@/pages/payment/success.vue'),
    meta: { requiresAuth: true, title: 'Payment Success' },
  },
  {
    path: '/workbench/:projectId',
    name: 'workbench',
    component: () => import('@/pages/workbench/index.vue'),
    meta: { requiresAuth: true, title: 'Workbench' },
  },
  {
    path: '/director',
    name: 'director-hub',
    component: () => import('@/pages/director/index.vue'),
    meta: { requiresAuth: true, title: 'Director' },
  },
  {
    path: '/director/workbench',
    name: 'director-workbench',
    component: () => import('@/pages/director/workbench.vue'),
    meta: { requiresAuth: true, title: 'Director Workbench' },
  },
  {
    path: '/director/workbench/:projectId',
    name: 'director-workbench-project',
    component: () => import('@/pages/director/workbench.vue'),
    meta: { requiresAuth: true, title: 'Director Workbench' },
  },
  {
    path: '/director/produce',
    name: 'director-produce',
    component: () => import('@/pages/director/produce/index.vue'),
    meta: { requiresAuth: true, title: 'Director Produce' },
  },
  {
    path: '/director/produce/:projectId',
    name: 'director-produce-project',
    component: () => import('@/pages/director/produce/index.vue'),
    meta: { requiresAuth: true, title: 'Director Produce' },
  },
  {
    path: '/director/agent-run',
    name: 'agent-run-launch',
    component: () => import('@/pages/director/agent-run/index.vue'),
    meta: { requiresAuth: true, title: 'Agent Studio' },
  },
  {
    path: '/director/agent-run/:runId',
    name: 'agent-run-observe',
    component: () => import('@/pages/director/agent-run/[runId].vue'),
    meta: { requiresAuth: true, title: 'Agent Run' },
  },
  {
    path: '/director/final-cut',
    name: 'director-final-cut',
    component: () => import('@/pages/director/final-cut.vue'),
    meta: { requiresAuth: true, title: 'Director Final Cut' },
  },
  {
    path: '/director/final-cut/:projectId',
    name: 'director-final-cut-project',
    component: () => import('@/pages/director/final-cut.vue'),
    meta: { requiresAuth: true, title: 'Director Final Cut' },
  },
  {
    path: '/director/flow',
    name: 'director-flow',
    component: () => import('@/pages/director/flow.vue'),
    meta: { requiresAuth: true, title: 'Director Flow' },
  },
  {
    path: '/director/flow/:projectId',
    name: 'director-flow-project',
    component: () => import('@/pages/director/flow.vue'),
    meta: { requiresAuth: true, title: 'Director Flow' },
  },
  {
    path: '/director/insight',
    name: 'director-insight',
    component: () => import('@/pages/director/insight.vue'),
    meta: { requiresAuth: true, title: 'Director Insight' },
  },
  {
    path: '/director/insight/:projectId',
    name: 'director-insight-project',
    component: () => import('@/pages/director/insight.vue'),
    meta: { requiresAuth: true, title: 'Director Insight' },
  },
  {
    path: '/director/retrieve',
    name: 'director-retrieve',
    component: () => import('@/pages/director/retrieve.vue'),
    meta: { requiresAuth: true, title: 'Director Retrieve' },
  },
  {
    path: '/director/evaluation',
    name: 'director-evaluation',
    component: () => import('@/pages/director/evaluation.vue'),
    meta: { requiresAuth: true, title: 'Director Evaluation' },
  },
  {
    path: '/director/:projectId',
    name: 'director-project',
    component: () => import('@/pages/director/index.vue'),
    meta: { requiresAuth: true, title: 'Director' },
  },
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      { path: '', name: 'admin-overview', component: () => import('@/pages/admin/index.vue') },
      { path: 'users', name: 'admin-users', component: () => import('@/pages/admin/users.vue') },
      { path: 'tasks', name: 'admin-tasks', component: () => import('@/pages/admin/tasks.vue') },
      { path: 'credits', name: 'admin-credits', component: () => import('@/pages/admin/credits.vue') },
      { path: 'dead-letter', name: 'admin-dead-letter', component: () => import('@/pages/admin/dead-letter.vue') },
      { path: 'keys', name: 'admin-keys', component: () => import('@/pages/admin/keys.vue') },
      { path: 'system', name: 'admin-system', component: () => import('@/pages/admin/system.vue') },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})

router.afterEach((to) => {
  const title = (to.meta?.title as string | undefined) ?? 'SaaS Platform'
  document.title = title === 'SaaS Platform' ? title : `${title} · SaaS Platform`
})

// 路由守卫
router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (authStore.isAuthenticated && !authStore.user) {
    try {
      await authStore.fetchUser()
    } catch {
      await authStore.logout({ remote: false })
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }

  if (to.meta.requiresAdmin && !authStore.user?.is_admin) {
    return { name: 'dashboard' }
  }

  if (!to.meta.requiresAuth && authStore.isAuthenticated && (to.name === 'login' || to.name === 'register')) {
    return { name: 'dashboard' }
  }
})

export default router
