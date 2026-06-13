import { ref, watch } from 'vue'

export interface MediaReview {
  version?: string
  media_type?: 'image' | 'video'
  status: 'usable' | 'cuttable' | 'needs_review' | 'regenerate' | string
  score: number
  notes?: string[]
  actions?: string[]
}

export interface MediaCandidate {
  url: string
  review?: MediaReview
  review_status?: string
  review_score?: number
}

export interface PromptRevision {
  revision_id: string
  shot_index: number
  source: string
  original_prompt: string
  rewritten_prompt: string
  created_at: string
  applied_at?: string
  rolled_back_at?: string | null
  preflight?: Record<string, any>
}

export interface PromptRevisionPayload {
  latest?: PromptRevision | null
  items?: PromptRevision[]
  count?: number
}

export interface ShotProductionState {
  next_action:
    | 'needs_rewrite'
    | 'needs_assets'
    | 'can_generate_image'
    | 'needs_image_review'
    | 'can_generate_video'
    | 'needs_video_review'
    | 'can_edit'
    | 'done'
    | 'blocked'
  phase: string
  severity: string
  title: string
  reason: string
  primary_action_label: string
  can_auto_continue: boolean
  blocking_refs: string[]
  review_status: string
}

export interface Shot {
  index: number
  prompt: string
  duration: number
  status: string
  image_candidates: Array<string | MediaCandidate>
  video_variants: Array<string | MediaCandidate>
  selected_image: string | null
  selected_video: string | null
  character_refs: string[]
  scene_refs: string[]
  prop_refs: string[]
  costume_refs: string[]
  style_refs: string[]
  last_error?: string
  prompt_revision?: PromptRevisionPayload
  production_state?: ShotProductionState
  director_preflight?: {
    risk_level: 'ready' | 'warning' | 'blocked'
    risk_count: number
    risks: Array<{ code: string; title: string; reason: string; severity: string }>
    suggestions: string[]
    required_refs: string[]
    missing_refs: string[]
    safe_prompt: string
    can_generate_image: boolean
    can_generate_video: boolean
  }
}

export interface RefImageItem {
  id?: string
  url: string
  view: string
  asset_id?: string
  pending?: boolean
  progress?: number
  selected?: boolean
  error?: string
  parent_asset_id?: string
  parent_url?: string
  lineage_role?: 'source' | 'derived' | 'shot'
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: number
  meta?: {
    drafts?: Array<{
      version: string
      title: string
      source: string
      content: string
    }>
    score?: {
      total: number
      items?: Record<string, number>
      suggestions?: string[]
    }
    quality_gate?: {
      allow_storyboard?: boolean
      allow_reference_images?: boolean
      allow_video_production?: boolean
      reason?: string
    }
    process_trace?: Record<string, any>
    workspace_writes?: Array<{
      path: string
      mode?: string
      source?: string
      reason?: string
      decision_recorded?: boolean
    }>
    workspace_loaded?: string
    workspace_version?: string
    project_brain_loaded?: string
    project_brain_analyzed_at?: string
  }
}

export type ExecutionEventTone = 'info' | 'active' | 'success' | 'warning' | 'error'

export interface ExecutionEvent {
  id: string
  project_id?: string
  task_id?: string
  source: 'brain' | 'api' | 'queue' | 'worker' | 'ffmpeg' | 'ledger' | 'ui'
  phase: string
  title: string
  detail: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'blocked'
  progress?: number
  tone?: ExecutionEventTone
  created_at: number
  updated_at?: number
  meta?: Record<string, any>
}

export interface AnchorLocks {
  lock_character: boolean
  lock_scene: boolean
  lock_costume: boolean
  lock_prop: boolean
}

export interface ProjectWorkspaceFile {
  path: string
  exists: boolean
  size: number
}

export interface ProjectWorkspace {
  project_id: string
  workspace_root?: string
  workspace_version?: string
  required_files?: string[]
  files?: ProjectWorkspaceFile[]
  ready?: boolean
  bootstrap?: Record<string, string>
}

export interface ProjectBrain {
  project_id: string
  brain_version?: string
  analyzed_at?: string
  phase?: string
  stage_index?: number
  summary?: string
  next_action?: string
  next_action_label?: string
  can_continue?: boolean
  missing?: Array<{ code: string; label: string }>
  risks?: Array<{ code: string; severity: string; title: string; reason: string }>
  signals?: Record<string, any>
  read_files?: ProjectWorkspaceFile[]
  context?: Record<string, any>
}

