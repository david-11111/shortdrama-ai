<script setup lang="ts">
import { ref, computed } from 'vue'

interface Asset {
  id: string
  asset_type: string
  file_url?: string
  filename?: string
  status?: string
  metadata?: Record<string, unknown>
}

const props = defineProps<{
  assets: Asset[]
  loading: boolean
}>()

const emit = defineEmits<{
  upload: [file: File, assetType: string]
  delete: [assetId: string]
  select: [asset: Asset]
}>()

const filterType = ref<string>('')
const uploadType = ref<string>('character')
const fileInput = ref<HTMLInputElement | null>(null)

const assetTypes = ['character', 'scene', 'style', 'generic'] as const

const filteredAssets = computed(() => {
  if (!filterType.value) return props.assets
  return props.assets.filter(a => a.asset_type === filterType.value)
})

function triggerUpload() {
  fileInput.value?.click()
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit('upload', file, uploadType.value)
    input.value = ''
  }
}

function getViews(asset: Asset): string[] {
  const meta = asset.metadata as { views?: string[] } | undefined
  return meta?.views || []
}
</script>

<template>
  <aside class="asset-panel">
    <header class="panel-header">
      <h3>资产池</h3>
      <div class="panel-actions">
        <select v-model="filterType" class="filter-select">
          <option value="">全部</option>
          <option v-for="t in assetTypes" :key="t" :value="t">{{ t }}</option>
        </select>
      </div>
    </header>

    <div class="upload-bar">
      <select v-model="uploadType" class="upload-type-select">
        <option v-for="t in assetTypes" :key="t" :value="t">{{ t }}</option>
      </select>
      <button class="btn btn-sm" @click="triggerUpload">上传</button>
      <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else class="asset-grid">
      <div
        v-for="asset in filteredAssets"
        :key="asset.id"
        class="asset-card"
        @click="emit('select', asset)"
      >
        <img
          v-if="asset.file_url"
          :src="asset.file_url"
          :alt="asset.filename || ''"
          class="asset-thumb"
        />
        <div v-else class="asset-placeholder">{{ asset.asset_type[0].toUpperCase() }}</div>

        <div class="asset-info">
          <span class="asset-name">{{ asset.filename || asset.id.slice(0, 8) }}</span>
          <span class="asset-type-badge">{{ asset.asset_type }}</span>
        </div>

        <div v-if="getViews(asset).length" class="asset-views">
          <img
            v-for="(view, i) in getViews(asset)"
            :key="i"
            :src="view"
            class="view-thumb"
            :alt="`view-${i}`"
          />
        </div>

        <button
          class="delete-btn"
          title="删除"
          @click.stop="emit('delete', asset.id)"
        >&times;</button>
      </div>

      <p v-if="filteredAssets.length === 0" class="empty">暂无资产</p>
    </div>
  </aside>
</template>

<style scoped>
.asset-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
}

.panel-header h3 { margin: 0; font-size: 14px; }

.filter-select,
.upload-type-select {
  padding: 2px 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 12px;
  background: var(--color-bg);
  color: var(--color-text);
}

.upload-bar {
  display: flex;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
}

.btn-sm {
  padding: 2px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  cursor: pointer;
  font-size: 12px;
}

.loading {
  padding: var(--space-lg);
  text-align: center;
  color: var(--color-text-secondary);
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
  gap: var(--space-sm);
  padding: var(--space-sm);
  overflow-y: auto;
  flex: 1;
}

.asset-card {
  position: relative;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-xs);
  cursor: pointer;
  transition: border-color 0.15s;
}

.asset-card:hover { border-color: var(--color-primary); }

.asset-thumb {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: var(--radius-sm);
}

.asset-placeholder {
  width: 100%;
  aspect-ratio: 1;
  background: var(--color-bg-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: bold;
  color: var(--color-text-secondary);
  border-radius: var(--radius-sm);
}

.asset-info {
  margin-top: var(--space-xs);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.asset-name {
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-type-badge {
  font-size: 10px;
  color: var(--color-text-secondary);
}

.asset-views {
  display: flex;
  gap: 2px;
  margin-top: var(--space-xs);
}

.view-thumb {
  width: 24px;
  height: 24px;
  object-fit: cover;
  border-radius: 2px;
}

.delete-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  background: var(--color-error);
  color: #fff;
  border: none;
  border-radius: 50%;
  width: 18px;
  height: 18px;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
}

.asset-card:hover .delete-btn { opacity: 1; }

.empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 13px;
}
</style>
