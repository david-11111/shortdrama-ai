import client from './client'
import type { AxiosRequestConfig } from 'axios'

interface ChatPayload {
  project_id: string
  messages: Array<{ role: string; content: string }>
  preset?: string
  output_options?: {
    need_advice?: boolean
    need_reference_images?: boolean
    need_storyboard?: boolean
    need_video?: boolean
  }
}

interface ScriptPayload {
  project_id: string
  topic: string
  style?: string
  shot_count?: number
}

interface PreparePayload {
  project_id: string
  shot_indices?: number[]
}

interface ProducePayload {
  project_id: string
  shot_indices?: number[]
  skip_images?: boolean
  provider?: string
  anchor_locks?: {
    lock_character?: boolean
    lock_scene?: boolean
    lock_costume?: boolean
    lock_prop?: boolean
  }
}

interface ExportFinalPayload {
  project_id: string
  shot_indices?: number[]
  transitions?: string[]
  subtitles?: Array<{ start: number; end: number; text: string }>
  bgm_path?: string
  bgm_volume?: number
  edit_plan?: Record<string, unknown>
}

interface ReferenceImagesPayload {
  project_id: string
  character_description: string
  views: string[]
  asset_type?: string
}

interface AsyncResult {
  task_id: string
  status: string
}

type RequestOptions = Pick<AxiosRequestConfig, 'silent' | 'dedupeKey'>

interface EvolutionPatternsQuery {
  project_id?: string
  problem_type?: string
  verdict_type?: string
  limit?: number
}

// Sync endpoints
export const getDirectorPresets = () =>
  client.get('/director/presets')

export const getEvaluationStandard = () =>
  client.get('/director/evaluation-standard')

export const getFinalCutRecipes = () =>
  client.get('/director/final-cut-recipes')

export const generateFinalCutPlanAi = (payload: {
  project_id: string
  recipe_id: string
  instruction?: string
}) => client.post('/director/final-cut-plan/ai', payload)

export const applyFinalCutRule = (payload: {
  project_id: string
  recipe_id: string
}) => client.post('/director/final-cut-plan/apply-rule', payload)

export const getEvolutionPatterns = (params?: EvolutionPatternsQuery) =>
  client.get('/director/evolution/patterns', { params })

export const getProjectMemory = (projectId: string) =>
  client.get(`/director/${projectId}/project-memory`)

// Async endpoints (return task_id)
export const directorChat = (payload: ChatPayload, options?: RequestOptions) =>
  client.post<AsyncResult>('/director/chat', payload, options)

export const directorScript = (payload: ScriptPayload, options?: RequestOptions) =>
  client.post<AsyncResult>('/director/script', payload, options)

export const directorPrepare = (payload: PreparePayload, options?: RequestOptions) =>
  client.post<AsyncResult>('/director/prepare', payload, options)

export const directorProduce = (payload: ProducePayload, options?: RequestOptions) =>
  client.post<AsyncResult>('/director/produce', payload, options)

export const directorExportFinal = (payload: ExportFinalPayload, options?: RequestOptions) =>
  client.post<AsyncResult & { clip_count: number }>('/director/export-final', payload, options)

export const directorExportPreview = (payload: ExportFinalPayload, options?: RequestOptions) =>
  client.post<AsyncResult & { clip_count: number }>('/director/export-preview', payload, options)

export const directorReferenceImages = (payload: ReferenceImagesPayload, options?: RequestOptions) =>
  client.post<AsyncResult>('/director/reference-images', payload, options)

// Diagnose and evaluation
export const diagnoseTask = (payload: object) =>
  client.post('/director/diagnose-task', payload)

export const recommendMode = (payload: object) =>
  client.post('/director/recommend-mode', payload)

export const explainDecision = (payload: object) =>
  client.post('/director/explain-decision', payload)

export const evaluateRun = (payload: object) =>
  client.post('/director/evaluate-run', payload)

export const reworkSuggest = (payload: object) =>
  client.post('/director/rework-suggest', payload)

export const updateProjectMemory = (projectId: string, payload: object) =>
  client.post(`/director/${projectId}/project-memory`, payload)

export const recordEvolution = (payload: object) =>
  client.post('/director/evolution/record', payload)

// ── Agent Events ──

export interface AgentEvent {
  id: string
  type?: string
  event_type: string
  actor?: string
  run_id: string | null
  project_id?: string
  task_id: string | null
  step_id?: string | null
  user_id?: number | null
  source?: string
  phase?: string
  title?: string
  detail?: string
  status?: string
  progress?: number | null
  meta?: Record<string, unknown>
  data?: Record<string, unknown>
  created_at: string
}

