<template>
  <div class="director-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Director Flow</p>
        <h1>制作流</h1>
        <p class="page-subtitle">只保留异步制作相关动作，提交更快。</p>
      </div>
      <div class="header-actions">
        <router-link to="/director" class="btn-link">导演首页</router-link>
        <router-link to="/tasks" class="btn-link">任务队列</router-link>
      </div>
    </header>

    <section class="project-bar">
      <label for="project-id">项目 ID</label>
      <input id="project-id" v-model.trim="projectId" placeholder="请输入 project_id" />
    </section>

    <section class="cards-grid">
      <article class="card">
        <h2>1) director/script</h2>
        <input v-model.trim="scriptForm.topic" placeholder="剧情主题 topic" />
        <input v-model.trim="scriptForm.style" placeholder="风格 style（可选）" />
        <input v-model.number="scriptForm.shot_count" type="number" min="1" max="50" placeholder="镜头数 shot_count" />
        <button type="button" class="btn-primary" :disabled="!projectId || !scriptForm.topic || loading.script" @click="submitScript">
          {{ loading.script ? '提交中...' : '提交 Script 任务' }}
        </button>
      </article>

      <article class="card">
        <h2>2) director/chat</h2>
        <textarea v-model.trim="chatInput" rows="4" placeholder="输入导演对话内容..." />
        <input v-model.trim="chatPreset" placeholder="preset（可选）" />
        <button type="button" class="btn-primary" :disabled="!projectId || !chatInput || loading.chat" @click="submitChat">
          {{ loading.chat ? '提交中...' : '提交 Chat 任务' }}
        </button>
      </article>

      <article class="card">
        <h2>3) director/prepare</h2>
        <input v-model.trim="prepareShotIndicesInput" placeholder="shot_indices（逗号分隔，可选）" />
        <button type="button" class="btn-primary" :disabled="!projectId || loading.prepare" @click="submitPrepare">
          {{ loading.prepare ? '提交中...' : '提交 Prepare 任务' }}
        </button>
      </article>

      <article class="card">
        <h2>4) director/produce</h2>
        <input v-model.trim="produceShotIndicesInput" placeholder="shot_indices（逗号分隔，可选）" />
        <label class="inline-check">
          <input v-model="produceSkipImages" type="checkbox" />
          <span>skip_images</span>
        </label>
        <input v-model.trim="produceProvider" placeholder="provider（可选，如 seedance/kling）" />
        <button type="button" class="btn-primary" :disabled="!projectId || loading.produce" @click="submitProduce">
          {{ loading.produce ? '提交中...' : '提交 Produce 任务' }}
        </button>
      </article>

      <article class="card">
        <h2>5) director/reference-images</h2>
        <textarea
          v-model.trim="refImageCharacterDescription"
          rows="3"
          placeholder="character_description（人物描述）"
        />
        <input v-model.trim="refImageViewsInput" placeholder="views（逗号分隔，如 front,side,back）" />
        <input v-model.trim="refImageAssetType" placeholder="asset_type（可选）" />
        <button
          type="button"
          class="btn-primary"
          :disabled="!projectId || !refImageCharacterDescription || loading.referenceImages"
          @click="submitReferenceImages"
        >
          {{ loading.referenceImages ? '提交中...' : '提交 Reference Images 任务' }}
        </button>
      </article>
    </section>

    <section class="result-card">
      <h2>响应结果</h2>
      <p class="result-hint">最后一次调用: {{ lastAction || '无' }}</p>
      <pre>{{ responseText }}</pre>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  directorChat,
  directorPrepare,
  directorProduce,
  directorReferenceImages,
  directorScript,
} from '@/api/director'

const route = useRoute()
const projectId = ref((route.params.projectId as string) || localStorage.getItem('director:last_project_id') || '')

watch(
  () => route.params.projectId,
  (value) => {
    if (typeof value === 'string') {
      projectId.value = value
    }
  },
)

watch(projectId, (value) => {
  localStorage.setItem('director:last_project_id', value || '')
})

