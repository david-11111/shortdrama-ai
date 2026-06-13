<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import type { RefImageItem, Shot } from '@/composables/useDirectorSession'

const session = inject<any>('session')
const activeKey = ref('')

const refs = computed<RefImageItem[]>(() => {
  const items = Array.isArray(session?.refImages?.value) ? session.refImages.value : []
  return items.filter((item: RefImageItem) => item?.url && !item.pending)
})

const shots = computed<Shot[]>(() => {
  const rows = Array.isArray(session?.shots?.value) ? session.shots.value : []
  return rows.filter((shot: Shot) => Number.isFinite(Number(shot.index)))
})

const sourceRefs = computed(() => {
  return refs.value.filter((item) => !String(item.view || '').startsWith('shot_') && item.lineage_role !== 'derived')
})

const derivedRefs = computed(() => {
  return refs.value.filter((item) => String(item.view || '').startsWith('shot_') || item.lineage_role === 'derived')
})

const canvasRows = computed(() => Math.max(sourceRefs.value.length, derivedRefs.value.length, shots.value.length, 1))
const canvasHeight = computed(() => 112 + canvasRows.value * 96)
type Connection = {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
  activeKeys: string[]
  kind: string
}

function normalizeViewLabel(view: string) {
  if (view?.startsWith('shot_')) return `分镜 #${view.slice('shot_'.length)}`
  const map: Record<string, string> = {
    front: '正面母图',
    side: '侧面母图',
    expression_smile: '表情母图',
    full_body: '全身母图',
  }
  return map[view] || view || '参考图'
}

function keyForRef(item: RefImageItem) {
  return item.id || item.asset_id || item.url
}

function isLineActive(line: Connection) {
  return !activeKey.value || line.activeKeys.includes(activeKey.value)
}

function isNodeActive(key: string) {
  if (!activeKey.value || activeKey.value === key) return true
  return connections.value.some((line) => line.activeKeys.includes(activeKey.value) && line.activeKeys.includes(key))
}

function rowY(index: number) {
  return 88 + index * 96
}

function shotConnections() {
  const sourceById = new Map<string, number>()
  const sourceByUrl = new Map<string, number>()
  const derivedByUrl = new Map<string, number>()

  sourceRefs.value.forEach((item, idx) => {
    if (item.asset_id) sourceById.set(item.asset_id, idx)
    sourceByUrl.set(item.url, idx)
  })
  derivedRefs.value.forEach((item, idx) => {
    derivedByUrl.set(item.url, idx)
  })

  const lines: Connection[] = []
  shots.value.forEach((shot, shotIdx) => {
    const shotY = rowY(shotIdx)
    const shotKey = String(shot.index)
    const selectedUrl = shot.selected_image || ''
    const derivedIdx = selectedUrl ? derivedByUrl.get(selectedUrl) : undefined
    const selectedSourceIdx = selectedUrl ? sourceByUrl.get(selectedUrl) : undefined
    const refIds = Array.isArray(shot.character_refs) ? shot.character_refs : []
    const sourceIdx = refIds.map((id) => sourceById.get(id) ?? sourceByUrl.get(id)).find((idx) => idx !== undefined)
    const sourceKey = sourceIdx !== undefined ? keyForRef(sourceRefs.value[sourceIdx]) : ''
    const selectedSourceKey = selectedSourceIdx !== undefined ? keyForRef(sourceRefs.value[selectedSourceIdx]) : ''
    const derivedKey = derivedIdx !== undefined ? keyForRef(derivedRefs.value[derivedIdx]) : ''

    if (sourceIdx !== undefined) {
      lines.push({
        id: `source-${shot.index}`,
        x1: 260,
        y1: rowY(sourceIdx),
        x2: derivedIdx !== undefined ? 512 : 756,
        y2: derivedIdx !== undefined ? rowY(derivedIdx) : shotY,
        activeKeys: [shotKey, sourceKey, derivedKey].filter(Boolean),
        kind: 'source',
      })
    } else if (selectedSourceIdx !== undefined) {
      lines.push({
        id: `source-selected-${shot.index}`,
        x1: 260,
        y1: rowY(selectedSourceIdx),
        x2: 756,
        y2: shotY,
        activeKeys: [shotKey, selectedSourceKey].filter(Boolean),
        kind: 'source',
      })
    }

    if (derivedIdx !== undefined) {
      lines.push({
        id: `derived-${shot.index}`,
        x1: 512,
        y1: rowY(derivedIdx),
        x2: 756,
        y2: shotY,
        activeKeys: [shotKey, derivedKey].filter(Boolean),
        kind: 'derived',
      })
    }
  })
  return lines
}

const connections = computed(shotConnections)
</script>

