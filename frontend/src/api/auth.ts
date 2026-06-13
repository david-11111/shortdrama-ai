import client from './client'
import type { TokenResponse, User } from '@/types/api'

export const authApi = {
  register(email: string, password: string, displayName?: string) {
    return client.post<TokenResponse>(
      '/auth/register',
      { email, password, display_name: displayName },
      { skipAuth: true }
    )
  },

  login(email: string, password: string) {
    return client.post<TokenResponse>(
      '/auth/login',
      { email, password },
      { skipAuth: true }
    )
  },

  refresh(refreshToken: string) {
    return client.post<TokenResponse>(
      '/auth/refresh',
      { refresh_token: refreshToken },
      { skipAuth: true, silent: true }
    )
  },

  logout() {
    return client.post<{ message: string }>('/auth/logout', null, { silent: true })
  },

  me() {
    return client.get<User>('/auth/me')
  },
}
