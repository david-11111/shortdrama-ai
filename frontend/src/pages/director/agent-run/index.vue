<template>
  <main class="launch-page">
    <header class="launch-top">
      <div></div>
      <button class="avatar-button" type="button" :title="avatarTitle">{{ avatarLabel }}</button>
    </header>

    <section class="launch-center">
      <LaunchInput
        :projects="projects"
        :loading-projects="projectsLoading"
        :creating-run="creatingRun"
        :recent-runs="recentRuns"
        v-model:project-id="form.project_id"
        v-model:goal="form.goal"
        v-model:mode="form.mode"
        v-model:allowed-max-credits="form.allowed_max_credits"
        v-model:create-fresh-project="createFreshProject"
        @start="startRun"
        @project-change="handleProjectChange"
      />

      <section class="asset-intake" aria-label="input assets">
        <label class="asset-upload">
          <span>添加图片/视频监督素材</span>
          <input
            type="file"
            accept="image/*,video/*"
            multiple
            :disabled="creatingRun"
            @change="handleFileSelection"
          />
        </label>
        <div v-if="selectedFiles.length" class="asset-list">
          <div v-for="file in selectedFiles" :key="`${file.name}-${file.size}-${file.lastModified}`" class="asset-pill">
            <span>{{ fileKindLabel(file) }}</span>
            <strong>{{ file.name }}</strong>
            <button type="button" :disabled="creatingRun" @click="removeSelectedFile(file)">移除</button>
          </div>
        </div>
        <p v-if="uploadingAssets" class="asset-status">正在上传入口资产...</p>
      </section>

      <RecentRuns
        v-if="!createFreshProject"
        class="recent-area"
        :runs="recentRuns"
        @open="openRun"
      />

      <p v-if="error" class="inline-error">{{ error }}</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { createAgentRun, getAgentRuns } from '@/api/director'
import { createProject, listProjects, uploadAssetFile } from '@/api/workbench'
import { useAuthStore } from '@/stores/auth'
import LaunchInput, { type AgentProject } from './components/LaunchInput.vue'
import RecentRuns, { type RecentRunItem } from './components/RecentRuns.vue'

const router = useRouter()
const auth = useAuthStore()

const CLIENT_SETTINGS_KEY = 'agent-run:client-settings'
const CLIENT_RECENT_RUNS_KEY = 'agent-run:last-runs'

const projects = ref<AgentProject[]>([])
const projectsLoading = ref(false)
const creatingRun = ref(false)
const error = ref('')
const recentRuns = ref<RecentRunItem[]>(readRecentRuns())
const createFreshProject = ref(true)
const selectedFiles = ref<File[]>([])
const uploadingAssets = ref(false)

const savedSettings = readClientSettings()
const form = ref({
  project_id: String(savedSettings.project_id || localStorage.getItem('director:last_project_id') || ''),
  goal: String(savedSettings.goal || '新建一个30秒广告视频项目，先生成剧本和分镜，再生成关键帧，最后生成视频片段'),
  mode: (savedSettings.mode === 'step' ? 'step' : 'autopilot') as 'step' | 'autopilot',
  allowed_max_credits: Number(savedSettings.allowed_max_credits || 500),
})

const avatarTitle = computed(() => auth.user?.display_name || auth.user?.email || '当前用户')
const avatarLabel = computed(() => {
  const value = avatarTitle.value.trim()
  return value ? value.slice(0, 1).toUpperCase() : 'A'
})

watch(form, persistClientSettings, { deep: true })
watch(createFreshProject, persistClientSettings)

onMounted(async () => {
  await loadProjects()
})