<template>
  <section class="lineage-card">
    <div class="lineage-head">
      <div>
        <h3>参考图链路画布</h3>
        <p>母图、衍生图与分镜的绑定关系</p>
      </div>
      <button class="canvas-reset" type="button" @click="activeKey = ''">重置高亮</button>
    </div>

    <div v-if="!refs.length && !shots.length" class="empty">生成参考图或分镜后，这里会显示生产链路。</div>
    <div v-else class="canvas-wrap">
      <svg class="links" :viewBox="`0 0 980 ${canvasHeight}`" preserveAspectRatio="none" :style="{ height: `${canvasHeight}px` }">
        <path
          v-for="line in connections"
          :key="line.id"
          :class="['link-line', line.kind, { muted: !isLineActive(line) }]"
          :d="`M ${line.x1} ${line.y1} C ${(line.x1 + line.x2) / 2} ${line.y1}, ${(line.x1 + line.x2) / 2} ${line.y2}, ${line.x2} ${line.y2}`"
        />
      </svg>

      <div class="canvas-grid" :style="{ minHeight: `${canvasHeight}px` }">
        <div class="lane">
          <div class="lane-title">参考母图</div>
          <button
            v-for="(item, idx) in sourceRefs"
            :key="keyForRef(item)"
            class="node ref-node"
            :class="{ muted: !isNodeActive(keyForRef(item)) }"
            :style="{ top: `${rowY(idx) - 34}px` }"
            type="button"
            @click="activeKey = keyForRef(item)"
          >
            <img :src="item.url" :alt="item.view" />
            <span>{{ normalizeViewLabel(item.view) }}</span>
          </button>
        </div>

        <div class="lane">
          <div class="lane-title">衍生 / 已绑定图</div>
          <button
            v-for="(item, idx) in derivedRefs"
            :key="keyForRef(item)"
            class="node ref-node"
            :class="{ muted: !isNodeActive(keyForRef(item)) }"
            :style="{ top: `${rowY(idx) - 34}px` }"
            type="button"
            @click="activeKey = keyForRef(item)"
          >
            <img :src="item.url" :alt="item.view" />
            <span>{{ normalizeViewLabel(item.view) }}</span>
          </button>
          <div v-if="!derivedRefs.length" class="lane-empty">暂无衍生图</div>
        </div>

        <div class="lane">
          <div class="lane-title">分镜</div>
          <button
            v-for="(shot, idx) in shots"
            :key="shot.index"
            class="node shot-node"
            :class="{ muted: !isNodeActive(String(shot.index)) }"
            :style="{ top: `${rowY(idx) - 34}px` }"
            type="button"
            @click="activeKey = String(shot.index)"
          >
            <strong>#{{ shot.index }}</strong>
            <span>{{ shot.selected_image ? '已绑定参考图' : '未绑定' }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.lineage-card {
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
}

.lineage-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

h3 {
  margin: 0;
  font-size: 0.96rem;
}

.lineage-head p {
  margin: 0.25rem 0 0;
  font-size: 0.74rem;
  color: var(--color-text-secondary);
}

.canvas-reset {
  height: 30px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  padding: 0 0.65rem;
  cursor: pointer;
}

.canvas-wrap {
  position: relative;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-bg-secondary) 76%, var(--color-bg));
}

.links {
  position: absolute;
  inset: 0;
  width: 100%;
  min-width: 880px;
  pointer-events: none;
}

.link-line {
  fill: none;
  stroke: color-mix(in srgb, var(--color-primary) 70%, #ffffff);
  stroke-width: 2.5;
  opacity: 0.9;
}

.link-line.derived {
  stroke: color-mix(in srgb, var(--color-success) 70%, #ffffff);
}

.link-line.muted {
  opacity: 0.18;
}

.canvas-grid {
  position: relative;
  min-width: 880px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.2rem;
  padding: 0.75rem;
}

.lane {
  position: relative;
}

.lane-title {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  color: var(--color-text-secondary);
  font-size: 0.74rem;
  font-weight: 700;
}

.node {
  position: absolute;
  left: 0.5rem;
  width: calc(100% - 1rem);
  min-height: 68px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  cursor: pointer;
  transition: opacity 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
  text-align: left;
}

.node:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
}

.node.muted {
  opacity: 0.42;
}

.ref-node {
  display: grid;
  grid-template-columns: 60px 1fr;
  align-items: center;
  gap: 0.55rem;
  padding: 0.38rem;
}

.ref-node img {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  object-fit: cover;
  background: #000;
}

.ref-node span,
.shot-node span {
  font-size: 0.76rem;
  color: var(--color-text-secondary);
}

.shot-node {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.25rem;
  padding: 0.55rem 0.7rem;
}

.shot-node strong {
  font-size: 0.9rem;
}

.lane-empty {
  margin: 4.2rem 0.5rem 0;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: 0.85rem;
  color: var(--color-text-secondary);
  font-size: 0.78rem;
  text-align: center;
}

.empty {
  padding: 1rem;
  color: var(--color-text-secondary);
  text-align: center;
  font-size: 0.84rem;
}
</style>
