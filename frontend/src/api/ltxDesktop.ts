import client from './client'

export interface LtxDesktopStatus {
  running: boolean
  gpu?: { name: string; memory: string; utilization: number } | null
  uptime?: number | null
}

export interface LtxDesktopOpenPayload {
  media_url: string
  action: 'preview' | 'edit' | 'image-to-video' | 'extract-conditioning'
  prompt?: string
}

export interface LtxDesktopOpenResponse {
  success: boolean
  ltx_url?: string
  message: string
  task_id?: string
}

export const getLtxDesktopHealth = () =>
  client.get<LtxDesktopStatus>('/ltx-desktop/health')

export const launchLtxDesktop = () =>
  client.post<{ status: string; message: string }>('/ltx-desktop/launch')

export const shutdownLtxDesktop = () =>
  client.post<{ status: string; message: string }>('/ltx-desktop/shutdown')

export const openInLtxDesktop = (payload: LtxDesktopOpenPayload) =>
  client.post<LtxDesktopOpenResponse>('/ltx-desktop/open', payload)
