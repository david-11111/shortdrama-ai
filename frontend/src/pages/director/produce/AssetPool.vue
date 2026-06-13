<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { deleteAsset, listAssets, updateShotRow, uploadAssetFile } from '@/api/workbench'

interface AssetItem {
  id: string
  file_url: string
  asset_type: string
  metadata?: Record<string, any>
}

const session = inject<any>('session')
const assets = ref<AssetItem[]>([])
const dragOver = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const bindShotIndex = ref<number | null>(null)
const assetKind = ref('character')

const shotOptions = computed(() => {
  const rows = session.shots.value || []
  return rows.map((shot: any) => Number(shot.index)).filter((n: number) => Number.isFinite(n) && n > 0)
})

async function loadAssets() {
  if (!session.projectId.value) return
  try {
    const { data } = await listAssets(session.projectId.value)
    const rows = data?.items || data?.assets || data || []
    assets.value = rows.map((item: any) => ({
      id: String(item.asset_id || item.id || ''),
      file_url: String(item.file_url || ''),
      asset_type: String(item.asset_type || 'image'),
      metadata: item.metadata_json || item.metadata || {},
    }))
  } catch {
    assets.value = []
  }
}

async function uploadFiles(files: FileList | File[]) {
  if (!files.length || !session.projectId.value) return
  uploading.value = true
  uploadProgress.value = 0
  session.beginTask()
  try {
    const list = Array.from(files)
    for (let i = 0; i < list.length; i++) {
      const file = list[i]
      await uploadAssetFile(
        session.projectId.value,
        file,
        'image',
        {
          asset_kind: assetKind.value,
          entity_type: assetKind.value,
          lineage_role: ['character', 'scene', 'prop', 'costume', 'style'].includes(assetKind.value) ? 'source' : 'derived',
          generation_method: 'upload',
          filename: file.name,
        },
        (event) => {
          const current = event.total ? Math.round((event.loaded / event.total) * 100) : 0
          const global = Math.round(((i + current / 100) / list.length) * 100)
          uploadProgress.value = global
        },
      )
    }
    await loadAssets()
  } finally {
    uploading.value = false
    session.endTask()
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  void uploadFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  dragOver.value = false
  if (!event.dataTransfer?.files?.length) return
  void uploadFiles(event.dataTransfer.files)
}

async function removeAsset(assetId: string) {
  if (!session.projectId.value) return
  if (!confirm('确认删除这个素材吗？')) return
  await deleteAsset(session.projectId.value, assetId)
  await loadAssets()
}

function refFieldForKind(kind: string) {
  if (kind === 'character') return 'character_refs'
  if (kind === 'costume') return 'costume_refs'
  if (kind === 'scene') return 'scene_refs'
  if (kind === 'prop') return 'prop_refs'
  if (kind === 'style') return 'style_refs'
  return ''
}

async function bindAssetToShot(asset: AssetItem) {
  if (!session.projectId.value) return
  const target = bindShotIndex.value || shotOptions.value[0]
  if (!target) return
  const kind = String(asset.metadata?.asset_kind || asset.metadata?.entity_type || asset.asset_type)
  const field = refFieldForKind(kind)
  const shot = (session.shots.value || []).find((row: any) => Number(row.index) === Number(target))
  const updates: Record<string, any> = {}
  if (field && shot) {
    const current = Array.isArray(shot[field]) ? shot[field] : []
    updates[field] = Array.from(new Set([...current, asset.id]))
  } else if (asset.file_url) {
    updates.selected_image = asset.file_url
    updates.status = 'image_done'
  }
  if (!Object.keys(updates).length) return
  await updateShotRow(session.projectId.value, target, updates)
  session.shots.value = session.shots.value.map((row: any) => {
    if (Number(row.index) !== Number(target)) return row
    return { ...row, ...updates }
  })
}

onMounted(() => {
  if (session.projectId.value) void loadAssets()
})

watch(
  () => session.projectId.value,
  (value) => {
    if (value) void loadAssets()
    else assets.value = []
  },
)

watch(
  shotOptions,
  (rows) => {
    if (!rows.length) {
      bindShotIndex.value = null
      return
    }
    if (!bindShotIndex.value || !rows.includes(bindShotIndex.value)) {
      bindShotIndex.value = rows[0]
    }
  },
  { immediate: true },
)
</script>

<template>
  <section class="asset-pool card">
    <div class="pool-header">
      <label class="bind-select">
        素材类型
        <select v-model="assetKind">
          <option value="character">角色</option>
          <option value="scene">场景</option>
          <option value="prop">道具</option>
          <option value="costume">服化道</option>
          <option value="style">风格</option>
          <option value="shot_keyframe">关键帧</option>
        </select>
      </label>
      <h3>素材池</h3>
      <label class="bind-select">
        绑定目标
        <select v-model.number="bindShotIndex">
          <option :value="null">选择分镜</option>
          <option v-for="idx in shotOptions" :key="idx" :value="idx">#{{ idx }}</option>
        </select>
      </label>
    </div>

    <label
      class="dropzone transition-all"
      :class="{ over: dragOver }"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop="onDrop"
    >
      <input type="file" accept="image/*" multiple hidden @change="onFileChange" />
      <span class="drop-icon">[ + ]</span>
      <strong>拖拽图片到这里，或点击上传</strong>
      <small>支持多图上传，上传后可直接绑定到分镜</small>
    </label>

    <div v-if="uploading" class="upload-progress">
      <div class="track">
        <div class="fill animate-progress" :style="{ width: `${uploadProgress}%` }"></div>
      </div>
      <span>{{ uploadProgress }}%</span>
    </div>

    <div v-if="assets.length === 0" class="empty">
      <div class="empty-icon">◻</div>
      <p>暂无素材，先上传图片构建素材池。</p>
    </div>

    <div v-else class="asset-grid">
      <article v-for="asset in assets" :key="asset.id" class="asset-item transition-all">
        <img :src="asset.file_url" :alt="asset.id" />
        <div class="item-meta">{{ asset.metadata?.view_type || asset.asset_type }}</div>
        <div class="item-actions">
          <button class="btn-danger transition-all" type="button" @click="removeAsset(asset.id)">删除</button>
          <button class="btn-secondary transition-all" type="button" @click="bindAssetToShot(asset)">绑定到 shot</button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.card {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.asset-pool {
  padding: 1rem;
}

.pool-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

h3 {
  margin: 0;
  font-size: 0.95rem;
}

.bind-select {
  display: inline-flex;
  gap: 0.45rem;
  align-items: center;
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}

.bind-select select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  border-radius: var(--radius-sm);
  height: 30px;
  padding: 0 0.45rem;
}

.dropzone {
  display: grid;
  gap: 0.2rem;
  place-items: center;
  text-align: center;
  border: 1.5px dashed color-mix(in srgb, var(--color-primary) 45%, var(--color-border));
  border-radius: var(--radius-md);
  padding: 1rem 0.7rem;
  background: color-mix(in srgb, var(--color-bg-secondary) 88%, transparent);
  cursor: pointer;
  margin-bottom: 0.7rem;
}

.dropzone:hover,
.dropzone.over {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 16%, transparent);
}