export interface AgentRun {
  run_id: string
  project_id: string
  status: string
  started_at: string
  finished_at: string | null
  event_count: number
}

export interface AgentEventsResponse {
  events: AgentEvent[]
  total: number
}

export interface AgentRunsResponse {
  runs: AgentRun[]
  total: number
}

export interface AgentRunSnapshotNode {
  id: string
  title: string
  index?: number
  status: string
  summary: string
  brain_summary?: string
  evidence_summary?: string
  progress: number
  risks?: Array<Record<string, unknown>>
  artifacts?: Array<AgentRunSnapshotArtifact>
  event_ids: string[]
  task_ids: string[]
  available_actions: string[]
  gate?: Record<string, unknown>
  flow_stages?: AgentRunSnapshotFlowStage[]
}

export interface AgentRunSnapshotArtifact {
  id: string
  run_id: string | null
  project_id?: string
  task_id: string | null
  user_id?: number | null
  artifact_type: string
  uri: string
  summary: string
  meta?: Record<string, unknown>
  created_at?: string | null
}

export interface AgentRunSnapshotStreamItem {
  id: string
  node_id: string
  time?: string | null
  level: string
  text: string
  event_type?: string
  source?: string
  actor?: string
  event_kind?: string
  visibility?: string
  summary?: string
  reason?: string
  status?: string
  progress?: number | null
  phase?: string
  title?: string
  detail?: string
  meta?: Record<string, unknown>
  data?: Record<string, unknown>
}

export interface AgentRunSnapshotEvidenceLayer {
  id: string
  title: string
  summary: string
  count: number
  items: Array<Record<string, unknown> | unknown>
  meta?: Record<string, unknown>
}

export interface AgentRunSnapshotFlowStage {
  id: string
  title: string
  action: string
  node_id: string
  status: string
  source?: 'state_machine' | 'project_state' | 'run_evidence' | 'gate' | string
  progress: number
  gate: {
    allowed: boolean
    missing: string[]
    reason: string
  }
  stats: Record<string, unknown>
  policy?: {
    version?: string
    depends_on?: string[]
    gate_rules?: Array<Record<string, unknown>>
    status_rules?: Array<Record<string, unknown>>
  }
}

export interface AgentRunOutputMedia {
  id: string
  kind: string
  url: string
  title: string
  summary?: string
  shot_index?: number | string | null
  source?: string
}

export interface AgentRunKeyframeCandidate {
  artifact_id?: string
  shot_index?: number | string | null
  url: string
  prompt?: string
  provider?: string
  status?: string
  selected?: boolean
  quality_score?: number | string | null
  source?: string
}

export interface AgentRunKeyframePoolItem {
  shot_index?: number | string | null
  prompt?: string
  status?: string
  candidates: AgentRunKeyframeCandidate[]
  summary: {
    candidate_count: number
    selected_count: number
    running_count: number
    failed_count: number
  }
}

