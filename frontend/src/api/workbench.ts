import client from './client'
import type { AxiosProgressEvent } from 'axios'

// ── 项目 ──
export const createProject = (payload: { name: string; input_path?: string }) =>
  client.post('/projects', payload, { timeout: 180000 })

export const listProjects = () =>
  client.get('/projects')

export const getProject = (projectId: string) =>
  client.get(`/projects/${projectId}`)

export const getProjectLogs = (projectId: string) =>
  client.get(`/projects/${projectId}/logs`)

export const getProjectWorkspace = (projectId: string) =>
  client.get(`/projects/${projectId}/workspace`)

export const getProjectBrain = (projectId: string) =>
  client.get(`/projects/${projectId}/brain`)

export const getProjectAgentEvents = (projectId: string, limit = 100) =>
  client.get(`/projects/${projectId}/agent-events`, { params: { limit } })

export const continueProjectBrain = (projectId: string, data?: {
  action?: string
  instruction?: string
  mode?: 'preview' | 'step' | 'autopilot'
  shot_indices?: number[]
  estimated_max_credits?: number
  allowed_max_credits?: number
}) => client.post(`/projects/${projectId}/brain/continue`, data || {})

export const initProjectWorkspace = (projectId: string, data?: { force?: boolean }) =>
  client.post(`/projects/${projectId}/workspace/init`, data || {})

export const writeProjectWorkspaceFile = (projectId: string, data: {
  path: string
  content: string
  mode?: 'append' | 'replace'
  source?: string
  reason?: string
  force?: boolean
}) => client.post(`/projects/${projectId}/workspace/write`, data)

// ── 脚本行 ──
export const listShotRows = (projectId: string) =>
  client.get(`/projects/${projectId}/shot-rows`)

export const getShotRow = (projectId: string, idx: number) =>
  client.get(`/projects/${projectId}/shot-rows/${idx}`)

export const updateShotRow = (projectId: string, idx: number, data: {
  prompt?: string
  duration?: number
  status?: string
  selected?: boolean
  character_refs?: string[]
  scene_refs?: string[]
  prop_refs?: string[]
  costume_refs?: string[]
  style_refs?: string[]
  selected_image?: string | null
  selected_video?: string | null
}) => client.put(`/projects/${projectId}/shot-rows/${idx}`, data)

export const listShotPromptRevisions = (projectId: string, idx: number) =>
  client.get(`/projects/${projectId}/shot-rows/${idx}/prompt-revisions`)

export const applyShotSafeRewrite = (projectId: string, idx: number, data?: {
  project_goal?: string
}) => client.post(`/projects/${projectId}/shot-rows/${idx}/safe-rewrite`, data || {})

export const rollbackShotSafeRewrite = (projectId: string, idx: number, data?: {
  revision_id?: string
  force?: boolean
}) => client.post(`/projects/${projectId}/shot-rows/${idx}/rollback-rewrite`, data || {})

// 最终成片剪辑方案
export const getFinalEditPlan = (projectId: string) =>
  client.get(`/projects/${projectId}/final-edit-plan`)

export const saveFinalEditPlan = (projectId: string, plan: Record<string, unknown>) =>
  client.put(`/projects/${projectId}/final-edit-plan`, { plan })

// ── 资产 ──
export const listAssets = (projectId: string, assetType?: string) =>
  client.get(`/projects/${projectId}/assets`, { params: { asset_type: assetType } })

export const getVisualPlan = (projectId: string) =>
  client.get(`/projects/${projectId}/visual-plan`)

export const applyVisualPlanAction = (projectId: string, actionId: string, data?: {
  asset_id?: string
}) => client.post(`/projects/${projectId}/visual-plan/actions/${actionId}/apply`, data || {})

export const getAsset = (projectId: string, assetId: string) =>
  client.get(`/projects/${projectId}/assets/${assetId}`)

export const createAsset = (projectId: string, data: {
  asset_type: string
  file_url?: string
  file_path?: string
  content_base64?: string
  filename?: string
  metadata?: Record<string, unknown>
}) => client.post(`/projects/${projectId}/assets`, data)

export const uploadAssetFile = (
  projectId: string,
  file: File,
  assetType: string,
  metadata?: Record<string, unknown>,
  onUploadProgress?: (event: AxiosProgressEvent) => void,
) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('asset_type', assetType)
  if (metadata) {
    formData.append('metadata_json', JSON.stringify(metadata))
  }
  return client.post(`/projects/${projectId}/assets/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress,
  })
}

export const importAssetUrl = (projectId: string, data: {
  url: string
  asset_type?: string
  filename?: string
  metadata?: Record<string, unknown>
}) => client.post(`/projects/${projectId}/assets/import-url`, data)

export const updateAsset = (projectId: string, assetId: string, data: {
  asset_type?: string
  file_url?: string
  metadata?: Record<string, unknown>
  status?: string
}) => client.put(`/projects/${projectId}/assets/${assetId}`, data)

export const deleteAsset = (projectId: string, assetId: string) =>
  client.delete(`/projects/${projectId}/assets/${assetId}`)

// ── 批量生成 ──
export const batchGenerateImages = (payload: {
  items: Array<{ shot_row: object; provider?: string }>
  provider?: string
}) => client.post('/batch/generate-images', payload)

export const batchGenerateVideos = (payload: {
  items: Array<{ shot_row: object; provider?: string }>
  provider?: string
}) => client.post('/batch/generate-videos', payload)
