<template>
  <aside class="status-bar">
    <div class="status-block">
      <span>运行状态</span>
      <strong class="status-line"><i :class="`dot-${tone}`"></i>{{ statusLabel }}</strong>
    </div>

    <div class="status-block">
      <span>目标</span>
      <strong class="truncate">{{ snapshot?.run.goal || '等待目标' }}</strong>
    </div>

    <div class="status-block">
      <span>预算</span>
      <strong>{{ spent }}/{{ allowed }}</strong>
      <div class="bar"><i :style="{ width: `${budgetPercent}%` }"></i></div>
    </div>

    <div class="status-block">
      <span>进度</span>
      <strong>{{ completedTasks }}/{{ totalTasks }} 任务</strong>
    </div>

    <div class="status-block">
      <span>耗时</span>
      <strong>{{ elapsed }}</strong>
    </div>

    <div class="status-block">
      <span>生产阶段</span>
      <strong class="truncate">{{ currentStageTitle }}</strong>
      <small :class="{ blocked: gateBlocked }">{{ gateStatus }}</small>
      <small v-if="missingText">缺少：{{ missingText }}</small>
      <small v-if="gateReason">{{ gateReason }}</small>
    </div>

    <div v-if="decisionVisible" class="status-block">
      <span>决策上下文</span>
      <strong class="truncate">{{ decisionTitle }}</strong>
      <small v-if="decisionNext">下一步：{{ decisionNext }}</small>
      <small v-if="decisionReason">{{ decisionReason }}</small>
    </div>
    <div class="status-actions">
      <button type="button" @click="$emit('goHome')">首页</button>
      <button type="button" :disabled="cancelDisabled" @click="$emit('cancelRun')">取消</button>
      <button type="button" @click="$emit('openExpert')">专家后台</button>
      <small>{{ actionHint }}</small>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRunSnapshot } from '@/api/director'

const props = defineProps<{
  snapshot: AgentRunSnapshot | null
  status?: string
  elapsed: string
  canceling?: boolean
}>()

defineEmits<{
  goHome: []
  cancelRun: []
  openExpert: []
}>()

