<template>
  <div class="admin-shell">
    <button class="mobile-toggle" type="button" @click="sidebarOpen = !sidebarOpen">
      {{ sidebarOpen ? '关闭菜单' : '打开菜单' }}
    </button>

    <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false"></div>

    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-brand">
        <p class="brand-kicker">Admin Console</p>
        <strong>SaaS 后台</strong>
      </div>

      <nav class="sidebar-nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: isActive(item.to) }"
          @click="sidebarOpen = false"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>

    <main class="content">
      <div class="content-inner">
        <RouterView />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()
const sidebarOpen = ref(false)

const navItems = [
  { label: '总览', to: '/admin' },
  { label: '用户管理', to: '/admin/users' },
  { label: '任务监控', to: '/admin/tasks' },
  { label: '积分与收入', to: '/admin/credits' },
  { label: '死信队列', to: '/admin/dead-letter' },
  { label: 'Key Pool', to: '/admin/keys' },
  { label: '系统健康', to: '/admin/system' },
  { label: '返回前台', to: '/' },
]

function isActive(path: string) {
  if (path === '/admin') return route.path === '/admin'
  return route.path.startsWith(path)
}
</script>

<style scoped>
.admin-shell {
  min-height: 100vh;
  display: flex;
  background: #f5f7fb;
}

.sidebar {
  width: 240px;
  flex: 0 0 240px;
  background: #1a1a2e;
  color: #f5f7fb;
  padding: 24px 16px;
  position: sticky;
  top: 0;
  height: 100vh;
}

.sidebar-brand {
  margin-bottom: 24px;
  padding: 0 8px;
}

.brand-kicker {
  margin: 0 0 8px;
  color: #8fb8ff;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.sidebar-nav {
  display: grid;
  gap: 8px;
}

.nav-link {
  display: block;
  padding: 12px 14px;
  border-radius: 12px;
  color: rgba(245, 247, 251, 0.82);
  text-decoration: none;
  transition: background-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
}

.nav-link:hover,
.nav-link.active {
  background: rgba(143, 184, 255, 0.14);
  color: #fff;
  transform: translateX(2px);
}

.content {
  flex: 1;
  min-width: 0;
}

.content-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
}

.mobile-toggle {
  display: none;
}

.sidebar-mask {
  display: none;
}

@media (max-width: 900px) {
  .mobile-toggle {
    display: inline-flex;
    position: fixed;
    top: 16px;
    left: 16px;
    z-index: 30;
    padding: 10px 14px;
    border: none;
    border-radius: 999px;
    background: #1a1a2e;
    color: #fff;
  }

  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    z-index: 40;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }

  .sidebar.open {
    transform: translateX(0);
  }

  .sidebar-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgba(15, 23, 42, 0.45);
  }

  .content-inner {
    padding: 72px 16px 24px;
  }
}
</style>
