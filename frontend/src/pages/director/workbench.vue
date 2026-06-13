<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getDirectorPresets } from '@/api/director'
import { annotateScript, getLibraryFilters, retrievePrompt } from '@/api/prompt'

const route = useRoute()

const presets = ref<Array<{ key: string; name: string; description: string }>>([])
const selectedPreset = ref('')
const filterMode = ref('')
const filterValue = ref('')
const styleHint = ref('')
const contextHint = ref('')

const scriptText = ref('')
const retrieveQuery = ref('')
const loading = ref(false)

const hitItems = ref<Array<Record<string, any>>>([])
const annotateResult = ref<Record<string, any> | null>(null)
const filterOptions = ref<Record<string, any>>({})

onMounted(async () => {
  try {
    const res = await getDirectorPresets()
    presets.value = res.data?.presets || res.data || []
  } catch { /* ignore */ }
  try {
    const res = await getLibraryFilters()
    filterOptions.value = res.data?.modes || {}
  } catch { /* ignore */ }
  if (route.params.projectId) {
    styleHint.value = route.params.projectId as string
  }
})

async function handleAnnotate() {
  if (!scriptText.value.trim()) return
  loading.value = true
  try {
    const res = await annotateScript({
      raw_text: scriptText.value,
      style_hint: styleHint.value,
      context_hint: contextHint.value,
      filter_mode: filterMode.value,
      filter_value: filterValue.value,
    })
    annotateResult.value = res.data
    hitItems.value = res.data?.hit_items || res.data?.matches || []
  } catch (e: any) {
    alert(e?.response?.data?.detail || '标注失败')
  } finally {
    loading.value = false
  }
}

async function handleRetrieve() {
  if (!retrieveQuery.value.trim()) return
  loading.value = true
  try {
    const res = await retrievePrompt({
      query: retrieveQuery.value,
      stage: 'script',
      style_hint: styleHint.value,
      context_hint: contextHint.value,
      filter_mode: filterMode.value,
      filter_value: filterValue.value,
    })
    hitItems.value = res.data?.matches || res.data?.results || []
  } catch (e: any) {
    alert(e?.response?.data?.detail || '检索失败')
  } finally {
    loading.value = false
  }
}

function scoreColor(score: number): string {
  if (score >= 8) return '#22c55e'
  if (score >= 5) return '#eab308'
  return '#94a3b8'
}
</script>

<template>
  <div class="workbench-page">
    <h2>导演工作台</h2>

    <!-- 控制栏 -->
    <div class="control-bar">
      <label>
        预设
        <select v-model="selectedPreset">
          <option value="">全部</option>
          <option v-for="p in presets" :key="p.key" :value="p.key">{{ p.name }}</option>
        </select>
      </label>
      <label>
        筛选模式
        <select v-model="filterMode">
          <option value="">不筛选</option>
          <option value="library_family">库族</option>
          <option value="library_cluster">库群</option>
          <option value="parent_library">父库</option>
          <option value="source_file">源文件</option>
        </select>
      </label>
      <label>
        筛选值
        <input v-model="filterValue" placeholder="筛选值" />
      </label>
      <label>
        风格提示
        <input v-model="styleHint" placeholder="风格提示" />
      </label>
      <label>
        剧情背景
        <input v-model="contextHint" placeholder="剧情背景" />
      </label>
    </div>

    <!-- 三栏布局 -->
    <div class="panels">
      <!-- 左栏：剧本输入 -->
      <div class="panel panel-left">
        <h3>剧本输入</h3>
        <textarea
          v-model="scriptText"
          rows="12"
          placeholder="粘贴剧本文本..."
        ></textarea>
        <button class="btn-primary" :disabled="loading" @click="handleAnnotate">
          {{ loading ? '处理中...' : '一键标注' }}
        </button>
        <div class="retrieve-row">
          <input v-model="retrieveQuery" placeholder="快速检索（一句话）" @keyup.enter="handleRetrieve" />
          <button class="btn-secondary" :disabled="loading" @click="handleRetrieve">检索</button>
        </div>
      </div>

      <!-- 中栏：命中库 -->
      <div class="panel panel-mid">
        <h3>命中库 ({{ hitItems.length }})</h3>
        <div v-if="!hitItems.length" class="empty">暂无命中</div>
        <div v-for="(item, idx) in hitItems" :key="idx" class="hit-card">
          <div class="hit-header">
            <span class="hit-name">{{ item.title || item.name || `#${idx + 1}` }}</span>
            <span class="hit-score" :style="{ color: scoreColor(item.score || 0) }">
              {{ (item.score || 0).toFixed(1) }}
            </span>
          </div>
          <p class="hit-prompt">{{ (item.prompt_text || item.prompt || '').slice(0, 120) }}</p>
          <div class="hit-tags">
            <span v-for="tag in (item.tags || []).slice(0, 5)" :key="tag" class="tag">{{ tag }}</span>
          </div>
        </div>
      </div>

      <!-- 右栏：标注结果 -->
      <div class="panel panel-right">
        <h3>标注结果</h3>
        <div v-if="!annotateResult" class="empty">点击"一键标注"查看结果</div>
        <template v-else>
          <div v-for="scene in (annotateResult.scenes || [])" :key="scene.index" class="scene-card">
            <h4>场景 {{ scene.index }}: {{ scene.heading || '' }}</h4>
            <div v-if="scene.seedance_prompt" class="prompt-block">
              <label>视频提示词</label>
              <p>{{ scene.seedance_prompt }}</p>
            </div>
            <div v-if="scene.ref_prompt" class="prompt-block">
              <label>参考图提示词</label>
              <p>{{ scene.ref_prompt }}</p>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workbench-page { padding: 1.5rem; max-width: 1600px; margin: 0 auto; }
