<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { applyFinalCutRule, directorExportFinal, directorExportPreview, generateFinalCutPlanAi, getFinalCutRecipes } from '@/api/director'
import { getFinalEditPlan, importAssetUrl, listAssets, listProjects, saveFinalEditPlan, uploadAssetFile } from '@/api/workbench'
import { useTaskPoller } from '@/composables/useTaskPoller'

interface ProjectOption {
  project_id: string
  name: string
}

interface EditClip {
  shot_index: number
  order: number
  enabled: boolean
  video_url: string
  prompt: string
  duration: number
  trim_start: number
  trim_end: number
  transition: string
  subtitle: string
}

interface EditPlan {
  version: number
  settings: {
    transition: string
    burn_subtitles: boolean
    subtitle_source: string
    bgm_path: string
    bgm_volume: number
    cover_title: string
    cover_frame_sec: number | null
  }
  clips: EditClip[]
}

interface FinalCutRecipe {
  id: string
  name: string
  category: string
  difficulty: string
  commercial_value?: string
  ffmpeg_feasibility: string
  summary: string
  rules?: string[]
  steps?: string[]
  formula?: string[]
  planner_actions?: string[]
  needs_ai?: string[]
  needs_assets?: string[]
}

const route = useRoute()
const projects = ref<ProjectOption[]>([])
const projectId = ref('')
const loading = ref(false)
const saving = ref(false)
const exporting = ref(false)
const previewing = ref(false)
const error = ref('')
const finalUrl = ref('')
const previewUrl = ref('')
const selectedShot = ref<number | null>(null)
const exportProgress = ref(0)
const exportStage = ref('')
const previewProgress = ref(0)
const previewStage = ref('')
const audioAssets = ref<any[]>([])
const selectedBgmAssetId = ref('')
const bgmUrl = ref('')
const bgmUploading = ref(false)
const bgmImporting = ref(false)
const recipes = ref<FinalCutRecipe[]>([])
const selectedRecipeId = ref('')
const recipeLoading = ref(false)
const ruleApplying = ref(false)
const aiPlanning = ref(false)
const aiPlanProgress = ref(0)
const aiPlanStage = ref('')
const aiInstruction = ref('')
const aiPlanNotes = ref<string[]>([])
const executionChanges = ref<string[]>([])

const plan = ref<EditPlan>({
  version: 1,
  settings: {
    transition: 'fade',
    burn_subtitles: true,
    subtitle_source: 'prompt',
    bgm_path: '',
    bgm_volume: 0.15,
    cover_title: '',
    cover_frame_sec: null,
  },
  clips: [],
})

const enabledClips = computed(() => plan.value.clips.filter((clip) => clip.enabled && clip.video_url))
const selectedClip = computed(() => {
  return plan.value.clips.find((clip) => clip.shot_index === selectedShot.value) || enabledClips.value[0] || plan.value.clips[0]
})
const estimatedDuration = computed(() => {
  return enabledClips.value.reduce((sum, clip) => {
    return sum + Math.max(0.1, Number(clip.duration || 0) - Number(clip.trim_start || 0) - Number(clip.trim_end || 0))
  }, 0)
})
const selectedRecipe = computed(() => {
  return recipes.value.find((item) => item.id === selectedRecipeId.value) || recipes.value[0]
})
const recipeGroups = computed(() => {
  const groups: Record<string, FinalCutRecipe[]> = {}
  for (const item of recipes.value) {
    const key = item.category || 'other'
    if (!groups[key]) groups[key] = []
    groups[key].push(item)
  }
  return groups
})

function mapProjects(data: any): ProjectOption[] {
  const rows = data?.items || data?.projects || data || []
  if (!Array.isArray(rows)) return []
  return rows
    .map((row: any) => ({
      project_id: String(row.project_id || row.id || ''),
      name: String(row.name || row.project_id || row.id || ''),
    }))
    .filter((row: ProjectOption) => row.project_id)
}

