<template>
  <section class="launch-card">
    <h1>Agent Run</h1>

    <label class="fresh-toggle" :class="{ active: createFreshProject }">
      <input
        type="checkbox"
        :checked="createFreshProject"
        @change="$emit('update:createFreshProject', ($event.target as HTMLInputElement).checked)"
      />
      <span>作为新项目启动，不继承历史项目的镜头和产物</span>
    </label>

    <label v-if="!createFreshProject" class="project-picker">
      <select
        v-if="projects.length !== 1"
        :value="projectId"
        :disabled="loadingProjects"
        @change="updateProject(($event.target as HTMLSelectElement).value)"
      >
        <option value="">{{ loadingProjects ? '正在读取项目...' : '选择已有项目继续' }}</option>
        <option v-for="project in projects" :key="project.project_id" :value="project.project_id">
          {{ project.name }} / {{ shortId(project.project_id) }}
        </option>
      </select>
      <div v-else class="single-project">
        {{ projects[0].name }} / {{ shortId(projects[0].project_id) }}
      </div>
    </label>

    <div v-else class="fresh-note">
      将创建全新的项目，并派发完整生产线：剧本分镜、关键帧、视频片段。
    </div>

    <div class="goal-box">
      <textarea
        :value="goal"
        placeholder="描述这次要制作的视频。例：我想做一段30秒的黄金首饰广告视频，电影级别，高级、精致、有光影质感。"
        rows="3"
        @keydown.ctrl.enter.prevent="$emit('start')"
        @keydown.meta.enter.prevent="$emit('start')"
        @input="$emit('update:goal', ($event.target as HTMLTextAreaElement).value)"
      />
      <button
        class="send-button"
        type="button"
        :disabled="creatingRun || (!projectId && !createFreshProject) || !goal.trim()"
        :aria-label="createFreshProject ? '新建并执行完整流程' : '继续当前项目'"
        @click="$emit('start')"
      >
        {{ creatingRun ? '...' : '→' }}
      </button>
    </div>

    <div class="quick-prompts">
      <button
        v-for="prompt in quickPrompts"
        :key="prompt"
        type="button"
        @click="$emit('update:goal', prompt)"
      >
        {{ prompt }}
      </button>
    </div>

    <details class="advanced">
      <summary>预算上限 {{ allowedMaxCredits || 0 }} 积分 / 高级设置</summary>
      <div class="advanced-grid">
        <label>
          <span>预算上限</span>
          <input
            :value="allowedMaxCredits"
            type="number"
            min="0"
            @input="$emit('update:allowedMaxCredits', Number(($event.target as HTMLInputElement).value || 0))"
          />
        </label>
        <label>
          <span>模式</span>
          <select :value="mode" @change="$emit('update:mode', ($event.target as HTMLSelectElement).value as 'step' | 'autopilot')">
            <option value="autopilot">autopilot：完整执行</option>
            <option value="step">step：单步推进</option>
          </select>
        </label>
      </div>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RecentRunItem } from './RecentRuns.vue'

export interface AgentProject {
  project_id: string
  name: string
  status?: string
}

const props = defineProps<{
  projects: AgentProject[]
  loadingProjects: boolean
  creatingRun: boolean
  recentRuns: RecentRunItem[]
  projectId: string
  goal: string
  mode: 'step' | 'autopilot'
  allowedMaxCredits: number
  createFreshProject: boolean
}>()

const emit = defineEmits<{
  'update:projectId': [value: string]
  'update:goal': [value: string]
  'update:mode': [value: 'step' | 'autopilot']
  'update:allowedMaxCredits': [value: number]
  'update:createFreshProject': [value: boolean]
  start: []
  projectChange: []
}>()

const quickPrompts = computed(() => {
  const hasFailed = props.recentRuns.some((run) => ['failed', 'blocked'].includes(run.status))
  return props.createFreshProject
    ? [
        '我想做一段30秒的黄金首饰广告视频，电影级别，小金饰品牌调性，高级、精致、有光影质感。请先生成剧本和分镜，再生成关键帧，最后生成视频片段。',
        '我想做一段30秒的睫毛广告视频，高级美妆质感，近景微距、柔光、干净奢华。请完整执行到视频片段。',
      ]
    : [
        '继续当前项目，检查图片和视频生成进度',
        hasFailed ? '诊断失败镜头并给出修复动作' : '从图片池选择主图并生成视频',
      ]
})

function updateProject(value: string) {
  emit('update:projectId', value)
  emit('projectChange')
}

function shortId(id: string) {
  return id ? id.slice(0, 8) : ''
}
</script>

<style scoped>
.launch-card {
  display: grid;
  gap: 10px;
  width: min(640px, 100%);
  margin: 0 auto;
  text-align: center;
}

h1 {
  margin: 0 0 8px;
  color: #8b949e;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: 0;
}

label {
  text-align: center;
}

label span {
  color: #8b949e;
  font-size: 13px;
}

select,
textarea,
input,
.single-project,
.fresh-note {
  box-sizing: border-box;
  border: 1px solid #30363d;
  background: #1c2128;
  color: #e6edf3;
  font: inherit;
  outline: none;
}

select,
input,
.single-project {
  min-height: 30px;
  border-radius: 8px;
  padding: 0 10px;
  font-size: 12px;
}

.project-picker select,
.single-project {
  width: auto;
  max-width: min(420px, 100%);
  margin: 0 auto 2px;
  color: #8b949e;
}

.fresh-toggle {
  display: inline-flex;
  justify-content: center;
  gap: 8px;
  align-items: center;
  color: #8b949e;
}

.fresh-toggle.active span {
  color: #e6edf3;
}

.fresh-toggle input {
  width: 14px;
  height: 14px;
  min-height: 0;
}

.fresh-note {
  width: fit-content;
  max-width: 100%;
  margin: 0 auto;
  border-radius: 8px;
  padding: 7px 10px;
  color: #8b949e;
  font-size: 12px;
}

.goal-box {
  position: relative;
}

.goal-box textarea {
  width: 100%;
  min-height: 98px;
  max-height: 150px;
  resize: vertical;
  border-radius: 12px;
  padding: 14px 52px 14px 16px;
  line-height: 1.45;
  background: #1c2128;
}

select:focus,
textarea:focus,
input:focus {
  border-color: #58a6ff;
  box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.12);
}

.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
  margin-top: -2px;
}

.quick-prompts button {
  border: 0;
  background: transparent;
  color: #58a6ff;
  padding: 2px 0;
  font-size: 12px;
  cursor: pointer;
}

.quick-prompts button:hover {
  color: #79c0ff;
  text-decoration: underline;
}

.send-button {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid #30363d;
  border-radius: 9px;
  background: #238636;
  color: #ffffff;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.send-button:disabled {
  background: #30363d;
  color: #8b949e;
  cursor: not-allowed;
}

.advanced {
  margin-top: 4px;
  color: #8b949e;
  font-size: 12px;
  text-align: center;
}

.advanced summary {
  width: fit-content;
  margin: 0 auto;
  cursor: pointer;
}

.advanced-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
  text-align: left;
}
</style>
