<script setup lang="ts">
import { computed, onBeforeMount, onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getProjectBrain, getProjectWorkspace, listProjects } from '@/api/workbench'
import { useDirectorSession } from '@/composables/useDirectorSession'
import ChatPanel from './ChatPanel.vue'
import RefImageGrid from './RefImageGrid.vue'
import RefLineageCanvas from './RefLineageCanvas.vue'
import VisualPlannerPanel from './VisualPlannerPanel.vue'
import ProductionFlowPanel from './ProductionFlowPanel.vue'
import BrainExecutionTrace from './BrainExecutionTrace.vue'
import ExecutionObserverPanel from './ExecutionObserverPanel.vue'
import ProductionConsolePanel from './ProductionConsolePanel.vue'
import ShotCards from './ShotCards.vue'
import AssetPool from './AssetPool.vue'
import ContinueActionPanel from './ContinueActionPanel.vue'

interface ProjectOption {
  project_id: string
  name: string
}

const route = useRoute()
const router = useRouter()
const session = useDirectorSession()
provide('session', session)

const searchKeyword = ref('')
const projects = ref<ProjectOption[]>([])
const loadingProjects = ref(false)
const snapshotLabel = ref('')
const selectedSnapshotId = ref('')
const loadingWorkspace = ref(false)
const loadingBrain = ref(false)

const filteredProjects = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  if (!keyword) return projects.value
  return projects.value.filter((item) => {
    return item.project_id.toLowerCase().includes(keyword) || item.name.toLowerCase().includes(keyword)
  })
})

const hasRunningTasks = computed(() => session.activeTaskCount.value > 0)
const producedVideoCount = computed(() => {
  const shots = Array.isArray(session.shots.value) ? session.shots.value : []
  return shots.filter((shot: any) => Boolean(String(shot?.selected_video || '').trim())).length
})
const shotCount = computed(() => Array.isArray(session.shots.value) ? session.shots.value.length : 0)
const finalCutReady = computed(() => producedVideoCount.value > 0)
const finalCutTarget = computed(() => session.projectId.value ? `/director/final-cut/${session.projectId.value}` : '/director/final-cut')
const finalCutHint = computed(() => {
  if (!session.projectId.value) return '先选择项目，再进入剪辑台。'
  if (!shotCount.value) return '当前项目还没有分镜，先生成分镜和视频素材。'
  if (!producedVideoCount.value) return '还没有可剪辑视频，先完成至少一个分镜视频。'
  if (producedVideoCount.value < shotCount.value) return `已有 ${producedVideoCount.value}/${shotCount.value} 个视频可剪，可以先剪预览，也可以继续补齐素材。`
  return `已有 ${producedVideoCount.value}/${shotCount.value} 个视频可剪，建议进入剪辑台生成预览小样。`
})

function mapProjects(data: any): ProjectOption[] {
  const rows = data?.items || data?.projects || data || []
  if (!Array.isArray(rows)) return []
  return rows
    .map((row: any) => ({
      project_id: String(row.project_id || row.id || ''),
      name: String(row.name || row.project_id || row.id || '').trim(),
    }))
    .filter((row: ProjectOption) => row.project_id)
}

async function loadProjects() {
  loadingProjects.value = true
  try {
    const { data } = await listProjects()
    projects.value = mapProjects(data)
  } finally {
    loadingProjects.value = false
  }
}

function routeProjectId() {
  const param = route.params.projectId
  if (typeof param === 'string' && param.trim()) return param.trim()
  const query = route.query.project_id || route.query.projectId
  if (typeof query === 'string' && query.trim()) return query.trim()
  return ''
}

function clearProjectScopedState() {
  session.shots.value = []
  session.refImages.value = []
  session.projectWorkspace.value = null
  session.projectBrain.value = null
  session.executionEvents.value = []
  session.activeTaskCount.value = 0
}

function switchProject(projectId: string) {
  const next = String(projectId || '').trim()
  if (!next) return
  if (session.projectId.value !== next) {
    clearProjectScopedState()
    session.projectId.value = next
  }
}

function applyRouteProject() {
  switchProject(routeProjectId())
}