function normalizePlan(raw: any): EditPlan {
  const settings = {
    ...plan.value.settings,
    ...(raw?.settings || {}),
  }
  const clips = Array.isArray(raw?.clips)
    ? raw.clips.map((clip: any, idx: number) => ({
        shot_index: Number(clip.shot_index || idx + 1),
        order: Number(clip.order || idx + 1),
        enabled: clip.enabled !== false,
        video_url: String(clip.video_url || ''),
        prompt: String(clip.prompt || ''),
        duration: Number(clip.duration || 5),
        trim_start: Number(clip.trim_start || 0),
        trim_end: Number(clip.trim_end || 0),
        transition: String(clip.transition || settings.transition || 'fade'),
        subtitle: String(clip.subtitle || clip.prompt || ''),
      }))
    : []
  return { version: 1, settings, clips }
}

function reindex() {
  plan.value.clips = plan.value.clips.map((clip, idx) => ({ ...clip, order: idx + 1 }))
}

function selectClip(clip: EditClip) {
  selectedShot.value = clip.shot_index
}

function moveClip(index: number, direction: -1 | 1) {
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= plan.value.clips.length) return
  const next = [...plan.value.clips]
  const current = next[index]
  next[index] = next[nextIndex]
  next[nextIndex] = current
  plan.value.clips = next
  reindex()
}

function clampTrim(clip: EditClip) {
  const duration = Math.max(0.1, Number(clip.duration || 0))
  clip.trim_start = Math.max(0, Number(clip.trim_start || 0))
  clip.trim_end = Math.max(0, Number(clip.trim_end || 0))
  if (clip.trim_start + clip.trim_end >= duration) {
    clip.trim_end = Math.max(0, duration - clip.trim_start - 0.1)
  }
}

function effectiveDuration(clip: EditClip) {
  return Math.max(0.1, Number(clip.duration || 0) - Number(clip.trim_start || 0) - Number(clip.trim_end || 0))
}

function summarizeExecutionChanges(before: EditPlan, after: EditPlan): string[] {
  const beforeByShot = new Map(before.clips.map((clip) => [clip.shot_index, clip]))
  const changes: string[] = []
  for (const clip of after.clips) {
    const prev = beforeByShot.get(clip.shot_index)
    if (!prev) continue
    const itemChanges: string[] = []
    if (prev.order !== clip.order) itemChanges.push(`顺序 ${prev.order}→${clip.order}`)
    const prevDuration = effectiveDuration(prev)
    const nextDuration = effectiveDuration(clip)
    if (Math.abs(prevDuration - nextDuration) >= 0.05) {
      itemChanges.push(`片长 ${prevDuration.toFixed(1)}s→${nextDuration.toFixed(1)}s`)
    }
    if (prev.transition !== clip.transition) itemChanges.push(`转场 ${prev.transition}→${clip.transition}`)
    if (prev.enabled !== clip.enabled) itemChanges.push(clip.enabled ? '启用' : '禁用')
    if (itemChanges.length) changes.push(`#${clip.shot_index}：${itemChanges.join('，')}`)
  }
  return changes.length ? changes : ['剪辑方案已保存，但未产生可见参数变化。']
}

async function loadProjects() {
  const { data } = await listProjects()
  projects.value = mapProjects(data)
}

async function loadPlan() {
  if (!projectId.value) return
  loading.value = true
  error.value = ''
  finalUrl.value = ''
  previewUrl.value = ''
  try {
    const { data } = await getFinalEditPlan(projectId.value)
    plan.value = normalizePlan(data?.plan)
    selectedShot.value = plan.value.clips[0]?.shot_index ?? null
    await loadAudioAssets()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '加载剪辑方案失败'
    plan.value.clips = []
  } finally {
    loading.value = false
  }
}

async function loadAudioAssets() {
  if (!projectId.value) return
  const { data } = await listAssets(projectId.value, 'audio')
  audioAssets.value = Array.isArray(data?.items) ? data.items : []
  const match = audioAssets.value.find((asset) => {
    return asset.file_url === plan.value.settings.bgm_path || asset.file_path === plan.value.settings.bgm_path
  })
  selectedBgmAssetId.value = match?.asset_id || ''
}

async function loadRecipes() {
  recipeLoading.value = true
  try {
    const { data } = await getFinalCutRecipes()
    recipes.value = Array.isArray(data?.items) ? data.items : []
    if (!selectedRecipeId.value && recipes.value[0]) selectedRecipeId.value = recipes.value[0].id
  } catch {
    recipes.value = []
  } finally {
    recipeLoading.value = false
  }
}

