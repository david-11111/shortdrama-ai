<script setup lang="ts">
import { ref, computed } from 'vue'

interface Asset {
  id: string
  asset_type: string
  file_url?: string
  filename?: string
  metadata?: Record<string, unknown>
}

const props = defineProps<{
  visible: boolean
  assets: Asset[]
  characterRefs: string[]
  sceneRefs: string[]
  propRefs: string[]
  costumeRefs: string[]
  styleRefs: string[]
}>()

const emit = defineEmits<{
  'update:visible': [val: boolean]
  save: [refs: { character_refs: string[]; scene_refs: string[]; prop_refs: string[]; costume_refs: string[]; style_refs: string[] }]
}>()

const localCharRefs = ref<string[]>([...props.characterRefs])
const localSceneRefs = ref<string[]>([...props.sceneRefs])
const localPropRefs = ref<string[]>([...props.propRefs])
const localCostumeRefs = ref<string[]>([...props.costumeRefs])
const localStyleRefs = ref<string[]>([...props.styleRefs])

const activeTab = ref<'character' | 'scene' | 'prop' | 'costume' | 'style'>('character')

const filteredAssets = computed(() =>
  props.assets.filter((a) => {
    const kind = String(a.metadata?.asset_kind || a.metadata?.entity_type || a.asset_type)
    return kind === activeTab.value
  })
)

function isSelected(assetId: string): boolean {
  const map = { character: localCharRefs, scene: localSceneRefs, prop: localPropRefs, costume: localCostumeRefs, style: localStyleRefs }
  return map[activeTab.value].value.includes(assetId)
}

function toggle(assetId: string) {
  const map = { character: localCharRefs, scene: localSceneRefs, prop: localPropRefs, costume: localCostumeRefs, style: localStyleRefs }
  const list = map[activeTab.value]
  const idx = list.value.indexOf(assetId)
  if (idx >= 0) list.value.splice(idx, 1)
  else list.value.push(assetId)
}

function save() {
  emit('save', {
    character_refs: localCharRefs.value,
    scene_refs: localSceneRefs.value,
    prop_refs: localPropRefs.value,
    costume_refs: localCostumeRefs.value,
    style_refs: localStyleRefs.value,
  })
  emit('update:visible', false)
}

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <teleport to="body">
    <div v-if="visible" class="ref-overlay" @click.self="close">
      <div class="ref-modal">
        <header class="ref-header">
          <h3>管理引用资产</h3>
          <button class="close-btn" @click="close">&times;</button>
        </header>

        <nav class="ref-tabs">
          <button
            v-for="tab in (['character', 'scene', 'prop', 'costume', 'style'] as const)"
            :key="tab"
            :class="['tab', { active: activeTab === tab }]"
            @click="activeTab = tab"
          >
            {{ tab }}
          </button>
        </nav>

        <div class="ref-grid">
          <div
            v-for="asset in filteredAssets"
            :key="asset.id"
            :class="['ref-item', { selected: isSelected(asset.id) }]"
            @click="toggle(asset.id)"
          >
            <img
              v-if="asset.file_url"
              :src="asset.file_url"
              :alt="asset.filename || asset.id"
              class="ref-thumb"
            />
            <div v-else class="ref-placeholder">{{ asset.filename || asset.id }}</div>
            <span class="ref-label">{{ asset.filename || asset.id }}</span>
          </div>
          <p v-if="filteredAssets.length === 0" class="empty">暂无 {{ activeTab }} 类型资产</p>
        </div>

        <footer class="ref-footer">
          <button class="btn btn-secondary" @click="close">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </footer>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.ref-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.ref-modal {
  background: var(--color-bg);
  border-radius: var(--radius-lg);
  width: 560px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.ref-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md);
  border-bottom: 1px solid var(--color-border);
}

.ref-header h3 { margin: 0; font-size: 16px; }

.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  color: var(--color-text-secondary);
}

.ref-tabs {
  display: flex;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
}

.tab {
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  cursor: pointer;
  font-size: 13px;
}

.tab.active {
  background: var(--color-primary);
  color: #fff;
  border-color: var(--color-primary);
}

.ref-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: var(--space-sm);
  padding: var(--space-md);
  overflow-y: auto;
  flex: 1;
}

.ref-item {
  border: 2px solid transparent;
  border-radius: var(--radius-sm);
  padding: var(--space-xs);
  cursor: pointer;
  text-align: center;
  transition: border-color 0.15s;
}

.ref-item.selected {
  border-color: var(--color-primary);
}

.ref-thumb {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: var(--radius-sm);
}

.ref-placeholder {
  width: 100%;
  aspect-ratio: 1;
  background: var(--color-bg-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
}

.ref-label {
  display: block;
  font-size: 11px;
  margin-top: var(--space-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--color-text-secondary);
}

.ref-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  padding: var(--space-md);
  border-top: 1px solid var(--color-border);
}

.btn {
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-sm);
  font-size: 14px;
  cursor: pointer;
}

.btn-primary { background: var(--color-primary); color: #fff; }
.btn-secondary { background: var(--color-bg-secondary); color: var(--color-text); border: 1px solid var(--color-border); }
</style>
