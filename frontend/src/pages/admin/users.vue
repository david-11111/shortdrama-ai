<template>
  <div class="admin-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Users</p>
        <h1>用户管理</h1>
      </div>
    </header>

    <section class="toolbar">
      <input v-model.trim="search" class="input" type="search" placeholder="搜索邮箱或昵称" @keyup.enter="applyFilters" />
      <select v-model="tier" class="input" @change="applyFilters">
        <option value="">全部套餐</option>
        <option value="free">free</option>
        <option value="pro">pro</option>
        <option value="enterprise">enterprise</option>
      </select>
      <select v-model="status" class="input" @change="applyFilters">
        <option value="">全部状态</option>
        <option value="active">active</option>
        <option value="disabled">disabled</option>
      </select>
      <button class="btn-primary" type="button" @click="applyFilters">查询</button>
    </section>

    <div v-if="errorMessage" class="feedback error">{{ errorMessage }}</div>

    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>邮箱</th>
            <th>套餐</th>
            <th>状态</th>
            <th>余额</th>
            <th>注册时间</th>
            <th>管理员</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="7" class="state-cell">加载中...</td>
          </tr>
          <tr v-else-if="users.length === 0">
            <td colspan="7" class="state-cell">暂无数据</td>
          </tr>
          <tr v-for="user in users" :key="user.id">
            <td>
              <div class="cell-main">{{ user.email }}</div>
              <div class="cell-sub">{{ user.display_name || '-' }}</div>
            </td>
            <td>
              <select class="mini-input" :value="user.tier" :disabled="savingUserId === user.id" @change="updateTier(user.id, $event)">
                <option value="free">free</option>
                <option value="pro">pro</option>
                <option value="enterprise">enterprise</option>
              </select>
            </td>
            <td>{{ user.status }}</td>
            <td>{{ user.balance ?? 0 }}</td>
            <td>{{ formatTime(user.created_at) }}</td>
            <td>
              <label class="switch">
                <input type="checkbox" :checked="user.is_admin" :disabled="savingUserId === user.id" @change="toggleAdmin(user.id, $event)" />
                <span>{{ user.is_admin ? '是' : '否' }}</span>
              </label>
            </td>
            <td>
              <button class="btn-secondary" type="button" :disabled="savingUserId === user.id" @click="toggleStatus(user)">
                {{ user.status === 'active' ? '禁用' : '启用' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pagination">
      <button class="btn-secondary" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button class="btn-secondary" type="button" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { adminApi, type AdminUserRow } from '@/api/admin'

const users = ref<AdminUserRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
const savingUserId = ref<number | null>(null)
const page = ref(1)
const total = ref(0)
const pageSize = 20
const search = ref('')
const tier = ref('')
const status = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

onMounted(() => {
  void loadUsers()
})

async function loadUsers() {
  loading.value = true
  errorMessage.value = ''

  try {
    const { data } = await adminApi.users({
      page: page.value,
      page_size: pageSize,
      tier: tier.value || undefined,
      status: status.value || undefined,
      search: search.value || undefined,
    })
    users.value = data.users
    total.value = data.total
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '加载用户失败'
  } finally {
    loading.value = false
  }
}

async function patchUser(userId: number, payload: { tier?: string; status?: string; is_admin?: boolean }) {
  savingUserId.value = userId
  errorMessage.value = ''

  try {
    await adminApi.updateUser(userId, payload)
    await loadUsers()
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.detail ?? error?.message ?? '更新用户失败'
  } finally {
    savingUserId.value = null
  }
}

function updateTier(userId: number, event: Event) {
  const value = (event.target as HTMLSelectElement).value
  void patchUser(userId, { tier: value })
}

function toggleAdmin(userId: number, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  void patchUser(userId, { is_admin: checked })
}

function toggleStatus(user: AdminUserRow) {
  const nextStatus = user.status === 'active' ? 'disabled' : 'active'
  void patchUser(user.id, { status: nextStatus })
}

function applyFilters() {
  page.value = 1
  void loadUsers()
}

function goPage(nextPage: number) {
  page.value = nextPage
  void loadUsers()
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}
</script>

<style scoped>
.page-header {
  margin-bottom: 20px;
}

.page-kicker {
  margin: 0 0 8px;
  color: #3156d3;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

h1 {
  margin: 0;
}

.toolbar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.input,
.mini-input {
  padding: 10px 12px;
  border: 1px solid #dbe2f0;
  border-radius: 12px;
  background: #fff;
}

.input {
  min-width: 180px;
}

.btn-primary,
.btn-secondary {
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid transparent;
  cursor: pointer;
}

.btn-primary {
  background: #3156d3;
  color: #fff;
}

.btn-secondary {
  background: #fff;
  border-color: #dbe2f0;
  color: #475569;
}

.feedback {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
}

.feedback.error {
  background: #fef3f2;
  color: #b42318;
}

.table-wrap {
  overflow-x: auto;
  border: 1px solid #dbe2f0;
  border-radius: 18px;
  background: #fff;
}

.table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 14px 16px;
  border-bottom: 1px solid #e5e7eb;
  text-align: left;
  vertical-align: middle;
}

.table tbody tr:last-child td {
  border-bottom: none;
}

.cell-main {
  font-weight: 600;
}

.cell-sub {
  margin-top: 4px;
  color: #64748b;
  font-size: 0.875rem;
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.state-cell {
  color: #64748b;
  text-align: center;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
</style>