async function savePlan() {
  if (!projectId.value) return
  saving.value = true
  error.value = ''
  try {
    reindex()
    const { data } = await saveFinalEditPlan(projectId.value, plan.value as unknown as Record<string, unknown>)
    plan.value = normalizePlan(data?.plan)
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '保存剪辑方案失败'
  } finally {
    saving.value = false
  }
}

async function applySelectedRecipeWithAi() {
  if (!projectId.value || !selectedRecipe.value) return
  aiPlanning.value = true
  aiPlanProgress.value = 0
  aiPlanStage.value = '提交 AI 剪辑规划任务'
  error.value = ''
  aiPlanNotes.value = []
  executionChanges.value = []
  try {
    const before = normalizePlan(plan.value)
    const { data } = await generateFinalCutPlanAi({
      project_id: projectId.value,
      recipe_id: selectedRecipe.value.id,
      instruction: aiInstruction.value.trim(),
    })
    if (!data?.task_id) throw new Error('AI 剪辑任务提交失败')
    trackAiPlan(data.task_id, before)
  } catch (err: any) {
    aiPlanning.value = false
    error.value = err?.response?.data?.detail || err?.message || 'AI 生成剪辑方案失败'
  }
}

function trackAiPlan(taskId: string, before: EditPlan) {
  const poller = useTaskPoller()
  poller.start(taskId)
  const timer = setInterval(() => {
    aiPlanProgress.value = Math.max(aiPlanProgress.value, Number(poller.progress.value || 0))
    if (poller.stageText.value) aiPlanStage.value = poller.stageText.value
    if (!poller.isPolling.value && poller.status.value) {
      clearInterval(timer)
      aiPlanning.value = false
      if (poller.status.value === 'done') {
        const data = poller.result.value || {}
        aiPlanProgress.value = 100
        aiPlanStage.value = 'AI 剪辑方案已写入'
        const nextPlan = normalizePlan(data?.plan)
        plan.value = nextPlan
        executionChanges.value = summarizeExecutionChanges(before, nextPlan)
        aiPlanNotes.value = [
          ...(Array.isArray(data?.explanation) ? data.explanation : []),
          ...(Array.isArray(data?.warnings) ? data.warnings.map((item: string) => `注意：${item}`) : []),
        ]
        if (data?.tokens_used) {
          aiPlanNotes.value.push(`本次 AI 规划消耗 ${data.tokens_used} tokens`)
        }
        return
      }
      error.value = poller.error.value || 'AI 生成剪辑方案失败'
    }
  }, 300)
}

async function applySelectedRecipeLocally() {
  if (!projectId.value || !selectedRecipe.value) return
  ruleApplying.value = true
  error.value = ''
  aiPlanNotes.value = []
  executionChanges.value = []
  try {
    const before = normalizePlan(plan.value)
    const { data } = await applyFinalCutRule({
      project_id: projectId.value,
      recipe_id: selectedRecipe.value.id,
    })
    const nextPlan = normalizePlan(data?.plan)
    plan.value = nextPlan
    executionChanges.value = summarizeExecutionChanges(before, nextPlan)
    aiPlanNotes.value = [
      ...(Array.isArray(data?.explanation) ? data.explanation : []),
      ...(Array.isArray(data?.warnings) ? data.warnings.map((item: string) => `注意：${item}`) : []),
    ]
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '应用剪辑规则失败'
  } finally {
    ruleApplying.value = false
  }
}

function applyBgmAsset() {
  const asset = audioAssets.value.find((item) => item.asset_id === selectedBgmAssetId.value)
  if (!asset) {
    plan.value.settings.bgm_path = ''
    return
  }
  plan.value.settings.bgm_path = asset.file_url || asset.file_path || ''
}

async function uploadBgm(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !projectId.value) return
  bgmUploading.value = true
  error.value = ''
  try {
    const { data } = await uploadAssetFile(projectId.value, file, 'audio', { role: 'bgm' })
    await loadAudioAssets()
    selectedBgmAssetId.value = data?.asset_id || data?.id || ''
    applyBgmAsset()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || 'BGM 上传失败'
  } finally {
    bgmUploading.value = false
    input.value = ''
  }
}

