import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { User } from '@/types/api'

const ACCESS_KEY = 'access_token'
const REFRESH_KEY = 'refresh_token'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(localStorage.getItem(ACCESS_KEY))
  const _refreshToken = ref<string | null>(localStorage.getItem(REFRESH_KEY))
  const user = ref<User | null>(null)

  const isAuthenticated = computed(() => !!accessToken.value)

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    _refreshToken.value = refresh
    localStorage.setItem(ACCESS_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  }

  function clearAuth() {
    accessToken.value = null
    _refreshToken.value = null
    user.value = null
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  }

  async function logout(options: { remote?: boolean } = {}) {
    const { remote = true } = options
    try {
      if (remote && accessToken.value) {
        await authApi.logout()
      }
    } catch {
      // Best effort logout: always clear local auth state.
    } finally {
      clearAuth()
    }
  }

  async function login(email: string, password: string) {
    const { data } = await authApi.login(email, password)
    setTokens(data.access_token, data.refresh_token)
    await fetchUser()
  }

  async function register(email: string, password: string, displayName?: string) {
    const { data } = await authApi.register(email, password, displayName)
    setTokens(data.access_token, data.refresh_token)
    await fetchUser()
  }

  async function refreshToken(): Promise<string> {
    if (!_refreshToken.value) throw new Error('No refresh token')
    const { data } = await authApi.refresh(_refreshToken.value)
    setTokens(data.access_token, data.refresh_token)
    return data.access_token
  }

  async function fetchUser() {
    const { data } = await authApi.me()
    user.value = {
      ...data,
      is_admin: Boolean((data as User & { is_admin?: boolean }).is_admin),
    }
  }

  // ---------- 跨标签同步 ----------
  // 某个标签页登出或刷新 Token 时，其他标签页通过 storage 事件同步内存态
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event) => {
      if (event.key === ACCESS_KEY) {
        accessToken.value = event.newValue
        if (!event.newValue) user.value = null
      } else if (event.key === REFRESH_KEY) {
        _refreshToken.value = event.newValue
      }
    })
  }

  return {
    accessToken,
    user,
    isAuthenticated,
    login,
    register,
    logout,
    clearAuth,
    refreshToken,
    fetchUser,
    setTokens,
  }
})