export function useDirectorSession() {
  const projectId = ref('')
  const shots = ref<Shot[]>([])
  const chatMessages = ref<ChatMessage[]>([])
  const refImages = ref<RefImageItem[]>([])
  const projectWorkspace = ref<ProjectWorkspace | null>(null)
  const projectBrain = ref<ProjectBrain | null>(null)
  const anchorLocks = ref<AnchorLocks>({ lock_character: true, lock_scene: false, lock_costume: true, lock_prop: false })
  const directorStage = ref(0)
  const loading = ref(false)
  const activeTaskCount = ref(0)
  const executionEvents = ref<ExecutionEvent[]>([])
  const historySnapshots = ref<Array<{ id: string; label: string; savedAt: number; data: Record<string, unknown> }>>([])

  const STORAGE_KEY = 'director_session'
  const HISTORY_KEY = 'director_session_history'
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let lastSave = 0
  let suspended = false

  function save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        projectId: projectId.value, shots: shots.value,
        chatMessages: chatMessages.value.slice(-80), refImages: refImages.value,
        anchorLocks: anchorLocks.value, projectWorkspace: projectWorkspace.value,
        directorStage: directorStage.value,
        executionEvents: executionEvents.value.slice(-30), savedAt: Date.now(),
      }))
    } catch {}
  }

  function debouncedSave() {
    if (suspended) return
    if (saveTimer) clearTimeout(saveTimer)
    const wait = Math.max(500, 1000 - (Date.now() - lastSave))
    saveTimer = setTimeout(() => { lastSave = Date.now(); save() }, wait)
  }

  function restore() {
    try { historySnapshots.value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') } catch { historySnapshots.value = [] }
    suspended = true
    try {
      const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
      if (!data) return
      if (data.projectId) projectId.value = data.projectId
      if (data.shots) shots.value = data.shots
      if (data.chatMessages) chatMessages.value = data.chatMessages
      if (data.refImages) refImages.value = data.refImages
      if (data.projectWorkspace) projectWorkspace.value = data.projectWorkspace
      projectBrain.value = null
      if (data.anchorLocks) anchorLocks.value = { ...anchorLocks.value, ...data.anchorLocks }
      if (typeof data.directorStage === 'number') directorStage.value = data.directorStage
      if (Array.isArray(data.executionEvents)) executionEvents.value = data.executionEvents.slice(-120)
    } catch {} finally { suspended = false }
  }

  function reset() {
    projectId.value = ''; shots.value = []; chatMessages.value = []; refImages.value = []
    projectWorkspace.value = null; projectBrain.value = null; directorStage.value = 0
    activeTaskCount.value = 0; executionEvents.value = []
    localStorage.removeItem(STORAGE_KEY)
  }

  function saveSnapshot(label = '') {
    const title = label.trim() || (chatMessages.value[chatMessages.value.length - 1]?.content || '').slice(0, 32) || projectId.value || 'snapshot'
    historySnapshots.value = [{
      id: `snap-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      label: title, savedAt: Date.now(),
      data: JSON.parse(JSON.stringify({ projectId: projectId.value, shots: shots.value, chatMessages: chatMessages.value, refImages: refImages.value, anchorLocks: anchorLocks.value, projectWorkspace: projectWorkspace.value, directorStage: directorStage.value, executionEvents: executionEvents.value })),
    }, ...historySnapshots.value].slice(0, 12)
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(historySnapshots.value)) } catch {}
  }

  function loadSnapshot(id: string) {
    const snap = historySnapshots.value.find((s) => s.id === id)
    if (!snap) return
    suspended = true
    try {
      const d = snap.data as any
      projectId.value = d.projectId || ''
      shots.value = d.shots || []; chatMessages.value = d.chatMessages || []
      refImages.value = d.refImages || []; executionEvents.value = d.executionEvents || []
      projectWorkspace.value = d.projectWorkspace || null; projectBrain.value = null
      if (d.anchorLocks) anchorLocks.value = { ...anchorLocks.value, ...d.anchorLocks }
      directorStage.value = Number.isFinite(d.directorStage) ? d.directorStage : 0
    } finally { suspended = false; save() }
  }

  function deleteSnapshot(id: string) {
    historySnapshots.value = historySnapshots.value.filter((s) => s.id !== id)
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(historySnapshots.value)) } catch {}
  }

  function beginTask() { activeTaskCount.value += 1 }
  function endTask() { activeTaskCount.value = Math.max(0, activeTaskCount.value - 1) }

  function pushExecutionEvent(event: Omit<ExecutionEvent, 'id' | 'created_at'> & { id?: string; created_at?: number }) {
    const now = Date.now()
    const item: ExecutionEvent = { id: event.id || `evt-${now}-${Math.random().toString(16).slice(2, 8)}`, created_at: event.created_at || now, updated_at: now, ...event }
    executionEvents.value.push(item)
    if (executionEvents.value.length > 160) executionEvents.value = executionEvents.value.slice(-120)
    return item
  }

  function upsertExecutionEvent(matcher: (e: ExecutionEvent) => boolean, patch: Partial<Omit<ExecutionEvent, 'id' | 'created_at'>>, fallback?: Omit<ExecutionEvent, 'id' | 'created_at'>) {
    const idx = executionEvents.value.findIndex(matcher)
    if (idx >= 0) {
      const next = [...executionEvents.value]
      next[idx] = { ...next[idx], ...patch, updated_at: Date.now() }
      executionEvents.value = next
      return next[idx]
    }
    if (fallback) return pushExecutionEvent({ ...fallback, ...patch, updated_at: Date.now() })
    return null
  }

  function clearExecutionEvents() { executionEvents.value = [] }

  watch([projectId, shots, chatMessages, refImages, anchorLocks, projectWorkspace, projectBrain, directorStage], debouncedSave, { deep: true })
  watch(executionEvents, debouncedSave, { deep: false })

  return {
    projectId, shots, chatMessages, refImages, projectWorkspace, projectBrain,
    anchorLocks, directorStage, loading, activeTaskCount, executionEvents, historySnapshots,
    beginTask, endTask, pushExecutionEvent, upsertExecutionEvent, clearExecutionEvents,
    save, restore, reset, saveSnapshot, loadSnapshot, deleteSnapshot,
  }
}