async function importBgmUrl() {
  if (!projectId.value || !bgmUrl.value.trim()) return
  bgmImporting.value = true
  error.value = ''
  try {
    const { data } = await importAssetUrl(projectId.value, {
      url: bgmUrl.value.trim(),
      asset_type: 'audio',
      metadata: { role: 'bgm' },
    })
    bgmUrl.value = ''
    await loadAudioAssets()
    selectedBgmAssetId.value = data?.asset_id || data?.id || ''
    applyBgmAsset()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || 'BGM URL 导入失败'
  } finally {
    bgmImporting.value = false
  }
}

function trackExport(taskId: string) {
  const poller = useTaskPoller()
  poller.start(taskId)
  const timer = setInterval(() => {
    exportProgress.value = Math.max(exportProgress.value, Number(poller.progress.value || 0))
    if (poller.stageText.value) exportStage.value = poller.stageText.value
    if (!poller.isPolling.value && poller.status.value) {
      clearInterval(timer)
      exporting.value = false
      if (poller.status.value === 'done' && poller.result.value?.final_url) {
        finalUrl.value = poller.result.value.final_url
        exportProgress.value = 100
        exportStage.value = '导出完成'
      } else {
        error.value = '导出失败，请在任务详情查看原因'
      }
    }
  }, 300)
}

function trackPreview(taskId: string) {
  const poller = useTaskPoller()
  poller.start(taskId)
  const timer = setInterval(() => {
    previewProgress.value = Math.max(previewProgress.value, Number(poller.progress.value || 0))
    if (poller.stageText.value) previewStage.value = poller.stageText.value
    if (!poller.isPolling.value && poller.status.value) {
      clearInterval(timer)
      previewing.value = false
      const url = poller.result.value?.preview_url || poller.result.value?.final_url
      if (poller.status.value === 'done' && url) {
        previewUrl.value = url
        previewProgress.value = 100
        previewStage.value = '预览生成完成'
      } else {
        error.value = '预览生成失败，请在任务详情查看原因'
      }
    }
  }, 300)
}

async function exportPreview() {
  if (!projectId.value || !enabledClips.value.length) return
  previewing.value = true
  error.value = ''
  previewUrl.value = ''
  previewProgress.value = 0
  previewStage.value = '提交预览任务'
  try {
    await savePlan()
    const { data } = await directorExportPreview({
      project_id: projectId.value,
      edit_plan: plan.value as unknown as Record<string, unknown>,
    })
    trackPreview(data.task_id)
  } catch (err: any) {
    previewing.value = false
    error.value = err?.response?.data?.detail || err?.message || '预览提交失败'
  }
}

async function exportFinal() {
  if (!projectId.value || !enabledClips.value.length) return
  exporting.value = true
  error.value = ''
  finalUrl.value = ''
  exportProgress.value = 0
  exportStage.value = '提交导出任务'
  try {
    await savePlan()
    const { data } = await directorExportFinal({
      project_id: projectId.value,
      edit_plan: plan.value as unknown as Record<string, unknown>,
    })
    trackExport(data.task_id)
  } catch (err: any) {
    exporting.value = false
    error.value = err?.response?.data?.detail || err?.message || '导出提交失败'
  }
}

onMounted(async () => {
  const routeProject = route.params.projectId
  if (typeof routeProject === 'string') projectId.value = routeProject
  await Promise.all([loadProjects(), loadRecipes()])
  if (!projectId.value && projects.value[0]) projectId.value = projects.value[0].project_id
  await loadPlan()
})

watch(projectId, () => {
  void loadPlan()
})
</script>