function readClientSettings() {
  try {
    const raw = localStorage.getItem(CLIENT_SETTINGS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function readRecentRuns(): RecentRunItem[] {
  try {
    const raw = localStorage.getItem(CLIENT_RECENT_RUNS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((item) => item?.run_id).slice(0, 5) : []
  } catch {
    return []
  }
}

function persistClientSettings() {
  localStorage.setItem(
    CLIENT_SETTINGS_KEY,
    JSON.stringify({
      project_id: createFreshProject.value ? '' : form.value.project_id,
      goal: form.value.goal,
      mode: form.value.mode,
      allowed_max_credits: Number(form.value.allowed_max_credits || 0),
      create_fresh_project: createFreshProject.value,
      updated_at: new Date().toISOString(),
    }),
  )
}

async function loadProjects() {
  projectsLoading.value = true
  error.value = ''
  try {
    const { data } = await listProjects()
    const rows = data?.items || data?.projects || data || []
    projects.value = rows
      .map((row: any) => ({
        project_id: String(row.project_id || row.id || ''),
        name: String(row.name || row.project_id || row.id || ''),
        status: row.status,
      }))
      .filter((row: AgentProject) => row.project_id)

    if (!createFreshProject.value && !form.value.project_id && projects.value[0]) {
      form.value.project_id = projects.value[0].project_id
    }
    if (!createFreshProject.value && form.value.project_id) {
      await loadServerRecentRuns(form.value.project_id)
    }
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '读取项目失败'
  } finally {
    projectsLoading.value = false
  }
}

async function handleProjectChange() {
  localStorage.setItem('director:last_project_id', form.value.project_id)
  persistClientSettings()
  if (form.value.project_id) {
    await loadServerRecentRuns(form.value.project_id)
  }
}

async function loadServerRecentRuns(projectId: string) {
  try {
    const { data } = await getAgentRuns(projectId, { limit: 5 })
    const serverRuns: RecentRunItem[] = (data.runs || []).map((run) => ({
      run_id: run.run_id,
      project_id: run.project_id,
      project_name: projects.value.find((item) => item.project_id === run.project_id)?.name || run.project_id,
      goal: `Run ${shortId(run.run_id)}`,
      status: run.status,
      mode: run.status,
      created_at: run.started_at,
      credits: 0,
    }))
    mergeRecentRuns(serverRuns)
  } catch {
    // Recent runs are auxiliary; launch should not depend on this request.
  }
}

async function startRun() {
  if ((!form.value.project_id && !createFreshProject.value) || !form.value.goal.trim()) return
  creatingRun.value = true
  error.value = ''
  try {
    let projectId = form.value.project_id
    if (createFreshProject.value) {
      const { data: project } = await createProject({ name: projectNameFromGoal(form.value.goal) })
      projectId = String(project?.project_id || project?.id || '')
      if (!projectId) throw new Error('服务端未返回 project_id')
      form.value.project_id = projectId
      await loadProjects()
    } else {
      localStorage.setItem('director:last_project_id', projectId)
    }

    const inputAssets = await uploadInputAssets(projectId)
    const params = createFreshProject.value ? buildFreshProductionParams(form.value.goal) : {}
    if (inputAssets.length) {
      params.input_assets = inputAssets
    }

    const { data } = await createAgentRun({
      project_id: projectId,
      goal: form.value.goal.trim(),
      instruction: form.value.goal.trim(),
      mode: form.value.mode,
      action: createFreshProject.value ? 'production_run' : 'continue_project',
      allowed_max_credits: Number(form.value.allowed_max_credits || 0),
      params,
    })
    if (!data.run_id) throw new Error('服务端未返回 run_id')
    rememberRun(data.run_id, data.status || 'created', projectId)
    await router.push(`/director/agent-run/${data.run_id}`)
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '创建 Agent Run 失败'
  } finally {
    creatingRun.value = false
  }
}

function handleFileSelection(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || []).filter((file) => isSupportedInputAsset(file))
  const existing = new Set(selectedFiles.value.map(fileKey))
  selectedFiles.value = [
    ...selectedFiles.value,
    ...files.filter((file) => !existing.has(fileKey(file))),
  ].slice(0, 12)
  input.value = ''
}

function removeSelectedFile(target: File) {
  const key = fileKey(target)
  selectedFiles.value = selectedFiles.value.filter((file) => fileKey(file) !== key)
}

function isSupportedInputAsset(file: File) {
  return file.type.startsWith('image/') || file.type.startsWith('video/')
}

function assetTypeForFile(file: File) {
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('video/')) return 'video'
  return 'generic'
}

function fileKindLabel(file: File) {
  return assetTypeForFile(file) === 'video' ? '视频' : '图片'
}

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`
}

async function uploadInputAssets(projectId: string) {
  if (!selectedFiles.value.length) return []
  uploadingAssets.value = true
  try {
    const uploaded = []
    for (const file of selectedFiles.value) {
      const assetType = assetTypeForFile(file)
      const { data } = await uploadAssetFile(projectId, file, assetType, {
        role: assetType === 'video' ? 'source_video' : 'golden_reference',
        entrypoint: '/director/agent-run',
        goal: form.value.goal.trim(),
        filename: file.name,
      })
      uploaded.push({
        asset_id: String(data.asset_id || data.id || ''),
        asset_type: assetType,
        file_url: String(data.file_url || ''),
        role: assetType === 'video' ? 'source_video' : 'golden_reference',
      })
    }
    selectedFiles.value = []
    return uploaded.filter((asset) => asset.asset_id && asset.file_url)
  } finally {
    uploadingAssets.value = false
  }
}

function rememberRun(runId: string, status: string, projectId = form.value.project_id) {
  const project = projects.value.find((item) => item.project_id === projectId)
  mergeRecentRuns([{
    run_id: runId,
    project_id: projectId,
    project_name: project?.name || projectId,
    goal: form.value.goal,
    status,
    mode: form.value.mode,
    created_at: new Date().toISOString(),
    credits: Number(form.value.allowed_max_credits || 0),
  }])
}

function mergeRecentRuns(items: RecentRunItem[]) {
  const merged = [...items, ...recentRuns.value]
  const seen = new Set<string>()
  recentRuns.value = merged
    .filter((item) => {
      if (seen.has(item.run_id)) return false
      seen.add(item.run_id)
      return true
    })
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
    .slice(0, 5)
  localStorage.setItem(CLIENT_RECENT_RUNS_KEY, JSON.stringify(recentRuns.value))
}

function openRun(runId: string) {
  router.push(`/director/agent-run/${runId}`)
}

function projectNameFromGoal(goal: string) {
  const trimmed = goal.trim().replace(/\s+/g, ' ')
  return trimmed ? trimmed.slice(0, 28) : `Agent 项目 ${new Date().toLocaleString('zh-CN', { hour12: false })}`
}

function shortId(id: string) {
  return id ? `${id.slice(0, 8)}...` : ''
}

function buildFreshProductionParams(goal: string) {
  const duration = inferDurationSec(goal)
  return {
    provider_mode: 'real',
    clean_start: true,
    entrypoint: '/director/agent-run',
    image_provider: 'seedream',
    video_provider: 'ltx2.3',
    target_duration_sec: duration,
    max_image_tasks: duration >= 30 ? 8 : 4,
    max_video_tasks: duration >= 30 ? 6 : 3,
    wait_provider_timeout_sec: 1800,
    allow_local_placeholders: false,
    intent_brief: goal.trim(),
  } as Record<string, any>
}

function inferDurationSec(goal: string) {
  const match = String(goal || '').match(/(\d{1,3})\s*(秒|s|S|sec|second)/)
  const value = match ? Number(match[1]) : 30
  if (!Number.isFinite(value) || value <= 0) return 30
  return Math.min(Math.max(value, 5), 180)
}
</script>

<style scoped>
.launch-page {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 100vh;
  background: #0d1117;
  color: #e6edf3;
}

.launch-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 22px;
}

.avatar-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid #30363d;
  border-radius: 999px;
  background: #161b22;
  color: #e6edf3;
  font-weight: 700;
}

.launch-center {
  display: grid;
  align-content: center;
  gap: 14px;
  min-height: 0;
  padding: 24px;
}

.recent-area {
  align-self: start;
}

.asset-intake {
  display: grid;
  gap: 8px;
  width: min(640px, 100%);
  margin: 0 auto;
}

.asset-upload {
  display: flex;
  justify-content: center;
}

.asset-upload span {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 0 12px;
  background: #161b22;
  color: #58a6ff;
  font-size: 12px;
  cursor: pointer;
}

.asset-upload input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.asset-list {
  display: grid;
  gap: 6px;
}

.asset-pill {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 4px 8px;
  background: #161b22;
  text-align: left;
}

.asset-pill span {
  color: #8b949e;
  font-size: 12px;
}

.asset-pill strong {
  overflow: hidden;
  color: #e6edf3;
  font-size: 12px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-pill button {
  border: 0;
  background: transparent;
  color: #ff7b72;
  cursor: pointer;
  font-size: 12px;
}

.asset-status {
  margin: 0;
  color: #8b949e;
  font-size: 12px;
  text-align: center;
}

.inline-error {
  width: min(600px, 100%);
  margin: 0 auto;
  color: #ff7b72;
  font-size: 13px;
  text-align: center;
}

@media (max-width: 720px) {
  .launch-center {
    align-content: start;
    padding: 18px;
  }
}
</style>
