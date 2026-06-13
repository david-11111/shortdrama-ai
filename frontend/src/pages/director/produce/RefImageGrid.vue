<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { directorReferenceImages } from '@/api/director'
import { saveReferenceBindings } from '@/api/prompt'
import { updateShotRow } from '@/api/workbench'
import { useTaskPoller } from '@/composables/useTaskPoller'
import type { RefImageItem } from '@/composables/useDirectorSession'

type RefGridItem = RefImageItem & { id: string }

const session = inject<any>('session')
const poller = useTaskPoller()
const charDescription = ref('')
const showInput = ref(false)
const selectedIds = ref<Set<string>>(new Set())
const bindShotIds = ref<Set<number>>(new Set())
const binding = ref(false)
const showBindPanel = ref(false)
const localError = ref('')
const previewImage = ref<RefGridItem | null>(null)

const views = ['front', 'side', 'expression_smile', 'full_body']
const items = computed(() => session.refImages.value as RefGridItem[])
const shotOptions = computed(() => {
  const rows = session.shots.value || []
  return rows
    .map((shot: any) => Number(shot.index))
    .filter((idx: number) => Number.isFinite(idx) && idx > 0)
})
const selectedItems = computed(() => {
  return items.value.filter((item) => selectedIds.value.has(item.id) && item.url && !item.pending)
})

function createId(prefix: string, view: string) {
  return `${prefix}-${view}-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`
}

function normalizeViewLabel(view: string) {
  if (view?.startsWith('shot_')) {
    const idx = view.slice('shot_'.length)
    return `分镜 #${idx}`
  }
  const map: Record<string, string> = {
    front: '正面',
    side: '侧面',
    expression_smile: '微笑',
    full_body: '全身',
  }
  return map[view] || view
}

function toggleSelect(item: RefGridItem) {
  if (item.pending) return
  const next = new Set(selectedIds.value)
  if (next.has(item.id)) next.delete(item.id)
  else next.add(item.id)
  selectedIds.value = next
}

function isSelected(item: RefGridItem) {
  return selectedIds.value.has(item.id)
}

function openPreview(item: RefGridItem) {
  if (!item.url) return
  previewImage.value = item
}

function closePreview() {
  previewImage.value = null
}

function toggleBindShot(shotIndex: number) {
  const next = new Set(bindShotIds.value)
  if (next.has(shotIndex)) next.delete(shotIndex)
  else next.add(shotIndex)
  bindShotIds.value = next
}

function openBindPanel() {
  if (!selectedItems.value.length) {
    localError.value = '请先选中参考图，再绑定分镜。'
    return
  }
  if (!shotOptions.value.length) {
    localError.value = '当前没有可绑定分镜。'
    return
  }
  if (!bindShotIds.value.size) {
    bindShotIds.value = new Set([shotOptions.value[0]])
  }
  localError.value = ''
  showBindPanel.value = true
}

function replacePendingByTaskId(taskId: string, updater: (item: RefGridItem) => RefGridItem) {
  session.refImages.value = items.value.map((item) => {
    if (item.asset_id !== taskId) return item
    return updater(item)
  })
}

async function waitForTask(taskId: string) {
  poller.start(taskId)
  return await new Promise<{ status: string; result: any; error: string }>((resolve) => {
    const timer = setInterval(() => {
      replacePendingByTaskId(taskId, (item) => ({
        ...item,
        progress: Math.max(item.progress || 0, poller.progress.value || 0),
      }))
      const stopped = !poller.isPolling.value
      const hasState = Boolean(poller.status.value || poller.result.value || poller.error.value)
      if (stopped && hasState) {
        clearInterval(timer)
        resolve({
          status: poller.status.value,
          result: poller.result.value,
          error: poller.error.value,
        })
      }
    }, 120)
  })
}

async function generateRefImages() {
  if (!session.projectId.value) return
  localError.value = ''
  if (!charDescription.value.trim()) {
    showInput.value = true
    localError.value = '请先填写角色描述，再生成参考图。'
    return
  }
  try {
    const { data } = await directorReferenceImages({
      project_id: session.projectId.value,
      character_description: charDescription.value,
      views,
    })
    const taskId = data.task_id
    const pendingItems: RefGridItem[] = views.map((view) => ({
      id: createId(taskId, view),
      view,
      url: '',
      asset_id: taskId,
      pending: true,
      progress: 0,
      selected: false,
    }))
    session.refImages.value = [...items.value, ...pendingItems]
    showInput.value = false
    session.beginTask()

    try {
      const done = await waitForTask(taskId)
      if (done.status === 'done' && done.result?.views) {
        const viewMap = done.result.views as Record<string, string>
        replacePendingByTaskId(taskId, (item) => ({
          ...item,
          url: viewMap[item.view] || '',
          asset_id: done.result.asset_id || item.asset_id,
          pending: false,
          progress: 100,
        }))
        return
      }
      const err = done.error || done.status || '任务失败'
      localError.value = err
      replacePendingByTaskId(taskId, (item) => ({
        ...item,
        pending: false,
        error: err,
      }))
    } finally {
      session.endTask()
    }
  } catch (e: any) {
    localError.value = e?.response?.data?.detail || e?.message || '参考图任务提交失败'
  }
}