function chooseProject(projectId: string) {
  switchProject(projectId)
  if (projectId) void router.push(`/director/produce/${projectId}`)
}

async function loadProjectWorkspace(projectId: string) {
  if (!projectId) return
  loadingWorkspace.value = true
  try {
    const { data } = await getProjectWorkspace(projectId)
    session.projectWorkspace.value = data
    appendWorkspaceEvent(data)
  } catch (error: any) {
    session.projectWorkspace.value = null
    session.chatMessages.value = [
      ...session.chatMessages.value,
      {
        role: 'system',
        content: `项目工作区读取失败：${error?.response?.data?.detail || error?.message || 'unknown error'}`,
        timestamp: Date.now(),
      },
    ]
  } finally {
    loadingWorkspace.value = false
  }
}

async function loadProjectBrain(projectId: string) {
  if (!projectId) return
  loadingBrain.value = true
  try {
    const { data } = await getProjectBrain(projectId)
    session.projectBrain.value = data
    appendBrainEvent(data)
  } catch (error: any) {
    session.projectBrain.value = null
    session.chatMessages.value = [
      ...session.chatMessages.value,
      {
        role: 'system',
        content: `项目大脑读取失败：${error?.response?.data?.detail || error?.message || 'unknown error'}`,
        timestamp: Date.now(),
      },
    ]
  } finally {
    loadingBrain.value = false
  }
}

function appendWorkspaceEvent(workspace: any) {
  const wpId = workspace?.project_id || session.projectId.value
  const existing = session.chatMessages.value.some((item: any) => {
    return item?.meta?.workspace_loaded === wpId
  })
  if (existing) return
  const files = Array.isArray(workspace?.files) ? workspace.files : []
  const readyFiles = files.filter((item: any) => item.exists).length
  session.chatMessages.value = [
    ...session.chatMessages.value,
    {
      role: 'system',
      content: [
        `已读取主角工作区：${workspace?.project_id || session.projectId.value}`,
        `工作区版本：${workspace?.workspace_version || '-'}`,
        `项目文档：${readyFiles}/${files.length || 0} 个文件就绪`,
        '下一步：根据 PROJECT.md、memory 和当前场次判断生产卡点。',
      ].join('\n'),
      timestamp: Date.now(),
      meta: {
        workspace_loaded: workspace?.project_id,
        workspace_version: workspace?.workspace_version,
      },
    },
  ]
}

function appendBrainEvent(brain: any) {
  const brainId = brain?.project_id || session.projectId.value
  const existing = session.chatMessages.value.some((item: any) => {
    return item?.meta?.project_brain_loaded === brainId
  })
  if (existing) return
  session.chatMessages.value = [
    ...session.chatMessages.value,
    {
      role: 'system',
      content: [
        `项目大脑已读取：${brain?.project_id || session.projectId.value}`,
        `当前阶段：${brain?.phase || '-'}`,
        `下一步：${brain?.next_action_label || brain?.next_action || '-'}`,
        brain?.summary || '',
      ].filter(Boolean).join('\n'),
      timestamp: Date.now(),
      meta: {
        project_brain_loaded: brain?.project_id,
        project_brain_analyzed_at: brain?.analyzed_at,
      },
    },
  ]
}

function saveHistorySnapshot() {
  session.saveSnapshot(snapshotLabel.value)
  snapshotLabel.value = ''
}

function loadHistorySnapshot() {
  if (!selectedSnapshotId.value) return
  session.loadSnapshot(selectedSnapshotId.value)
}

function deleteHistorySnapshot() {
  if (!selectedSnapshotId.value) return
  session.deleteSnapshot(selectedSnapshotId.value)
  selectedSnapshotId.value = ''
}

onBeforeMount(() => {
  document.documentElement.setAttribute('data-theme', 'dark')
})

onMounted(async () => {
  session.restore()
  applyRouteProject()
  await loadProjects()
})

watch(
  () => [route.params.projectId, route.query.project_id, route.query.projectId],
  () => {
    applyRouteProject()
  },
  { immediate: true },
)