const status = computed(() => props.status || props.snapshot?.run.status || 'loading')
const allowed = computed(() => props.snapshot?.budget.allowed_max_credits || props.snapshot?.budget.estimated_max_credits || 0)
const spent = computed(() => {
  const budget = props.snapshot?.budget
  if (!budget) return 0
  const allowedValue = toNumber(budget.allowed_max_credits || budget.estimated_max_credits)
  const remaining = toNumber(budget.remaining_run_budget)
  if (allowedValue > 0) {
    return Math.max(0, Math.min(allowedValue, allowedValue - remaining))
  }
  return Math.max(
    toNumber(budget.spent_credits),
    toNumber(budget.task_credits_charged),
    toNumber(budget.reserved_credits),
    toNumber(budget.task_credits_reserved),
  )
})
const totalTasks = computed(() => Math.max(props.snapshot?.tasks.length || 0, props.snapshot?.nodes.filter((node) => node.status !== 'pending').length || 0))
const completedTasks = computed(() => (props.snapshot?.tasks || []).filter((task) => ['done', 'completed'].includes(String(task.status))).length)
const currentStage = computed(() => {
  const flow = props.snapshot?.flow || []
  return flow.find((stage) => ['running', 'blocked', 'pending'].includes(stage.status)) || flow[flow.length - 1] || null
})
const currentStageTitle = computed(() => stageLabel(String(currentStage.value?.title || '')))
const isProviderWaiting = computed(() => status.value === 'provider_waiting' || props.snapshot?.run.final_decision === 'provider_waiting')
const gateBlocked = computed(() => !isProviderWaiting.value && (currentStage.value?.gate?.allowed === false || currentStage.value?.status === 'blocked'))
const gateStatus = computed(() => {
  if (!currentStage.value) return '检查中'
  if (isProviderWaiting.value) return '等待 provider 恢复'
  if (gateBlocked.value) return '已阻断'
  if (currentStage.value.gate?.allowed) return '允许执行'
  return stageStatusLabel(String(currentStage.value.status || '检查中'))
})
const missingText = computed(() => {
  if (isProviderWaiting.value) return ''
  return (currentStage.value?.gate?.missing || []).map((item) => missingLabel(String(item))).filter(Boolean).join('、')
})
const gateReason = computed(() => {
  if (isProviderWaiting.value) return providerWaitingText.value
  return currentStage.value?.gate?.allowed === false ? reasonLabel(String(currentStage.value.gate.reason || '')) : ''
})
const providerWaitingText = computed(() => props.snapshot?.run.summary || 'Provider 暂时繁忙，剩余视频会自动等待恢复或重试。')
const decisionContext = computed(() => props.snapshot?.decision_context || null)
const pendingAction = computed(() => {
  const value = decisionContext.value?.pending_action
  return value && typeof value === 'object' ? value : null
})
const decisionVisible = computed(() => Boolean(decisionTitle.value || decisionNext.value || decisionReason.value))
const decisionTitle = computed(() => {
  if (decisionContext.value?.awaiting_user === 'confirm' && pendingAction.value) {
    return `等待确认：${actionLabel(String(pendingAction.value.action || decisionContext.value.next_action || ''))}`
  }
  if (decisionContext.value?.blocked_by?.length) return '等待前置条件'
  if (decisionContext.value?.next_action) return '已压缩当前决策'
  return ''
})
const decisionNext = computed(() => actionLabel(String(decisionContext.value?.next_action || '')))
const decisionReason = computed(() => {
  const blocked = decisionContext.value?.blocked_by || []
  if (blocked.length) return `阻断：${blocked.map((item) => missingLabel(String(item)) || String(item)).join('、')}`
  const recommendation = String(decisionContext.value?.last_recommendation || '').trim()
  if (!recommendation) return ''
  return recommendation.length > 48 ? `${recommendation.slice(0, 48)}...` : recommendation
})
const budgetPercent = computed(() => {
  if (!allowed.value) return 0
  return Math.max(0, Math.min(100, Math.round((spent.value / allowed.value) * 100)))
})
const tone = computed(() => {
  if (['completed', 'done'].includes(status.value)) return 'success'
  if (['failed', 'blocked', 'cancelled'].includes(status.value)) return 'error'
  return 'running'
})
const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    dispatching: '调度中',
    running: '运行中',
    provider_waiting: '等待 provider 恢复',
    completed: '完成',
    done: '完成',
    failed: '失败',
    blocked: '阻断',
    cancelled: '已取消',
    loading: '加载中',
  }
  return labels[status.value] || status.value
})
const terminalStatuses = ['completed', 'done', 'failed', 'cancelled']
const cancelDisabled = computed(() => Boolean(props.canceling) || terminalStatuses.includes(String(status.value || '').toLowerCase()))
const actionHint = computed(() => {
  if (props.canceling) return '正在提交取消指令。'
  if (cancelDisabled.value) return '当前状态不能取消。'
  return '取消会停止当前 Agent Run。'
})

function stageLabel(value: string) {
  const text = String(value || '').trim()
  const labels: Record<string, string> = {
    'Read project context': '读取项目上下文',
    'Generate script and storyboard plan': '生成剧本和分镜',
    'Plan visual assets': '规划视觉资产',
    'Lock reusable assets': '锁定可复用资产',
    'Generate keyframes': '生成关键帧',
    generate_keyframes: '生成关键帧',
    'Review keyframes': '确认关键帧',
    'Generate videos': '生成视频',
    generate_videos: '生成视频',
    'Review videos': '确认视频',
    'Produce audio, subtitles and BGM': '制作声音和字幕',
    'Build final cut': '合成成片',
    'Quality check': '质量检查',
    'Write back and review': '回写结果',
    dispatching: '派发中',
    running: '运行中',
    completed: '已完成',
    pending: '等待中',
  }
  return labels[text] || text || '等待中'
}

function toNumber(value: unknown) {
  const number = Number(value || 0)
  return Number.isFinite(number) ? number : 0
}

function stageStatusLabel(value: string) {
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '执行中',
    completed: '已完成',
    blocked: '已阻断',
  }
  return labels[value] || value || '检查中'
}