<template>
  <main class="final-cut-page">
    <header class="cut-header">
      <div>
        <p class="kicker">Final Cut</p>
        <h2>最终成片工作台</h2>
      </div>
      <div class="project-tools">
        <select v-model="projectId" class="project-select">
          <option value="">选择项目</option>
          <option v-for="item in projects" :key="item.project_id" :value="item.project_id">
            {{ item.name }} / {{ item.project_id }}
          </option>
        </select>
        <input v-model.trim="projectId" class="project-id" placeholder="project_id" />
        <button class="btn" type="button" :disabled="loading" @click="loadPlan">刷新</button>
        <button class="btn" type="button" :disabled="saving || !projectId" @click="savePlan">
          {{ saving ? '保存中' : '保存方案' }}
        </button>
        <button class="btn" type="button" :disabled="previewing || !enabledClips.length" @click="exportPreview">
          {{ previewing ? '预览生成中' : '生成预览小样' }}
        </button>
        <button class="btn btn-primary" type="button" :disabled="exporting || !enabledClips.length" @click="exportFinal">
          {{ exporting ? '导出中' : '导出成片' }}
        </button>
      </div>
    </header>

    <section class="summary-strip">
      <div><strong>{{ plan.clips.length }}</strong><span>镜头总数</span></div>
      <div><strong>{{ enabledClips.length }}</strong><span>进入成片</span></div>
      <div><strong>{{ estimatedDuration.toFixed(1) }}s</strong><span>预计片长</span></div>
      <div><strong>{{ plan.settings.burn_subtitles ? '开' : '关' }}</strong><span>字幕烧录</span></div>
    </section>

    <section v-if="recipes.length" class="recipe-panel">
      <div class="panel-title">
        <h3>剪辑思维库</h3>
        <span>{{ recipeLoading ? '加载中' : `${recipes.length} 条可复用规则` }}</span>
      </div>
      <div class="recipe-layout">
        <div class="recipe-list">
          <template v-for="(items, category) in recipeGroups" :key="category">
            <p class="recipe-category">{{ category }}</p>
            <button
              v-for="item in items"
              :key="item.id"
              type="button"
              class="recipe-item"
              :class="{ active: selectedRecipe?.id === item.id }"
              @click="selectedRecipeId = item.id"
            >
              <strong>{{ item.name }}</strong>
              <span>{{ item.ffmpeg_feasibility }}</span>
            </button>
          </template>
        </div>
        <article v-if="selectedRecipe" class="recipe-detail">
          <div class="recipe-detail-head">
            <div>
              <h3>{{ selectedRecipe.name }}</h3>
              <p>{{ selectedRecipe.summary }}</p>
            </div>
            <span>{{ selectedRecipe.difficulty }}</span>
          </div>
          <div class="recipe-tags">
            <span>商业价值：{{ selectedRecipe.commercial_value || 'medium' }}</span>
            <span>执行方式：{{ selectedRecipe.ffmpeg_feasibility }}</span>
            <span v-if="selectedRecipe.needs_ai?.length">AI：{{ selectedRecipe.needs_ai.join(' / ') }}</span>
          </div>
          <ol v-if="selectedRecipe.steps?.length" class="recipe-lines">
            <li v-for="step in selectedRecipe.steps.slice(0, 6)" :key="step">{{ step }}</li>
          </ol>
          <ul v-else-if="selectedRecipe.rules?.length" class="recipe-lines">
            <li v-for="rule in selectedRecipe.rules.slice(0, 6)" :key="rule">{{ rule }}</li>
          </ul>
          <ol v-else-if="selectedRecipe.formula?.length" class="recipe-lines">
            <li v-for="line in selectedRecipe.formula.slice(0, 6)" :key="line">{{ line }}</li>
          </ol>
          <div class="ai-plan-box">
            <textarea
              v-model.trim="aiInstruction"
              rows="3"
              placeholder="可选：补充剪辑要求，例如更偏高级感、保留结尾长镜头、不要大幅裁剪人物台词。"
            />
            <div class="recipe-actions">
              <button
                class="btn"
                type="button"
                :disabled="ruleApplying || aiPlanning || !projectId || !enabledClips.length"
                @click="applySelectedRecipeLocally"
              >
                {{ ruleApplying ? '应用中' : '本地应用规则' }}
              </button>
              <button
                class="btn btn-primary"
                type="button"
                :disabled="aiPlanning || ruleApplying || !projectId || !enabledClips.length"
                @click="applySelectedRecipeWithAi"
              >
                {{ aiPlanning ? 'AI 生成中' : 'AI 应用到剪辑方案' }}
              </button>
            </div>
            <section v-if="aiPlanning || aiPlanStage" class="ai-task-status">
              <div class="status-row">
                <span>{{ aiPlanning ? 'AI 剪辑规划' : 'AI 剪辑规划完成' }}</span>
                <span>{{ aiPlanProgress }}%</span>
              </div>
              <div class="progress-bar"><div :style="{ width: `${aiPlanProgress}%` }"></div></div>
              <p>{{ aiPlanStage }}</p>
            </section>
            <div v-if="executionChanges.length" class="execution-box">
              <strong>FFmpeg 可执行变化</strong>
              <ul>
                <li v-for="change in executionChanges" :key="change">{{ change }}</li>
              </ul>
            </div>
            <ul v-if="aiPlanNotes.length" class="ai-plan-notes">
              <li v-for="note in aiPlanNotes" :key="note">{{ note }}</li>
            </ul>
          </div>
        </article>
      </div>
    </section>

    <p v-if="error" class="error-line">{{ error }}</p>

    <div class="cut-layout">
      <section class="timeline-panel">
        <div class="panel-title">
          <h3>镜头编排</h3>
          <span>{{ loading ? '加载中' : '可调整顺序、裁剪和转场' }}</span>
        </div>

        <div v-if="!plan.clips.length" class="empty-state">
          当前项目还没有可导出的分镜视频。
        </div>

        <article
          v-for="(clip, index) in plan.clips"
          :key="clip.shot_index"
          class="clip-row"
          :class="{ selected: selectedClip?.shot_index === clip.shot_index, disabled: !clip.enabled }"
          @click="selectClip(clip)"
        >
          <label class="clip-check">
            <input v-model="clip.enabled" type="checkbox" />
          </label>
          <video :src="clip.video_url" preload="metadata" muted></video>
          <div class="clip-main">
            <div class="clip-head">
              <strong>#{{ clip.shot_index }}</strong>
              <span>{{ Math.max(0.1, clip.duration - clip.trim_start - clip.trim_end).toFixed(1) }}s</span>
            </div>
            <p>{{ clip.prompt || '未填写分镜提示词' }}</p>
            <div class="clip-fields">
              <label>开头裁掉<input v-model.number="clip.trim_start" min="0" step="0.1" type="number" @change="clampTrim(clip)" /></label>
              <label>结尾裁掉<input v-model.number="clip.trim_end" min="0" step="0.1" type="number" @change="clampTrim(clip)" /></label>
              <label>转场
                <select v-model="clip.transition">
                  <option value="cut">硬切</option>
                  <option value="fade">淡入淡出</option>
                  <option value="dissolve">溶解</option>
                </select>
              </label>
            </div>
          </div>
          <div class="clip-order">
            <button type="button" :disabled="index === 0" @click.stop="moveClip(index, -1)">↑</button>
            <button type="button" :disabled="index === plan.clips.length - 1" @click.stop="moveClip(index, 1)">↓</button>
          </div>
        </article>
      </section>

      <aside class="preview-panel">
        <div class="preview-box">
          <video v-if="previewUrl" :src="previewUrl" controls preload="metadata"></video>
          <video v-else-if="selectedClip?.video_url" :src="selectedClip.video_url" controls preload="metadata"></video>
          <div v-else class="empty-state">选择一个镜头预览</div>
        </div>

        <section v-if="previewing || previewUrl" class="export-status">
          <div class="export-head">
            <strong>预览小样</strong>
            <span>{{ previewProgress }}%</span>
          </div>
          <div class="progress-bar"><div :style="{ width: `${previewProgress}%` }"></div></div>
          <p>{{ previewStage }}</p>
          <a v-if="previewUrl" :href="previewUrl" target="_blank" rel="noopener">打开预览小样</a>
        </section>

        <section class="settings-panel">
          <h3>成片设置</h3>
          <label class="toggle-line">
            <input v-model="plan.settings.burn_subtitles" type="checkbox" />
            <span>导出时烧录字幕</span>
          </label>
          <label>
            默认转场
            <select v-model="plan.settings.transition">
              <option value="cut">硬切</option>
              <option value="fade">淡入淡出</option>
              <option value="dissolve">溶解</option>
            </select>
          </label>
          <div class="bgm-tools">
            <label>
              BGM 素材
              <select v-model="selectedBgmAssetId" @change="applyBgmAsset">
                <option value="">不使用 BGM</option>
                <option v-for="asset in audioAssets" :key="asset.asset_id" :value="asset.asset_id">
                  {{ asset.filename || asset.metadata?.filename || asset.asset_id }}
                </option>
              </select>
            </label>
            <label>
              BGM 音量
              <input v-model.number="plan.settings.bgm_volume" type="range" min="0" max="1" step="0.01" />
            </label>
            <div class="bgm-actions">
              <label class="file-button">
                {{ bgmUploading ? '上传中' : '上传音乐' }}
                <input accept="audio/*" type="file" :disabled="bgmUploading" @change="uploadBgm" />
              </label>
              <div class="url-import">
                <input v-model.trim="bgmUrl" placeholder="https://.../music.mp3" />
                <button type="button" :disabled="bgmImporting || !bgmUrl" @click="importBgmUrl">
                  {{ bgmImporting ? '导入中' : 'URL 导入' }}
                </button>
              </div>
            </div>
            <audio v-if="plan.settings.bgm_path" :src="plan.settings.bgm_path" controls preload="metadata"></audio>
          </div>
          <label>
            封面标题
            <input v-model.trim="plan.settings.cover_title" placeholder="用于后续封面生成" />
          </label>
          <label>
            当前镜头字幕
            <textarea v-if="selectedClip" v-model="selectedClip.subtitle" rows="4" />
          </label>
        </section>

        <section v-if="exporting || finalUrl" class="export-status">
          <div class="export-head">
            <strong>导出任务</strong>
            <span>{{ exportProgress }}%</span>
          </div>
          <div class="progress-bar"><div :style="{ width: `${exportProgress}%` }"></div></div>
          <p>{{ exportStage }}</p>
          <a v-if="finalUrl" :href="finalUrl" target="_blank" rel="noopener">打开最终成片</a>
        </section>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.final-cut-page {
  max-width: 1680px;
  margin: 0 auto;
  padding: 1.25rem;
}