export function normalizeMediaUrl(value?: string | null): string {
  const raw = String(value || '').trim().replace(/\\/g, '/')
  if (!raw) return ''
  if (/^(https?:)?\/\//i.test(raw) || /^(data|blob):/i.test(raw)) return raw
  return `/${raw.replace(/^\/+/, '')}`
}

export interface AgentRunOutputs {
  script: {
    content: string
    items: Array<{ title: string; content: string; source?: string }>
  }
  director_notes: Array<{ title: string; content: string; source?: string; created_at?: string }>
  keyframe_pool?: AgentRunKeyframePoolItem[]
  images: AgentRunOutputMedia[]
  videos: AgentRunOutputMedia[]
  shots: Array<Record<string, unknown> & {
    shot_index?: number | string
    prompt?: string
    selected_image?: string
    selected_video?: string
    status?: string
    last_error?: string
  }>
  summary: {
    image_count: number
    video_count: number
    shot_count: number
    final_video_url?: string
    run_summary?: string
  }
}

export interface AgentRunDecisionContext {
  current_goal: string
  awaiting_user: string
  pending_action: Record<string, unknown> | null
  last_recommendation: string
  blocked_by: string[]
  block_reason: string
  next_action: string
  routing_source: string
  target_domain: string
  updated_at: string
}

export interface AgentRunSnapshot {
  version: string
  run: {
    run_id: string
    project_id: string
    user_id: number
    trigger_type?: string | null
    goal: string
    status: string
    current_phase: string
    mode: string
    started_at?: string | null
    ended_at?: string | null
    summary: string
    final_decision: string
  }
  project: {
    project_id: string
    name: string
  }
  budget: {
    estimated_max_credits: number
    allowed_max_credits: number
    reserved_credits: number
    spent_credits: number
    refunded_credits: number
    remaining_run_budget: number
    task_credits_reserved: number
    task_credits_charged?: number
    task_credits_refunded?: number
  }
  ledger: Record<string, unknown>
  nodes: AgentRunSnapshotNode[]
  flow?: AgentRunSnapshotFlowStage[]
  decision_context: AgentRunDecisionContext
  stream: AgentRunSnapshotStreamItem[]
  evidence: Record<string, Record<string, unknown>>
  evidence_layers: Record<string, AgentRunSnapshotEvidenceLayer>
  outputs?: AgentRunOutputs
  actions: Array<{ id: string; label: string; enabled: boolean; reason?: string }>
  artifacts: AgentRunSnapshotArtifact[]
  tasks: Array<Record<string, unknown>>
  meta?: {
    limits?: Record<string, number>
    totals?: Record<string, number>
    truncated?: Record<string, boolean>
  }
}

export interface CreateAgentRunPayload {
  project_id: string
  goal?: string
  mode?: 'preview' | 'step' | 'autopilot'
  action?: 'continue_project' | 'production_run'
  continue_action?: string
  instruction?: string
  allowed_max_credits?: number
  estimated_max_credits?: number
  params?: Record<string, unknown>
}

export interface CreateAgentRunResponse {
  run_id: string
  project_id: string
  status: string
  mode: string
  action: string
  task_id?: string
  production_run_id?: string
  result?: Record<string, unknown>
}

export const getAgentEvents = (
  projectId: string,
  params?: { limit?: number; run_id?: string; event_type?: string }
) => client.get<AgentEventsResponse>(`/projects/${projectId}/agent-events`, { params })

export const getAgentRuns = (
  projectId: string,
  params?: { limit?: number }
) => client.get<AgentRunsResponse>(`/projects/${projectId}/agent-runs`, { params })

export const getAgentRunSnapshot = (
  runId: string,
  params?: {
    event_limit?: number
    task_limit?: number
    artifact_limit?: number
    evidence_item_limit?: number
    stream_limit?: number
  },
) =>
  client.get<AgentRunSnapshot>(`/agent-runs/${runId}/snapshot`, {
    dedupeKey: `agent-run-snapshot:${runId}`,
    params,
  })

export const getAgentRunEvents = (
  runId: string,
  params?: { limit?: number; event_type?: string },
) => client.get<AgentEventsResponse>(`/agent-runs/${runId}/events`, { params })

export const retryAgentRunFailedVideos = (runId: string, payload?: Record<string, unknown>) =>
  client.post(`/agent-runs/${runId}/actions/retry-failed`, payload || {})

export const exportAgentRunPartial = (runId: string, payload?: Record<string, unknown>) =>
  client.post(`/agent-runs/${runId}/actions/export-partial`, payload || {})

export const changeAgentRunProvider = (runId: string, payload: { provider: 'seedance' | 'kling' | 'joy-echo' | 'ltx2.3' }) =>
  client.post(`/agent-runs/${runId}/actions/change-provider`, payload)

export const continueAgentRunStep = (runId: string, payload?: Record<string, unknown>) =>
  client.post(`/agent-runs/${runId}/actions/continue-step`, payload || {})

export const skipShotAction = (runId: string, payload?: { shot_index?: number }) =>
  client.post(`/agent-runs/${runId}/actions/skip-shot`, payload || {})

export const previewAgentRunKeyframeBatch = (runId: string, payload: Record<string, unknown>) =>
  client.post(`/agent-runs/${runId}/actions/keyframe-batch/preview`, payload)

export const generateAgentRunKeyframeBatch = (runId: string, payload: Record<string, unknown>) =>
  client.post(`/agent-runs/${runId}/actions/generate-keyframe-batch`, payload)

export const selectAgentRunKeyframeCandidate = (runId: string, payload: Record<string, unknown>) =>
  client.post(`/agent-runs/${runId}/actions/select-keyframe-candidate`, payload)

export const generateAgentRunVideoFromPool = (runId: string, payload: Record<string, unknown>) =>
  client.post(`/agent-runs/${runId}/actions/generate-video-from-pool`, payload)

export const cancelAgentRun = (runId: string) =>
  client.post(`/agent-runs/${runId}/actions/cancel`)

export const createAgentRun = (payload: CreateAgentRunPayload) =>
  client.post<CreateAgentRunResponse>('/agent-runs', payload, { timeout: 180000 })