async function applyBindings() {
  if (!session.projectId.value) return
  if (!selectedItems.value.length || !bindShotIds.value.size) return
  binding.value = true
  localError.value = ''
  try {
    const urls = selectedItems.value.map((item) => item.url)
    const refIds = selectedItems.value
      .map((item) => item.asset_id || item.url)
      .filter((value): value is string => Boolean(value))
    const shots = Array.from(bindShotIds.value)
    for (let i = 0; i < shots.length; i += 1) {
      const shotIndex = shots[i]
      const url = urls[i % urls.length]
      await updateShotRow(session.projectId.value, shotIndex, {
        selected_image: url,
        status: 'image_done',
      })
    }
    await saveReferenceBindings(
      session.projectId.value,
      shots.map((shotIndex) => ({
        shot_index: shotIndex,
        character_refs: refIds,
        scene_refs: [],
        prop_refs: [],
        costume_refs: [],
        style_refs: [],
      })),
    )
    session.shots.value = session.shots.value.map((shot: any) => {
      if (!shots.includes(Number(shot.index))) return shot
      const idx = shots.indexOf(Number(shot.index))
      return {
        ...shot,
        selected_image: urls[idx % urls.length],
        status: 'image_done',
        character_refs: refIds,
      }
    })
    showBindPanel.value = false
  } catch (e: any) {
    localError.value = e?.response?.data?.detail || e?.message || '绑定分镜失败'
  } finally {
    binding.value = false
  }
}
</script>

<template>
  <section class="ref-grid card">
    <div class="ref-header">
      <h3>参考图</h3>
      <button class="btn-secondary transition-all" type="button" @click="openBindPanel">绑定分镜</button>
      <button class="btn-secondary transition-all" type="button" @click="showInput = !showInput">
        {{ showInput ? '收起描述' : '展开描述' }}
      </button>
      <button class="btn-primary transition-all" type="button" @click="generateRefImages">生成参考图</button>
    </div>

    <div v-show="showInput" class="inline-input animate-slide-up">
      <textarea
        v-model.trim="charDescription"
        rows="2"
        placeholder="角色描述，例如：短发、白衬衫、电影级写实、暖色逆光"
      />
      <p>将生成 {{ views.length }} 个视角</p>
    </div>

    <p v-if="localError" class="error-tip">{{ localError }}</p>

    <div v-if="items.length === 0" class="empty">暂无参考图，输入角色描述后开始生成。</div>
    <div v-else class="grid">
      <article
        v-for="img in items"
        :key="img.id"
        class="ref-card transition-all"
        :class="{ selected: isSelected(img), pending: img.pending }"
        @click="toggleSelect(img)"
      >
        <div class="preview">
          <img v-if="img.url" :src="img.url" :alt="img.view" />
          <button v-if="img.url" class="zoom-btn transition-all" type="button" @click.stop="openPreview(img)">放大</button>
          <div v-else class="skeleton">
            <div class="skeleton-block"></div>
            <span>{{ img.progress || poller.progress.value || 0 }}%</span>
          </div>
        </div>
        <div class="meta">
          <strong>{{ normalizeViewLabel(img.view) }}</strong>
          <small v-if="img.error">{{ img.error }}</small>
          <small v-else-if="img.pending">{{ poller.stageText.value || '生成中...' }}</small>
          <small v-else>{{ isSelected(img) ? '已选中' : '点击选中' }}</small>
        </div>
      </article>
    </div>

    <div v-if="previewImage" class="lightbox" @click.self="closePreview">
      <div class="lightbox-panel">
        <div class="lightbox-head">
          <strong>{{ normalizeViewLabel(previewImage.view) }}</strong>
          <button class="btn-secondary transition-all" type="button" @click="closePreview">关闭</button>
        </div>
        <img :src="previewImage.url" :alt="previewImage.view" />
      </div>
    </div>

    <div v-if="showBindPanel" class="bind-panel animate-slide-up">
      <div class="bind-head">
        <strong>分镜展示与绑定</strong>
        <button class="btn-secondary transition-all" type="button" @click="showBindPanel = false">关闭</button>
      </div>
      <p class="bind-desc">已选参考图 {{ selectedItems.length }} 张，勾选要绑定的分镜后保存。</p>
      <div class="bind-shots">
        <label v-for="idx in shotOptions" :key="idx" class="bind-shot">
          <input type="checkbox" :checked="bindShotIds.has(idx)" @change="toggleBindShot(idx)" />
          <span>#{{ idx }}</span>
        </label>
      </div>
      <div class="bind-actions">
        <button class="btn-primary transition-all" type="button" :disabled="binding || !bindShotIds.size" @click="applyBindings">
          {{ binding ? '绑定中...' : '保存绑定' }}
        </button>
      </div>
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