.cut-header,
.summary-strip,
.recipe-panel,
.timeline-panel,
.preview-panel,
.settings-panel,
.export-status {
  border: 1px solid var(--color-border);
  background: var(--color-bg);
  border-radius: var(--radius-md);
}

.cut-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  margin-bottom: 1rem;
}

.kicker {
  margin: 0 0 0.25rem;
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

h2,
h3,
p {
  margin: 0;
}

.project-tools {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.project-select,
.project-id,
.settings-panel input,
.settings-panel select,
.settings-panel textarea,
.clip-fields input,
.clip-fields select {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  color: var(--color-text);
}

.project-select {
  width: 260px;
  height: 36px;
}

.project-id {
  width: 180px;
  height: 36px;
  padding: 0 0.65rem;
}

.btn {
  height: 36px;
  padding: 0 0.85rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  cursor: pointer;
}

.btn-primary {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: white;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  overflow: hidden;
  margin-bottom: 1rem;
}

.summary-strip div {
  padding: 0.85rem 1rem;
  background: var(--color-bg-secondary);
}

.summary-strip strong {
  display: block;
  font-size: 1.1rem;
}

.summary-strip span,
.panel-title span,
.clip-head span,
.export-status p {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.recipe-panel {
  padding: 1rem;
  margin-bottom: 1rem;
}

.recipe-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 1rem;
}

.recipe-list {
  max-height: 360px;
  overflow: auto;
  padding-right: 0.25rem;
}

.recipe-category {
  margin: 0.5rem 0 0.35rem;
  color: var(--color-text-secondary);
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
}

.recipe-item {
  width: 100%;
  display: grid;
  gap: 0.2rem;
  text-align: left;
  padding: 0.7rem;
  margin-bottom: 0.45rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  cursor: pointer;
}

.recipe-item.active {
  border-color: var(--color-primary);
}

.recipe-item span,
.recipe-tags span {
  color: var(--color-text-secondary);
  font-size: 0.76rem;
}

.recipe-detail {
  min-height: 240px;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
}

.recipe-detail-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.7rem;
}

.recipe-detail-head p {
  margin-top: 0.35rem;
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.recipe-detail-head > span {
  height: 28px;
  padding: 0 0.6rem;
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.recipe-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.75rem;
}

.recipe-tags span {
  padding: 0.28rem 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
}

.recipe-lines {
  margin: 0;
  padding-left: 1.2rem;
  color: var(--color-text);
  line-height: 1.65;
}

.ai-plan-box {
  display: grid;
  gap: 0.6rem;
  margin-top: 0.9rem;
  padding-top: 0.9rem;
  border-top: 1px solid var(--color-border);
}

.ai-plan-box textarea {
  width: 100%;
  min-height: 78px;
  resize: vertical;
  padding: 0.65rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--color-text);
}

.recipe-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.execution-box {
  padding: 0.7rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
}

.ai-task-status {
  padding: 0.7rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
}

.ai-task-status p {
  margin-top: 0.45rem;
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.status-row {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.45rem;
  color: var(--color-text);
  font-size: 0.82rem;
  font-weight: 600;
}

.execution-box strong {
  display: block;
  margin-bottom: 0.4rem;
  font-size: 0.86rem;
}

.execution-box ul {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--color-text);
  line-height: 1.55;
  font-size: 0.82rem;
}

.ai-plan-notes {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--color-text-secondary);
  line-height: 1.55;
  font-size: 0.82rem;
}

