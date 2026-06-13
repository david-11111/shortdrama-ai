import client from './client'
import type { ApiKey } from '@/types/api'

interface ApiKeyListResponse {
  keys: ApiKey[]
}

export const keysApi = {
  list() {
    return client.get<ApiKeyListResponse>('/keys')
  },

  create(name: string) {
    return client.post<ApiKey>('/keys', { name })
  },

  revoke(keyId: string) {
    return client.delete(`/keys/${keyId}`)
  },
}
