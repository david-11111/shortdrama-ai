<template>
  <div class="director-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Director Insight</p>
        <h1>诊断流</h1>
        <p class="page-subtitle">聚焦同步诊断、评估复盘、记忆管理与演化模式。</p>
      </div>
      <div class="header-actions">
        <router-link to="/director" class="btn-link">导演首页</router-link>
        <router-link to="/director/flow" class="btn-link">制作流</router-link>
      </div>
    </header>

    <section class="project-bar">
      <label for="project-id">项目 ID</label>
      <input id="project-id" v-model.trim="projectId" placeholder="可选：用于记忆与评估接口" />
      <button type="button" class="btn-secondary" :disabled="!projectId || loading.memory" @click="loadProjectMemory">
        {{ loading.memory ? '读取中...' : '读取项目记忆' }}
      </button>
      <button type="button" class="btn-secondary" :disabled="loading.patterns" @click="loadPatterns">
        {{ loading.patterns ? '读取中...' : '刷新演化模式' }}
      </button>
    </section>

    <section class="cards-grid">
      <article class="card">
        <h2>标准读取</h2>
        <div class="btn-row">
          <button type="button" class="btn-secondary" :disabled="loading.presets" @click="loadPresets">
            {{ loading.presets ? '加载中...' : '读取 Presets' }}
          </button>
          <button type="button" class="btn-secondary" :disabled="loading.evaluation" @click="loadEvaluation">
            {{ loading.evaluation ? '加载中...' : '读取 Evaluation Standard' }}
          </button>
        </div>
      </article>

      <article class="card">
        <h2>诊断与推荐</h2>
        <textarea v-model.trim="diagnoseQuery" rows="3" placeholder="query（问题描述）" />
        <input v-model.trim="diagnoseStyleHint" placeholder="style_hint（可选）" />
        <input v-model.trim="diagnoseContextHint" placeholder="context_hint（可选）" />
        <input v-model.trim="recommendTaskType" placeholder="recommend 的 task_type（如 director_produce）" />
        <div class="btn-row">
          <button type="button" class="btn-secondary" :disabled="!diagnoseQuery || loading.diagnose" @click="runDiagnose">
            {{ loading.diagnose ? '执行中...' : 'diagnose-task' }}
          </button>
          <button type="button" class="btn-secondary" :disabled="!recommendTaskType || loading.recommend" @click="runRecommend">
            {{ loading.recommend ? '执行中...' : 'recommend-mode' }}
          </button>
          <button type="button" class="btn-secondary" :disabled="!diagnoseQuery || loading.explain" @click="runExplain">
            {{ loading.explain ? '执行中...' : 'explain-decision' }}
          </button>
        </div>
      </article>

      <article class="card">
        <h2>评估与重做</h2>
        <input v-model.trim="evaluateOutputName" placeholder="output_name（可选）" />
        <textarea v-model.trim="evaluateManualFeedback" rows="3" placeholder="manual_feedback（可选）" />
        <div class="btn-row">
          <button type="button" class="btn-secondary" :disabled="!projectId || loading.evaluate" @click="runEvaluate">
            {{ loading.evaluate ? '执行中...' : 'evaluate-run' }}
          </button>
          <button type="button" class="btn-secondary" :disabled="!projectId || loading.rework" @click="runRework">
            {{ loading.rework ? '执行中...' : 'rework-suggest' }}
          </button>
          <button type="button" class="btn-secondary" :disabled="!projectId || loading.recordEvolution" @click="runRecordEvolution">
            {{ loading.recordEvolution ? '执行中...' : 'evolution-record' }}
          </button>
        </div>
      </article>

      <article class="card">
        <h2>项目记忆</h2>
        <textarea
          v-model="projectMemoryInput"
          rows="8"
          placeholder="输入 JSON 对象，作为 profile 更新（POST /director/{project_id}/project-memory）"
        />
        <label class="inline-check">
          <input v-model="projectMemoryForce" type="checkbox" />
          <span>force</span>
        </label>
        <button type="button" class="btn-secondary" :disabled="!projectId || loading.updateMemory" @click="saveProjectMemory">
          {{ loading.updateMemory ? '保存中...' : '保存项目记忆' }}
        </button>
      </article>

      <article class="card">
        <h2>演化模式筛选</h2>
        <input v-model.trim="patternProblemType" placeholder="problem_type（可选）" />
        <input v-model.trim="patternVerdictType" placeholder="verdict_type（可选）" />
        <input v-model.number="patternLimit" type="number" min="1" max="100" placeholder="limit" />
        <button type="button" class="btn-secondary" :disabled="loading.patterns" @click="loadPatterns">
          {{ loading.patterns ? '读取中...' : '查询 patterns' }}
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
  diagnoseTask,
  evaluateRun,
  explainDecision,
  getDirectorPresets,
  getEvaluationStandard,
  getEvolutionPatterns,
  getProjectMemory,
  recordEvolution,
  recommendMode,
  reworkSuggest,
  updateProjectMemory,
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