.cut-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(360px, 0.8fr);
  gap: 1rem;
}

.timeline-panel,
.preview-panel {
  padding: 1rem;
}

.panel-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 0.8rem;
}

.clip-row {
  display: grid;
  grid-template-columns: 32px 152px minmax(0, 1fr) 38px;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  margin-bottom: 0.65rem;
  cursor: pointer;
}

.clip-row.selected {
  border-color: var(--color-primary);
}

.clip-row.disabled {
  opacity: 0.55;
}

.clip-row video {
  width: 152px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  background: black;
  border-radius: var(--radius-sm);
}

.clip-check {
  display: flex;
  justify-content: center;
}

.clip-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.25rem;
}

.clip-main p {
  color: var(--color-text);
  line-height: 1.45;
  margin-bottom: 0.55rem;
}

.clip-fields {
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 0.5rem;
}

.clip-fields label,
.settings-panel label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  color: var(--color-text-secondary);
  font-size: 0.78rem;
}

.clip-fields input,
.clip-fields select,
.settings-panel input,
.settings-panel select {
  height: 34px;
  padding: 0 0.55rem;
}

.clip-order {
  display: grid;
  gap: 0.35rem;
}

.clip-order button {
  height: 28px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--color-text);
}

.preview-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.preview-box {
  background: #080808;
  border-radius: var(--radius-sm);
  overflow: hidden;
  min-height: 260px;
  display: grid;
  place-items: center;
}