.drop-icon {
  font-size: 1rem;
  color: var(--color-primary);
}

.dropzone strong {
  font-size: 0.86rem;
  color: var(--color-text);
}

.dropzone small {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}

.upload-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.65rem;
}

.track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: var(--color-bg-secondary);
  overflow: hidden;
}

.fill {
  height: 100%;
  background: var(--gradient-progress);
}

.upload-progress span {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(92px, 1fr));
  gap: 0.55rem;
}

.asset-item {
  position: relative;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--color-bg-secondary);
}

.asset-item:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--color-primary) 60%, var(--color-border));
}

.asset-item img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
}

.item-meta {
  font-size: 0.66rem;
  padding: 0.2rem 0.3rem;
  color: var(--color-text-secondary);
}

.item-actions {
  position: absolute;
  inset: auto 4px 4px 4px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transform: translateY(4px);
  transition: all 0.18s ease;
}

.asset-item:hover .item-actions {
  opacity: 1;
  transform: translateY(0);
}

.btn-secondary,
.btn-danger {
  flex: 1;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 0.62rem;
  padding: 0.14rem 0.2rem;
  cursor: pointer;
}

.btn-secondary {
  background: color-mix(in srgb, var(--color-bg) 78%, transparent);
  color: var(--color-text);
}

.btn-danger {
  background: color-mix(in srgb, var(--color-error) 22%, transparent);
  border-color: color-mix(in srgb, var(--color-error) 52%, var(--color-border));
  color: #fff;
}

.btn-secondary:hover,
.btn-danger:hover {
  filter: brightness(1.05);
}

.empty {
  text-align: center;
  color: var(--color-text-secondary);
  padding: 1rem 0.2rem;
}

.empty-icon {
  font-size: 1.3rem;
  margin-bottom: 0.2rem;
}

.empty p {
  margin: 0;
  font-size: 0.82rem;
}
</style>