function missingLabel(value: string) {
  const labels: Record<string, string> = {
    shot_rows: '剧本/分镜',
    selected_image: '关键帧',
    image_task_failures: '失败的关键帧任务',
    image_tasks_or_selected_images: '关键帧任务',
    image_review_blockers: '未通过审查的关键帧',
    selected_video: '视频片段',
    video_task_failures: '失败的视频任务',
    video_tasks_or_selected_videos: '视频任务',
    video_review_blockers: '未通过审查的视频',
    final_video_url: '成片文件',
    generate_story_plan: '剧本/分镜阶段',
    generate_keyframes: '关键帧阶段',
    review_keyframes: '关键帧确认',
    generate_videos: '视频生成阶段',
    review_videos: '视频确认',
    final_cut: '成片合成',
  }
  return labels[value] || ''
}

function actionLabel(value: string) {
  const labels: Record<string, string> = {
    brain_next: '项目大脑下一步',
    status_query: '状态检查',
    generate_story_plan: '剧本和分镜',
    plan_visual_assets: '视觉资产规划',
    generate_keyframes: '关键帧生成',
    generate_videos: '视频生成',
    plan_final_edit: '剪辑成片',
  }
  return labels[String(value || '').trim()] || ''
}

function reasonLabel(value: string) {
  const labels: Record<string, string> = {
    'Script/storyboard rows must exist before visual assets or keyframes.': '需要先生成剧本和分镜，才能继续生成视觉资产。',
    'At least one selected keyframe is required before video generation.': '需要至少一张已确认关键帧，才能继续生成视频。',
    'Failed keyframe tasks must be resolved before keyframe review.': '有关键帧任务失败，需要先修复后再确认。',
    'Keyframe generation must run before keyframe review.': '需要先执行关键帧生成。',
    'Failed video tasks must be resolved before video review.': '有视频任务未完成，需要先恢复或重试后再确认。',
    'Video generation must run before video review.': '需要先执行视频生成。',
    'At least one selected video is required before audio/final cut.': '需要至少一个视频片段，才能继续合成成片。',
    'A final exported video is required before quality check.': '需要先导出成片，才能进行质量检查。',
    'Keyframe review found shots that must be regenerated before video generation.': '关键帧审查发现不合格镜头，需要先重做关键帧，再进入视频生成。',
    'Video review found clips that must be regenerated before final edit.': '视频审查发现不合格镜头，需要先重做视频片段，再进入剪辑成片。',
  }
  if (value.startsWith('Missing required prior stages:')) return '前置阶段还没有完成。'
  return labels[value] || value
}
</script>

<style scoped>
.status-bar {
  display: grid;
  align-content: start;
  gap: 18px;
  box-sizing: border-box;
  width: 100%;
  min-height: 100vh;
  border-right: 1px solid #30363d;
  background: #0d1117;
  padding: 22px 16px;
}

.status-block {
  display: grid;
  gap: 7px;
}

.status-block span {
  color: #8b949e;
  font-size: 12px;
}

.status-block strong {
  color: #e6edf3;
  font-size: 14px;
}

.status-block small {
  color: #f0c36a;
  font-size: 11px;
  line-height: 1.4;
}

.status-block small.blocked {
  color: #ffb3ad;
}

.status-line {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-line i {
  width: 9px;
  height: 9px;
  border-radius: 999px;
}

.dot-success {
  background: #3fb950;
}

.dot-running {
  background: #d29922;
}

.dot-error {
  background: #f85149;
}

.bar {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: #21262d;
}

.bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #58a6ff, #a371f7);
}

.status-actions {
  display: grid;
  gap: 8px;
  margin-top: 18px;
  border-top: 1px solid #30363d;
  padding-top: 18px;
}

.status-actions small {
  color: #6e7681;
  font-size: 11px;
  line-height: 1.4;
}

button {
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #161b22;
  color: #e6edf3;
  padding: 9px 10px;
  cursor: pointer;
}

button:disabled {
  color: #6e7681;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .status-bar {
    width: auto;
    min-height: 0;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    border-right: 0;
    border-bottom: 1px solid #30363d;
  }

  .status-actions {
    grid-column: 1 / -1;
    grid-template-columns: repeat(3, 1fr);
    margin-top: 0;
  }

  .status-actions small {
    grid-column: 1 / -1;
  }
}
</style>