const diagnoseQuery = ref('')
const diagnoseStyleHint = ref('')
const diagnoseContextHint = ref('')
const recommendTaskType = ref('director_produce')
const evaluateOutputName = ref('director')
const evaluateManualFeedback = ref('')

const projectMemoryInput = ref('{}')
const projectMemoryForce = ref(false)
const patternProblemType = ref('')
const patternVerdictType = ref('')
const patternLimit = ref(20)

const responseText = ref('No response yet.')
const lastAction = ref('')

const loading = ref<Record<string, boolean>>({
  presets: false,
  evaluation: false,
  diagnose: false,
  recommend: false,
  explain: false,
  evaluate: false,
  rework: false,
  recordEvolution: false,
  memory: false,
  updateMemory: false,
  patterns: false,
})

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

async function loadPresets() {
  const { data } = await withLoading('presets', () => getDirectorPresets())
  setResponse('director/presets', data)
}

async function loadEvaluation() {
  const { data } = await withLoading('evaluation', () => getEvaluationStandard())
  setResponse('director/evaluation-standard', data)
}

async function runDiagnose() {
  const { data } = await withLoading('diagnose', () =>
    diagnoseTask({
      query: diagnoseQuery.value,
      style_hint: diagnoseStyleHint.value || undefined,
      context_hint: diagnoseContextHint.value || undefined,
    }),
  )
  setResponse('director/diagnose-task', data)
}

async function runRecommend() {
  const { data } = await withLoading('recommend', () =>
    recommendMode({
      task_type: recommendTaskType.value,
      project_id: projectId.value || undefined,
      query: diagnoseQuery.value || undefined,
      style_hint: diagnoseStyleHint.value || undefined,
      context_hint: diagnoseContextHint.value || undefined,
    }),
  )
  setResponse('director/recommend-mode', data)
}

async function runExplain() {
  const { data } = await withLoading('explain', () =>
    explainDecision({
      query: diagnoseQuery.value,
      project_id: projectId.value || undefined,
      style_hint: diagnoseStyleHint.value || undefined,
      context_hint: diagnoseContextHint.value || undefined,
      task_type: recommendTaskType.value || undefined,
    }),
  )
  setResponse('director/explain-decision', data)
}

async function runEvaluate() {
  const { data } = await withLoading('evaluate', () =>
    evaluateRun({
      project_id: projectId.value,
      output_name: evaluateOutputName.value || undefined,
      style_hint: diagnoseStyleHint.value || undefined,
      context_hint: diagnoseContextHint.value || undefined,
      manual_feedback: evaluateManualFeedback.value || undefined,
    }),
  )
  setResponse('director/evaluate-run', data)
}

async function runRework() {
  const { data } = await withLoading('rework', () =>
    reworkSuggest({
      project_id: projectId.value,
      output_name: evaluateOutputName.value || undefined,
      manual_feedback: evaluateManualFeedback.value || undefined,
    }),
  )
  setResponse('director/rework-suggest', data)
}

async function runRecordEvolution() {
  const { data } = await withLoading('recordEvolution', () =>
    recordEvolution({
      project_id: projectId.value,
      output_name: evaluateOutputName.value || undefined,
      manual_verdict: 'pending',
      manual_notes: evaluateManualFeedback.value || undefined,
    }),
  )
  setResponse('director/evolution/record', data)
}

async function loadProjectMemory() {
  const { data } = await withLoading('memory', () => getProjectMemory(projectId.value))
  setResponse('director/{project_id}/project-memory GET', data)
  projectMemoryInput.value = JSON.stringify(data?.profile || data || {}, null, 2)
}

async function saveProjectMemory() {
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(projectMemoryInput.value || '{}')
  } catch {
    setResponse('project-memory parse error', { error: 'projectMemoryInput is not valid JSON object' })
    return
  }
  const { data } = await withLoading('updateMemory', () =>
    updateProjectMemory(projectId.value, {
      profile: parsed,
      force: projectMemoryForce.value,
    }),
  )
  setResponse('director/{project_id}/project-memory POST', data)
}

async function loadPatterns() {
  const { data } = await withLoading('patterns', () =>
    getEvolutionPatterns({
      project_id: projectId.value || undefined,
      problem_type: patternProblemType.value || undefined,
      verdict_type: patternVerdictType.value || undefined,
      limit: patternLimit.value || undefined,
    }),
  )
  setResponse('director/evolution/patterns', data)
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
  flex-wrap: wrap;
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.project-bar input {
  min-width: 260px;
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

.btn-row {
  display: flex;
  gap: var(--space-xs);
  flex-wrap: wrap;
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

.btn-secondary {
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
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
  max-height: 320px;
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
}
</style>