watch(
  () => session.projectId.value,
  (value) => {
    if (!value) return
    void loadProjectWorkspace(value)
    void loadProjectBrain(value)
    const match = projects.value.find((item) => item.project_id === value)
    if (match) {
      searchKeyword.value = `${match.name} (${match.project_id})`
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="produce-page">
    <header class="produce-header">
      <div class="title-wrap">
        <p class="kicker">Director Produce</p>
        <h2>导演生产中台</h2>
      </div>
      <div class="header-actions">
        <div class="project-select">
          <label for="project-search">项目</label>
          <input
            id="project-search"
            v-model="searchKeyword"
            placeholder="搜索项目名或 project_id"
            autocomplete="off"
          />
          <div v-if="searchKeyword || loadingProjects" class="project-menu">
            <div v-if="loadingProjects" class="project-item project-item--muted">加载项目中...</div>
            <button
              v-for="item in filteredProjects.slice(0, 8)"
              :key="item.project_id"
              class="project-item"
              type="button"
              @click="chooseProject(item.project_id)"
            >
              <span>{{ item.name }}</span>
              <small>{{ item.project_id }}</small>
            </button>
            <div v-if="!loadingProjects && filteredProjects.length === 0" class="project-item project-item--muted">
              无匹配项目
            </div>
          </div>
        </div>

        <input v-model.trim="session.projectId.value" class="project-id-input" placeholder="project_id" />
        <span class="workspace-status" :class="{ ready: session.projectWorkspace.value?.ready }">
          {{ loadingWorkspace ? '读取工作区...' : session.projectWorkspace.value?.ready ? '工作区已读取' : '工作区未就绪' }}
        </span>

        <span class="workspace-status" :class="{ ready: session.projectBrain.value?.can_continue }">
          {{ loadingBrain ? '读取项目大脑...' : session.projectBrain.value?.next_action_label || '项目大脑未读取' }}
        </span>

        <div class="history-box">
          <input v-model.trim="snapshotLabel" class="history-input" placeholder="历史快照名称" />
          <button class="btn-secondary transition-all" type="button" @click="saveHistorySnapshot">保存历史</button>
          <select v-model="selectedSnapshotId" class="history-select">
            <option value="">选择历史</option>
            <option v-for="item in session.historySnapshots.value" :key="item.id" :value="item.id">
              {{ new Date(item.savedAt).toLocaleString() }} - {{ item.label }}
            </option>
          </select>
          <button class="btn-secondary transition-all" type="button" :disabled="!selectedSnapshotId" @click="loadHistorySnapshot">加载</button>
          <button class="btn-secondary transition-all" type="button" :disabled="!selectedSnapshotId" @click="deleteHistorySnapshot">删除</button>
        </div>

        <button class="btn-secondary transition-all" type="button" @click="session.reset()">新建会话</button>
        <RouterLink
          class="btn-secondary final-cut-link transition-all"
          :to="finalCutTarget"
        >
          最终成片台
        </RouterLink>
      </div>
    </header>

    <ProductionFlowPanel />
    <ExecutionObserverPanel />
    <BrainExecutionTrace :loading-workspace="loadingWorkspace" :loading-brain="loadingBrain" />
    <section class="final-cut-bridge" :class="{ ready: finalCutReady }">
      <div>
        <p class="kicker">Final Cut Chain</p>
        <h3>{{ finalCutReady ? '素材已进入剪辑阶段' : '剪辑台等待素材' }}</h3>
        <p>{{ finalCutHint }}</p>
      </div>
      <RouterLink
        class="bridge-action transition-all"
        :class="{ disabled: !finalCutReady }"
        :to="finalCutTarget"
        :aria-disabled="!finalCutReady"
      >
        {{ finalCutReady ? '进入剪辑台做预览' : '等待可剪辑视频' }}
      </RouterLink>
    </section>
    <ProductionConsolePanel />

    <div class="produce-layout">
      <div class="left-col">
        <ChatPanel />
        <RefImageGrid />
        <VisualPlannerPanel />
        <RefLineageCanvas />
        <AssetPool />
        <ShotCards />
      </div>
      <div class="right-col">
        <ContinueActionPanel />
      </div>
    </div>

    <div v-if="hasRunningTasks" class="global-progress">
      <div class="global-progress__bar animate-progress"></div>
      <span>任务执行中 · {{ session.activeTaskCount.value }}</span>
    </div>
  </div>
</template>

<style scoped>
.produce-page {
  padding: 1.25rem;
  max-width: 1640px;
  margin: 0 auto;
}

.produce-header {
  position: relative;
  z-index: 20;
  margin-bottom: 1rem;
  padding: 0.9rem 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--color-bg) 78%, transparent);
  backdrop-filter: blur(10px);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.title-wrap h2 {
  margin: 0;
  font-size: 1.3rem;
}

.kicker {
  margin: 0 0 4px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-primary);
}

.header-actions {
  display: flex;
  gap: 0.8rem;
  align-items: flex-end;
  flex-wrap: wrap;
}

.project-select {
  position: relative;
  min-width: 300px;
}

.project-select label {
  display: block;
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}

.project-select input,
.project-id-input {
  width: 100%;
  height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  padding: 0 0.7rem;
}

.project-id-input {
  width: 180px;
}

.workspace-status {
  height: 36px;
  display: inline-flex;
  align-items: center;
  padding: 0 0.65rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  background: var(--color-bg-secondary);
  font-size: 0.76rem;
}

.workspace-status.ready {
  border-color: color-mix(in srgb, var(--color-success) 55%, var(--color-border));
  color: var(--color-success);
}

.history-box {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.history-input,
.history-select {
  height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  padding: 0 0.55rem;
}

.history-input {
  width: 140px;
}

.history-select {
  width: 220px;
}

.project-select input:focus,
.project-id-input:focus,
.history-input:focus,
.history-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 20%, transparent);
}

