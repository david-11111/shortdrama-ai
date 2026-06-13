<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import client from '@/api/client'
import {
  batchGenerateImages,
  batchGenerateVideos,
  createAsset,
  deleteAsset,
  getProject,
  listAssets,
  listShotRows,
  updateShotRow,
  uploadAssetFile,
} from '@/api/workbench'
import { useWebSocket } from '@/composables/useWebSocket'
import AssetPanel from './AssetPanel.vue'
import BatchActions from './BatchActions.vue'
import RefSelector from './RefSelector.vue'
import ShotTable from './ShotTable.vue'

interface ShotRow {
  shot_index: number
  prompt: string
  duration: number
  status: string
  image_candidates?: Array<string | { url?: string; image_url?: string; video_url?: string }>
  video_variants?: Array<string | { url?: string; image_url?: string; video_url?: string }>
  selected_image?: string | null
  selected_video?: string | null
  selected: boolean
  character_refs?: string[]
  scene_refs?: string[]
  prop_refs?: string[]
  costume_refs?: string[]
  style_refs?: string[]
  last_error?: string
}

interface Asset {
  id: string
  asset_type: string
  file_url?: string
  filename?: string
  status?: string
  metadata?: Record<string, unknown>
}

interface CreditsSummary {
  balance: number
}

interface CreditPricingRow {
  operation: string
  credits_cost: number
}

const route = useRoute()
const projectId = computed(() => route.params.projectId as string)

const projectName = ref('')
const rows = ref<ShotRow[]>([])
const assets = ref<Asset[]>([])
const loadingRows = ref(true)
const loadingAssets = ref(true)
const drawerOpen = ref(false)
const taskProgress = ref('')
const refSelectorVisible = ref(false)
const refTargetIdx = ref<number>(0)
const pricingMap = ref<Record<string, number> | null>(null)

const { connected, connect, on } = useWebSocket()

const selectedRows = computed(() => rows.value.filter((r) => r.selected))
const currentRefRow = computed(() => rows.value.find((r) => r.shot_index === refTargetIdx.value))

onMounted(async () => {
  await Promise.all([fetchProject(), fetchRows(), fetchAssets()])
  connect()
  on('task_update', handleTaskUpdate)
  on('task_complete', handleTaskComplete)
  on('task_failed', handleTaskFailed)
})

async function fetchProject() {
  try {
    const { data } = await getProject(projectId.value)
    projectName.value = data.name || projectId.value
  } catch {
    projectName.value = projectId.value
  }
}

async function fetchRows() {
  loadingRows.value = true
  try {
    const { data } = await listShotRows(projectId.value)
    const rawRows = Array.isArray(data) ? data : (data?.items ?? [])
    rows.value = (rawRows as Array<Record<string, unknown>>).map((raw) => ({
      shot_index: Number(raw.shot_index),
      prompt: String(raw.prompt ?? ''),
      duration: Number(raw.duration ?? 5),
      status: String(raw.status ?? 'draft'),
      image_candidates: (raw.image_candidates ?? raw.image_candidates_json ?? []) as string[],
      video_variants: (raw.video_variants ?? raw.video_variants_json ?? []) as string[],
      selected_image: (raw.selected_image ?? null) as string | null,
      selected_video: (raw.selected_video ?? null) as string | null,
      selected: Boolean(raw.selected),
      character_refs: (raw.character_refs ?? raw.character_refs_json ?? []) as string[],
      scene_refs: (raw.scene_refs ?? raw.scene_refs_json ?? []) as string[],
      prop_refs: (raw.prop_refs ?? raw.prop_refs_json ?? []) as string[],
      costume_refs: (raw.costume_refs ?? raw.costume_refs_json ?? []) as string[],
      style_refs: (raw.style_refs ?? raw.style_refs_json ?? []) as string[],
      last_error: String(raw.last_error ?? ''),
    }))
  } finally {
    loadingRows.value = false
  }
}

async function fetchAssets() {
  loadingAssets.value = true
  try {
    const { data } = await listAssets(projectId.value)
    const rawAssets = Array.isArray(data) ? data : (data?.items ?? [])
    assets.value = (rawAssets as Array<Record<string, unknown>>).map((raw) => ({
      id: String(raw.id ?? raw.asset_id ?? ''),
      asset_type: String(raw.asset_type ?? 'generic'),
      file_url: (raw.file_url ?? undefined) as string | undefined,
      filename: (raw.filename ?? undefined) as string | undefined,
      status: (raw.status ?? undefined) as string | undefined,
      metadata: ((raw.metadata ?? raw.metadata_json ?? {}) as Record<string, unknown>),
    }))
  } finally {
    loadingAssets.value = false
  }
}