const scriptForm = ref({
  topic: '',
  style: '',
  shot_count: 8,
})
const chatInput = ref('')
const chatPreset = ref('')
const prepareShotIndicesInput = ref('')
const produceShotIndicesInput = ref('')
const produceSkipImages = ref(false)
const produceProvider = ref('')
const refImageCharacterDescription = ref('')
const refImageViewsInput = ref('front,side')
const refImageAssetType = ref('character')

const responseText = ref('No response yet.')
const lastAction = ref('')
const loading = ref<Record<string, boolean>>({
  script: false,
  chat: false,
  prepare: false,
  produce: false,
  referenceImages: false,
})

function parseNumberList(value: string): number[] | undefined {
  const list = value
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((num) => Number.isFinite(num))
  return list.length ? list : undefined
}

function parseStringList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function setResponse(action: string, payload: unknown) {
  lastAction.value = action
  responseText.value = JSON.stringify(payload, null, 2)
}

async function withLoading<T>(key: string, fn: () => Promise<T>) {
  loading.value[key] = true
  try {
    const result = await fn()
    return result
  } finally {
    loading.value[key] = false
  }
}

async function submitScript() {
  const { data } = await withLoading('script', () =>
    directorScript({
      project_id: projectId.value,
      topic: scriptForm.value.topic,
      style: scriptForm.value.style || undefined,
      shot_count: Number(scriptForm.value.shot_count) || undefined,
    }),
  )
  setResponse('director/script', data)
}

async function submitChat() {
  const { data } = await withLoading('chat', () =>
    directorChat({
      project_id: projectId.value,
      messages: [{ role: 'user', content: chatInput.value }],
      preset: chatPreset.value || undefined,
    }),
  )
  setResponse('director/chat', data)
}

async function submitPrepare() {
  const { data } = await withLoading('prepare', () =>
    directorPrepare({
      project_id: projectId.value,
      shot_indices: parseNumberList(prepareShotIndicesInput.value),
    }),
  )
  setResponse('director/prepare', data)
}

async function submitProduce() {
  const { data } = await withLoading('produce', () =>
    directorProduce({
      project_id: projectId.value,
      shot_indices: parseNumberList(produceShotIndicesInput.value),
      skip_images: produceSkipImages.value,
      provider: produceProvider.value || undefined,
    }),
  )
  setResponse('director/produce', data)
}

async function submitReferenceImages() {
  const { data } = await withLoading('referenceImages', () =>
    directorReferenceImages({
      project_id: projectId.value,
      character_description: refImageCharacterDescription.value,
      views: parseStringList(refImageViewsInput.value),
      asset_type: refImageAssetType.value || undefined,
    }),
  )
  setResponse('director/reference-images', data)
}
</script>

<style scoped>
.director-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--space-xl);
  display: grid;
  gap: var(--space-lg);
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
}

.page-kicker {
  margin: 0 0 var(--space-xs);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.page-header h1 { margin: 0; font-size: 2rem; }
.page-subtitle { margin: var(--space-sm) 0 0; color: var(--color-text-secondary); }

.header-actions {
  display: flex;
  gap: var(--space-xs);
}

.btn-link {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
  color: var(--color-text-secondary);
}

.project-bar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.project-bar input {
  min-width: 300px;
  flex: 1;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-md);
}

.card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  background: var(--color-bg);
  display: grid;
  gap: var(--space-xs);
}

.card h2 {
  margin: 0 0 var(--space-xs);
  font-size: 1rem;
}

input,
textarea {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  padding: var(--space-sm);
  font: inherit;
}

button {
  border: none;
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--color-primary);
  color: #fff;
}

.inline-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.result-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  background: var(--color-bg);
}

.result-card h2 {
  margin: 0 0 var(--space-xs);
}

.result-hint {
  margin: 0 0 var(--space-sm);
  color: var(--color-text-secondary);
  font-size: 0.85rem;
}

.result-card pre {
  margin: 0;
  padding: var(--space-md);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  overflow: auto;
  max-height: 300px;
  font-size: 12px;
}

@media (max-width: 900px) {
  .director-page {
    padding: var(--space-md);
  }

  .cards-grid {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
  }

  .project-bar {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
