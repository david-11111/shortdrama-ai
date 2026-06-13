<script setup lang="ts">
import { ref } from 'vue'
import { retrievePrompt } from '@/api/prompt'

const query = ref('')
const stage = ref<'shot' | 'script' | 'ref_image' | 'repair'>('shot')
const topK = ref(8)
const styleHint = ref('')
const contextHint = ref('')
const filterMode = ref('')
const filterValue = ref('')
const loading = ref(false)
const results = ref<any[]>([])
const elapsed = ref(0)

async function handleRetrieve() {
  if (!query.value.trim()) return
  loading.value = true
  const t0 = Date.now()
  try {
    const { data } = await retrievePrompt({
      query: query.value,
      stage: stage.value,
      top_k: topK.value,
      style_hint: styleHint.value || undefined,
      context_hint: contextHint.value || undefined,
      filter_mode: filterMode.value || undefined,
      filter_value: filterValue.value || undefined,
    })
    results.value = data?.matched || data?.matches || data?.results || []
    elapsed.value = Date.now() - t0
  } finally {
    loading.value = false
  }
}

function scoreClass(score: number) {
  if (score >= 8) return 'score-high'
  if (score >= 5) return 'score-mid'
  return 'score-low'
}
</script>

<template>
  <div class="retrieve-page">
    <header class="header">
      <p class="kicker">Prompt Retrieve</p>
      <h1>提示词检索调试</h1>
    </header>

    <section class="card query-panel">
      <div class="query-grid">
        <input v-model.trim="query" class="query-main" placeholder="输入台词或场景描述..." @keyup.enter="handleRetrieve" />
        <select v-model="stage">
          <option value="shot">shot</option>
          <option value="script">script</option>
          <option value="ref_image">ref_image</option>
          <option value="repair">repair</option>
        </select>
        <input v-model.number="topK" type="number" min="1" max="20" />
        <select v-model="filterMode">
          <option value="">无筛选</option>
          <option value="library_cluster">库群</option>
          <option value="library_family">母库</option>
          <option value="parent_library">父库</option>
          <option value="source_file">源文件</option>
        </select>
        <input v-model.trim="filterValue" placeholder="筛选值" />
        <button class="btn" type="button" :disabled="loading" @click="handleRetrieve">
          {{ loading ? '检索中...' : '检索' }}
        </button>
      </div>
      <div class="context-row">
        <input v-model.trim="styleHint" placeholder="style_hint（可选）" />
        <input v-model.trim="contextHint" placeholder="context_hint（可选）" />
      </div>
    </section>

    <section class="result-head" v-if="results.length">
      命中 {{ results.length }} 条 · 耗时 {{ elapsed }}ms
    </section>

    <section v-if="!results.length && !loading" class="card empty">输入检索条件后开始调试。</section>

    <section v-else class="result-list">
      <article v-for="(item, i) in results" :key="item.id || i" class="card result-item">
        <div class="top-row">
          <strong>[{{ i + 1 }}] {{ item.name || item.title || '未命名条目' }}</strong>
          <span class="score" :class="scoreClass(Number(item.score || 0))">{{ Number(item.score || 0).toFixed(2) }}</span>
        </div>
        <p>{{ item.prompt_text || item.prompt || '-' }}</p>
        <div class="tags">
          <span v-for="tag in (item.tags || []).slice(0, 8)" :key="tag">{{ tag }}</span>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.retrieve-page {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.25rem;
}

.header h1 {
  margin: 0;
  font-size: 1.7rem;
}

.kicker {
  margin: 0 0 4px;
  font-size: 0.75rem;
  color: var(--color-primary);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
}

.query-panel {
  margin-top: 0.9rem;
  padding: 0.8rem;
}

.query-grid {
  display: grid;
  grid-template-columns: 2.8fr 0.8fr 0.55fr 1fr 1fr 0.7fr;
  gap: 0.45rem;
}

.query-main {
  min-width: 0;
}

input,
select {
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  padding: 0 0.6rem;
}

input:focus,
select:focus {
  outline: none;
  border-color: var(--color-primary);
}

.context-row {
  margin-top: 0.45rem;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.45rem;
}

.btn {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  cursor: pointer;
}

.btn:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-primary) 60%, var(--color-border));
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.result-head {
  margin-top: 0.8rem;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.empty {
  margin-top: 0.8rem;
  padding: 1rem;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 0.86rem;
}

.result-list {
  margin-top: 0.8rem;
  display: grid;
  gap: 0.6rem;
}

.result-item {
  padding: 0.75rem;
}

.top-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.8rem;
}

.top-row strong {
  font-size: 0.88rem;
  color: var(--color-text);
}

.score {
  font-size: 0.78rem;
  font-weight: 700;
}

.score-high { color: var(--color-success); }
.score-mid { color: var(--color-warning); }
.score-low { color: var(--color-text-secondary); }

.result-item p {
  margin: 0.4rem 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.5;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.tags span {
  display: inline-block;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.08rem 0.4rem;
  font-size: 0.7rem;
  color: var(--color-text-secondary);
  background: var(--color-bg-secondary);
}

@media (max-width: 1100px) {
  .query-grid {
    grid-template-columns: 1fr 1fr;
  }

  .context-row {
    grid-template-columns: 1fr;
  }
}
</style>