function handleTaskUpdate(msg: { task_id: string; progress?: number; message?: string }) {
  taskProgress.value = msg.message || `Progress: ${msg.progress ?? 0}%`
  if (msg.progress !== undefined) {
    const row = rows.value.find((r) => r.status.startsWith('generating'))
    if (row && msg.progress >= 100) void fetchRows()
  }
}

function handleTaskComplete(_msg: unknown) {
  taskProgress.value = 'Task completed.'
  void fetchRows()
}

function handleTaskFailed(msg: { error?: string }) {
  taskProgress.value = `Task failed: ${msg.error || 'unknown error'}`
  void fetchRows()
}

async function onUpdateRow(idx: number, data: Partial<ShotRow>) {
  await updateShotRow(projectId.value, idx, data)
  const row = rows.value.find((r) => r.shot_index === idx)
  if (row) Object.assign(row, data)
}

function onToggleSelect(idx: number, val: boolean) {
  const row = rows.value.find((r) => r.shot_index === idx)
  if (row) row.selected = val
}

function onSelectAll(val: boolean) {
  rows.value.forEach((r) => { r.selected = val })
}

function onOpenRefs(idx: number) {
  refTargetIdx.value = idx
  refSelectorVisible.value = true
}

async function onSaveRefs(refs: { character_refs: string[]; scene_refs: string[]; prop_refs: string[]; costume_refs: string[]; style_refs: string[] }) {
  await updateShotRow(projectId.value, refTargetIdx.value, refs)
  const row = rows.value.find((r) => r.shot_index === refTargetIdx.value)
  if (row) Object.assign(row, refs)
}

async function onUploadAsset(file: File, assetType: string) {
  try {
    await uploadAssetFile(projectId.value, file, assetType, {
      filename: file.name,
      size: file.size,
      mime: file.type || 'application/octet-stream',
    })
  } catch (err: any) {
    const status = Number(err?.response?.status ?? 0)
    // Fallback for environments that have not enabled streaming upload endpoint yet.
    if (status === 404 || status === 405) {
      const blobUrl = URL.createObjectURL(file)
      await createAsset(projectId.value, {
        asset_type: assetType,
        file_url: blobUrl,
        filename: file.name,
        metadata: {
          upload_mode: 'blob_url_fallback',
          size: file.size,
          mime: file.type || 'application/octet-stream',
        },
      })
      taskProgress.value = 'Streaming upload endpoint not enabled; used local blob URL fallback.'
    } else {
      throw err
    }
  }
  await fetchAssets()
}

async function onDeleteAsset(assetId: string) {
  const confirmed = window.confirm('Confirm deleting this asset? This action cannot be undone.')
  if (!confirmed) return
  await deleteAsset(projectId.value, assetId)
  assets.value = assets.value.filter((a) => a.id !== assetId)
}

function onAssetSelect(_asset: Asset) {
  const selected = rows.value.filter((r) => r.selected)
  if (selected.length === 0) return
  refTargetIdx.value = selected[0].shot_index
  refSelectorVisible.value = true
}

async function ensurePricingMap() {
  if (pricingMap.value) return pricingMap.value
  const { data } = await client.get<{ pricing: CreditPricingRow[] }>('/credits/pricing')
  const map: Record<string, number> = {}
  for (const item of data.pricing || []) {
    if (item.operation && Number.isFinite(item.credits_cost)) {
      map[item.operation] = Number(item.credits_cost)
    }
  }
  pricingMap.value = map
  return map
}

function resolveUnitCost(kind: 'image' | 'video', map: Record<string, number>) {
  if (kind === 'image') return map.image_gen ?? 5
  return map.video_gen_5s ?? map.video_gen ?? 10
}

async function precheckCredits(kind: 'image' | 'video', count: number) {
  try {
    const [creditsRes, pricing] = await Promise.all([
      client.get<CreditsSummary>('/credits'),
      ensurePricingMap(),
    ])
    const unitCost = resolveUnitCost(kind, pricing)
    const required = unitCost * count
    const balance = Number(creditsRes.data.balance ?? 0)
    if (balance < required) {
      taskProgress.value = `Insufficient credits: need ${required}, current ${balance}.`
      return false
    }
    return true
  } catch {
    taskProgress.value = 'Credit precheck failed. Please retry.'
    return false
  }
}