.preview-box video {
  width: 100%;
  max-height: 520px;
  background: black;
}

.settings-panel,
.export-status {
  padding: 1rem;
}

.settings-panel {
  display: grid;
  gap: 0.75rem;
}

.settings-panel textarea {
  resize: vertical;
  min-height: 96px;
  padding: 0.6rem;
}

.bgm-tools {
  display: grid;
  gap: 0.65rem;
}

.bgm-actions {
  display: grid;
  grid-template-columns: 116px minmax(0, 1fr);
  gap: 0.55rem;
}

.file-button {
  height: 34px;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  color: var(--color-text) !important;
  cursor: pointer;
}

.file-button input {
  display: none;
}

.url-import {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 84px;
  gap: 0.45rem;
}

.url-import button {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  color: var(--color-text);
}

.bgm-tools audio {
  width: 100%;
  height: 36px;
}

.toggle-line {
  flex-direction: row !important;
  align-items: center;
}

.export-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.progress-bar {
  height: 8px;
  border-radius: 99px;
  overflow: hidden;
  background: var(--color-bg-secondary);
}

.progress-bar div {
  height: 100%;
  background: var(--color-primary);
}

.export-status a {
  display: inline-block;
  margin-top: 0.5rem;
  color: var(--color-primary);
}

.empty-state,
.error-line {
  padding: 1rem;
  color: var(--color-text-secondary);
}

.error-line {
  border: 1px solid color-mix(in srgb, var(--color-danger) 60%, var(--color-border));
  border-radius: var(--radius-sm);
  margin-bottom: 1rem;
  color: var(--color-danger);
}

@media (max-width: 1180px) {
  .cut-header,
  .cut-layout {
    grid-template-columns: 1fr;
  }

  .cut-header {
    align-items: stretch;
    flex-direction: column;
  }

  .summary-strip {
    grid-template-columns: repeat(2, 1fr);
  }

  .recipe-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .clip-row {
    grid-template-columns: 28px 96px minmax(0, 1fr);
  }

  .clip-row video {
    width: 96px;
  }

  .clip-order {
    grid-column: 2 / -1;
    grid-template-columns: repeat(2, 1fr);
  }

  .clip-fields {
    grid-template-columns: 1fr;
  }
}
</style>