.control-bar { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; padding: 0.75rem; background: var(--bg-secondary, #f8f9fa); border-radius: 8px; }
.control-bar label { display: flex; flex-direction: column; font-size: 0.75rem; color: var(--text-muted, #6b7280); gap: 0.25rem; }
.control-bar select, .control-bar input { padding: 0.4rem 0.6rem; border: 1px solid var(--border, #e5e7eb); border-radius: 4px; font-size: 0.85rem; }
.panels { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; min-height: 500px; }
.panel { background: var(--bg-card, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 8px; padding: 1rem; overflow-y: auto; max-height: 70vh; }
.panel h3 { margin: 0 0 0.75rem; font-size: 0.95rem; }
.panel textarea { width: 100%; resize: vertical; padding: 0.5rem; border: 1px solid var(--border, #e5e7eb); border-radius: 4px; font-size: 0.85rem; }
.btn-primary { margin-top: 0.5rem; padding: 0.5rem 1rem; background: var(--primary, #3b82f6); color: #fff; border: none; border-radius: 4px; cursor: pointer; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { padding: 0.4rem 0.8rem; background: var(--bg-secondary, #f3f4f6); border: 1px solid var(--border, #e5e7eb); border-radius: 4px; cursor: pointer; }
.retrieve-row { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
.retrieve-row input { flex: 1; padding: 0.4rem 0.6rem; border: 1px solid var(--border, #e5e7eb); border-radius: 4px; }
.empty { color: var(--text-muted, #9ca3af); font-size: 0.85rem; text-align: center; padding: 2rem 0; }
.hit-card { padding: 0.6rem; border-bottom: 1px solid var(--border, #f3f4f6); }
.hit-header { display: flex; justify-content: space-between; align-items: center; }
.hit-name { font-weight: 600; font-size: 0.85rem; }
.hit-score { font-weight: 700; font-size: 0.9rem; }
.hit-prompt { font-size: 0.8rem; color: var(--text-muted, #6b7280); margin: 0.25rem 0; line-height: 1.4; }
.hit-tags { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.tag { font-size: 0.7rem; padding: 0.1rem 0.4rem; background: var(--bg-secondary, #f3f4f6); border-radius: 3px; color: var(--text-muted, #6b7280); }
.scene-card { margin-bottom: 1rem; padding: 0.75rem; background: var(--bg-secondary, #f8f9fa); border-radius: 6px; }
.scene-card h4 { margin: 0 0 0.5rem; font-size: 0.85rem; }
.prompt-block { margin-bottom: 0.5rem; }
.prompt-block label { font-size: 0.7rem; color: var(--text-muted, #9ca3af); text-transform: uppercase; }
.prompt-block p { font-size: 0.8rem; margin: 0.2rem 0 0; line-height: 1.4; }
</style>