async function onGenerateImages() {
  const items = selectedRows.value
    .filter((r) => r.status === 'ready')
    .map((r) => ({ shot_row: r }))
  if (!items.length) return

  const enough = await precheckCredits('image', items.length)
  if (!enough) return

  const { data } = await batchGenerateImages({ items })
  taskProgress.value = `Image batch submitted: ${data.task_id || ''}`
  items.forEach((item) => {
    const row = rows.value.find((r) => r.shot_index === (item.shot_row as ShotRow).shot_index)
    if (row) row.status = 'generating_image'
  })
}

async function onGenerateVideos() {
  const items = selectedRows.value
    .filter((r) => r.status === 'image_done' && r.selected_image)
    .map((r) => ({ shot_row: r }))
  if (!items.length) return

  const enough = await precheckCredits('video', items.length)
  if (!enough) return

  const { data } = await batchGenerateVideos({ items })
  taskProgress.value = `Video batch submitted: ${data.task_id || ''}`
  items.forEach((item) => {
    const row = rows.value.find((r) => r.shot_index === (item.shot_row as ShotRow).shot_index)
    if (row) row.status = 'generating_video'
  })
}
</script>

<template>
  <div class="workbench">
    <header class="wb-header">
      <h2>{{ projectName }}</h2>
      <BatchActions
        :selected-rows="selectedRows"
        @generate-images="onGenerateImages"
        @generate-videos="onGenerateVideos"
      />
    </header>

    <div class="wb-body">
      <div class="wb-aside" :class="{ open: drawerOpen }">
        <button class="drawer-toggle" @click="drawerOpen = !drawerOpen">
          {{ drawerOpen ? 'Hide' : 'Assets' }}
        </button>
        <AssetPanel
          :assets="assets"
          :loading="loadingAssets"
          @upload="onUploadAsset"
          @delete="onDeleteAsset"
          @select="onAssetSelect"
        />
      </div>

      <main class="wb-main">
        <div v-if="loadingRows" class="loading">Loading shot rows...</div>
        <ShotTable
          v-else
          :rows="rows"
          @update-row="onUpdateRow"
          @open-refs="onOpenRefs"
          @toggle-select="onToggleSelect"
          @select-all="onSelectAll"
        />
      </main>
    </div>

    <footer class="wb-footer">
      <span class="ws-status" :class="{ online: connected }">
        {{ connected ? 'WS connected' : 'WS disconnected' }}
      </span>
      <span v-if="taskProgress" class="task-progress">{{ taskProgress }}</span>
    </footer>

    <RefSelector
      :visible="refSelectorVisible"
      :assets="assets"
      :character-refs="currentRefRow?.character_refs || []"
      :scene-refs="currentRefRow?.scene_refs || []"
      :prop-refs="currentRefRow?.prop_refs || []"
      :costume-refs="currentRefRow?.costume_refs || []"
      :style-refs="currentRefRow?.style_refs || []"
      @update:visible="refSelectorVisible = $event"
      @save="onSaveRefs"
    />
  </div>
</template>

<style scoped>
.workbench {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--color-bg);
}

.wb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
}

.wb-header h2 { margin: 0; font-size: 18px; }

.wb-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.wb-aside {
  width: 30%;
  min-width: 240px;
  max-width: 360px;
  display: flex;
  flex-direction: column;
}

.wb-main {
  flex: 1;
  overflow: auto;
}

.loading {
  padding: var(--space-xl);
  text-align: center;
  color: var(--color-text-secondary);
}

.wb-footer {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-xs) var(--space-md);
  border-top: 1px solid var(--color-border);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.ws-status::before {
  content: '';
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  background: var(--color-error);
}

.ws-status.online::before {
  background: var(--color-success);
}

.drawer-toggle {
  display: none;
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  cursor: pointer;
  font-size: 12px;
  position: absolute;
  top: var(--space-sm);
  left: var(--space-sm);
  z-index: 10;
}

@media (max-width: 768px) {
  .wb-aside {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    width: 80%;
    max-width: 320px;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform 0.25s;
    background: var(--color-bg);
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.1);
  }

  .wb-aside.open {
    transform: translateX(0);
  }

  .drawer-toggle {
    display: block;
  }

  .wb-main {
    width: 100%;
  }
}
</style>