.project-menu {
  position: absolute;
  left: 0;
  right: 0;
  top: calc(100% + 6px);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-card);
  max-height: 260px;
  overflow-y: auto;
}

.project-item {
  width: 100%;
  border: none;
  background: transparent;
  color: var(--color-text);
  text-align: left;
  display: flex;
  justify-content: space-between;
  padding: 0.6rem 0.7rem;
  cursor: pointer;
}

.project-item:hover {
  background: var(--color-bg-secondary);
}

.project-item small {
  color: var(--color-text-secondary);
}

.project-item--muted {
  color: var(--color-text-secondary);
  cursor: default;
}

.project-item--muted:hover {
  background: transparent;
}

.produce-layout {
  display: grid;
  grid-template-columns: 5fr 7fr;
  gap: 1rem;
}

.final-cut-bridge {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
}

.final-cut-bridge.ready {
  border-color: color-mix(in srgb, var(--color-primary) 45%, var(--color-border));
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-bg));
}

.final-cut-bridge h3 {
  margin: 0;
  font-size: 1.02rem;
}

.final-cut-bridge p:last-child {
  margin: 0.35rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
}

.bridge-action {
  min-width: 176px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 0.9rem;
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: white;
  text-decoration: none;
  font-weight: 700;
}

.bridge-action.disabled {
  pointer-events: none;
  opacity: 0.55;
  border-color: var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
}

.left-col,
.right-col {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.right-col {
  position: sticky;
  top: 1rem;
  align-self: start;
}

.btn-secondary {
  height: 36px;
  padding: 0 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  cursor: pointer;
}

.final-cut-link {
  display: inline-flex;
  align-items: center;
  text-decoration: none;
}

.btn-secondary:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
  transform: translateY(-1px);
}

.btn-secondary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.global-progress {
  position: fixed;
  left: 24px;
  right: 24px;
  bottom: 16px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-bg) 84%, transparent);
  backdrop-filter: blur(8px);
  height: 34px;
  display: flex;
  align-items: center;
  overflow: hidden;
  z-index: 40;
}

.global-progress__bar {
  position: absolute;
  inset: 0;
  opacity: 0.35;
  background: var(--gradient-progress);
}

.global-progress span {
  position: relative;
  z-index: 1;
  font-size: 0.82rem;
  color: var(--color-text);
  padding-left: 0.9rem;
}

@media (max-width: 1200px) {
  .produce-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .final-cut-bridge {
    align-items: stretch;
    flex-direction: column;
  }

  .bridge-action {
    width: 100%;
  }
}
</style>