.ref-grid {
  padding: 1rem;
}

.ref-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

h3 {
  margin: 0;
  font-size: 0.96rem;
  flex: 1;
}

.inline-input {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  padding: 0.55rem;
  margin-bottom: 0.75rem;
}

.inline-input textarea {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  padding: 0.5rem;
  resize: vertical;
  font: inherit;
}

.inline-input p {
  margin: 0.45rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.74rem;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 0.7rem;
}

.ref-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--color-bg-secondary);
  cursor: pointer;
}

.ref-card:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--color-primary) 58%, var(--color-border));
}

.ref-card.selected {
  border-color: color-mix(in srgb, var(--color-primary) 68%, var(--color-border));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 25%, transparent);
}

.preview {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
}

.preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.ref-card:hover .preview img {
  transform: scale(1.08);
}

.zoom-btn {
  position: absolute;
  right: 8px;
  bottom: 8px;
  height: 28px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 52%, var(--color-border));
  border-radius: 999px;
  padding: 0 0.6rem;
  background: color-mix(in srgb, var(--color-bg) 80%, transparent);
  color: var(--color-text);
  font-size: 0.72rem;
  cursor: pointer;
}

.skeleton {
  height: 100%;
  display: grid;
  place-items: center;
  background: linear-gradient(90deg, rgba(148, 163, 184, 0.18), rgba(148, 163, 184, 0.3), rgba(148, 163, 184, 0.18));
  background-size: 180% 100%;
  animation: progress-stripe 1s linear infinite;
}

.skeleton-block {
  position: absolute;
  width: 44%;
  height: 44%;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--color-border) 70%, transparent);
}

.skeleton span {
  position: relative;
  z-index: 1;
  font-size: 0.83rem;
  color: var(--color-text);
}

.meta {
  padding: 0.4rem 0.45rem 0.45rem;
}

.meta strong {
  display: block;
  font-size: 0.76rem;
  color: var(--color-text);
}

.meta small {
  display: block;
  margin-top: 0.2rem;
  font-size: 0.68rem;
  color: var(--color-text-secondary);
}

.btn-primary,
.btn-secondary {
  height: 32px;
  padding: 0 0.68rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  cursor: pointer;
  font-size: 0.78rem;
}

.btn-primary {
  background: var(--color-primary);
  color: #fff;
  border-color: color-mix(in srgb, var(--color-primary) 68%, var(--color-border));
}

.btn-secondary {
  background: var(--color-bg-secondary);
  color: var(--color-text);
}

.btn-primary:hover,
.btn-secondary:hover {
  transform: translateY(-1px);
}

.empty {
  color: var(--color-text-secondary);
  text-align: center;
  font-size: 0.85rem;
  padding: 1.2rem 0;
}

.error-tip {
  margin: 0 0 0.55rem;
  font-size: 0.8rem;
  color: var(--color-error);
}

.bind-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  padding: 0.55rem;
  margin-top: 0.7rem;
}

.bind-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.bind-desc {
  margin: 0.4rem 0;
  font-size: 0.74rem;
  color: var(--color-text-secondary);
}

.bind-shots {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
  gap: 0.4rem;
}

.bind-shot {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 0.35rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.75rem;
}

.bind-actions {
  margin-top: 0.55rem;
  display: flex;
  justify-content: flex-end;
}

.lightbox {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgba(2, 6, 23, 0.74);
  display: grid;
  place-items: center;
  padding: 1rem;
}

.lightbox-panel {
  width: min(88vw, 980px);
  max-height: 88vh;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.lightbox-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.7rem 0.9rem;
  border-bottom: 1px solid var(--color-border);
}

.lightbox-panel img {
  display: block;
  width: 100%;
  max-height: calc(88vh - 56px);
  object-fit: contain;
  background: #000;
}
</style>
