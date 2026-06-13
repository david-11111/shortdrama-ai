<template>
  <main class="observe-page">
    <!-- 左侧状态栏 -->
    <RunStatusBar
      class="grid-sidebar"
      :snapshot="snapshot"
      :status="effectiveStatus"
      :elapsed="elapsed"
      :canceling="cancellingRun"
      @go-home="goHome"
      @cancel-run="cancelRun"
      @open-expert="openExpert"
    />

    <!-- 中间：事件流/对话 + 输入框 -->
    <section class="grid-center">
      <RunBanner :snapshot="snapshot" :elapsed="elapsed" />

      <div v-if="loading && !snapshot" class="state-box">Loading run snapshot...</div>
      <div v-else-if="error" class="state-box error">{{ error }}</div>

      <div v-else class="center-workspace">
        <div class="workspace-toolbar">
          <div class="view-tabs" aria-label="Agent run view">
            <button type="button" :class="{ active: activeView === 'timeline' }" @click="activeView = 'timeline'">执行链</button>
            <button type="button" :class="{ active: activeView === 'chat' }" @click="activeView = 'chat'">对话</button>
          </div>
          <span class="toolbar-stats">{{ outputSummary }}</span>
        </div>

        <div class="center-flow">
          <ChatStream
            v-if="activeView === 'chat'"
            :messages="chatMessages"
            :goal="snapshot?.run.goal || 'Agent Run'"
            :status="effectiveStatus"
            @refresh="refresh"
          />
          <EventTimeline
            v-else
            :events="timelineEvents"
            :goal="snapshot?.run.goal || 'Agent Run'"
            :status="effectiveStatus"
            :snapshot="snapshot"
            @refresh="refresh"
          />
        </div>
      </div>

      <form class="human-composer" @submit.prevent="submitHumanInstruction">
        <div class="composer-row">
          <select v-model="instructionAction" class="composer-select">
            <option value="">自动</option>
            <option value="generate_story_plan">剧本</option>
            <option value="plan_visual_assets">参考图</option>
            <option value="generate_keyframes">关键帧</option>
            <option value="generate_videos">视频</option>
            <option value="plan_final_edit">剪辑</option>
          </select>
          <textarea
            v-model="humanInstruction"
            :disabled="composerLocked"
            rows="1"
            placeholder="输入指令，Agent 会流式回复你..."
            @keydown.enter.exact.prevent="submitHumanInstruction"
          ></textarea>
          <button type="submit" :disabled="composerLocked || !humanInstruction.trim()">
            {{ submittingInstruction ? '...' : '发送' }}
          </button>
        </div>
        <div v-if="composerNotice || composerError || lastRoutingSummary" class="composer-footer">
          <em v-if="routedActionLabel" class="routing-hint">{{ routedActionLabel }}</em>
          <strong class="composer-state" :class="`state-${composerState}`">{{ composerStateText }}</strong>
          <span v-if="composerError" class="composer-error">{{ composerError }}</span>
          <span v-if="composerNotice" class="composer-notice">{{ composerNotice }}</span>
        </div>
      </form>
    </section>

    <!-- 右侧：成果面板（始终可见） -->
    <aside v-if="showOutputs" class="grid-output">
      <OutputBoard
        :run-id="runId"
        :outputs="snapshot?.outputs || null"
        @refresh="refresh"
      />
      <details class="evidence-fold">
        <summary>证据账本 ({{ evidenceCount }})</summary>
        <EvidenceLayers :layers="snapshot?.evidence_layers || {}" />
      </details>
    </aside>

    <!-- 底部状态栏 -->
    <footer class="grid-statusbar">
      <span>💰 {{ creditBalance }}</span>
      <span>本次: -{{ creditsSpent }}</span>
      <span>完成: {{ outputSummary }}</span>
      <span>⏱ {{ elapsed }}</span>
      <span :class="sseConnected ? 'sse-ok' : 'sse-off'">{{ sseConnected ? '📡 已连接' : '📡 断开' }}</span>
    </footer>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cancelAgentRun, continueAgentRunStep } from '@/api/director'
import ChatStream from './components/ChatStream.vue'
import EvidenceLayers from './components/EvidenceLayers.vue'
import EventTimeline from './components/EventTimeline.vue'
import OutputBoard from './components/OutputBoard.vue'
import RunBanner from './components/RunBanner.vue'
import RunStatusBar from './components/RunStatusBar.vue'
import { mergeAgentRunTimelineEvents } from './timelineEvents'
import { useAgentRunSnapshot } from './composables/useAgentRunSnapshot'
import { useAgentRunStream } from './composables/useAgentRunStream'
import { useChatMessages } from './composables/useChatMessages'

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId || ''))
const now = ref(Date.now())
const humanInstruction = ref('')
const instructionAction = ref('')
const submittingInstruction = ref(false)
const cancellingRun = ref(false)
const composerError = ref('')
const composerNotice = ref('')
const lastRoutingSummary = ref('')
const lastComposerStatus = ref('')
const activeView = ref<'timeline' | 'chat'>('timeline')

const {
  snapshot,
  loading,
  error,
  projectId,
  load,
} = useAgentRunSnapshot()

const runStream = useAgentRunStream()
const chat = useChatMessages(() => runId.value)
let timer: number | undefined
let snapshotRefreshTimer: number | undefined
let snapshotPollTimer: number | undefined
let fallbackAnswerTimer: number | undefined

runStream.setLlmHandlers({
  onStart: chat.handleLlmStreamStart,
  onChunk: chat.handleLlmChunk,
  onEnd: (event) => {
    chat.handleLlmStreamEnd(event)
    // Streaming finished — refresh snapshot to sync outputs/status
    if (snapshotRefreshTimer) window.clearTimeout(snapshotRefreshTimer)
    snapshotRefreshTimer = window.setTimeout(async () => {
      snapshotRefreshTimer = undefined
      if (runId.value) {
        await load(runId.value)
      }
    }, 800)
  },
})

const chatMessages = computed(() => chat.messages.value)
const timelineEvents = computed(() =>
  mergeAgentRunTimelineEvents(snapshot.value?.stream || [], runStream.events.value),
)
const streamStatus = computed(() => runStream.status.value)
const liveEventsForRun = computed(() =>
  runStream.events.value.filter((event) => {
    if (event.run_id !== runId.value) return false
    const visibility = String((event as { visibility?: string }).visibility || '').toLowerCase()
    const phase = String((event as { phase?: string }).phase || '').toLowerCase()
    return visibility !== 'debug' || phase === 'llm_planner'
  }),
)

const outputSummary = computed(() => {
  const outputs = snapshot.value?.outputs
  const summary = (outputs?.summary || {}) as Record<string, unknown>
  const shotCount = Number(summary.shot_count || outputs?.shots?.length || 0)
  const imageCount = Number(summary.image_count || outputs?.images?.length || 0)
  const videoCount = Number(summary.video_count || outputs?.videos?.length || 0)
  return `${shotCount} 镜头 · ${imageCount} 图片 · ${videoCount} 视频`
})
const showOutputs = computed(() => {
  const outputs = snapshot.value?.outputs
  if (!outputs) return evidenceCount.value > 0
  const summary = (outputs.summary || {}) as Record<string, unknown>
  return Boolean(
    outputs.shots?.length ||
    outputs.images?.length ||
    outputs.videos?.length ||
    outputs.keyframe_pool?.length ||
    summary.final_video_url ||
    evidenceCount.value > 0,
  )
})
const creditBalance = computed(() => {
  const budget = snapshot.value?.budget
  if (!budget) return '—'
  return String(budget.remaining_run_budget ?? 0)
})
const creditsSpent = computed(() => String(snapshot.value?.budget?.spent_credits ?? 0))
const sseConnected = computed(() => runStream.connected.value)
const evidenceCount = computed(() => {
  const layers = snapshot.value?.evidence_layers
  if (!layers || typeof layers !== 'object') return 0
  return Object.values(layers).reduce((sum, layer: any) => sum + (layer?.items?.length || 0), 0)
})
const effectiveStatus = computed(() => {
  if (isProviderWaitingSnapshot.value) return 'provider_waiting'
  return streamStatus.value || snapshot.value?.run.status || 'loading'
})
const isProviderWaitingSnapshot = computed(() =>
  snapshot.value?.run.final_decision === 'provider_waiting' ||
  snapshot.value?.run.status === 'provider_waiting' ||
  snapshot.value?.run.current_phase === 'provider_waiting',
)
const runCancelled = computed(() => String(effectiveStatus.value || '').toLowerCase() === 'cancelled')
const runFailed = computed(() => String(effectiveStatus.value || '').toLowerCase() === 'failed')
const decisionBlocked = computed(() => Boolean(snapshot.value?.decision_context?.blocked_by?.length))
const composerLocked = computed(() => submittingInstruction.value || runCancelled.value)
const routedAction = computed(() => instructionAction.value || inferInstructionAction(humanInstruction.value))
const routedActionLabel = computed(() => {
  const labels: Record<string, string> = {
    status_query: '状态查询',
    generate_story_plan: '剧本/分镜',
    plan_visual_assets: '参考图/视觉资产',
    generate_keyframes: '关键帧/出图',
    generate_videos: '视频生成',
    plan_final_edit: '剪辑/成片',
  }
  if (instructionAction.value && labels[instructionAction.value]) return `手动指定：${labels[instructionAction.value]}`
  if (routedAction.value && labels[routedAction.value]) return `关键词命中：${labels[routedAction.value]}`
  if (humanInstruction.value.trim()) return '自动路由：DeepSeek 先判断答复、诊断或派发'
  return lastRoutingSummary.value || '自动路由：等待输入'
})
const composerState = computed(() => {
  if (submittingInstruction.value) return 'running'
  if (composerError.value) return 'failed'
  if (lastComposerStatus.value) return lastComposerStatus.value
  if (runCancelled.value) return 'saved'
  if (runFailed.value) return 'failed'
  const st = String(effectiveStatus.value || '').toLowerCase()
  if (st === 'waiting_for_input') return 'waiting'
  if (humanInstruction.value.trim()) return 'draft'
  if (composerNotice.value) return 'saved'
  return 'idle'
})
const composerStateText = computed(() => {
  if (runCancelled.value) return '运行不可继续'
  if (decisionBlocked.value) return '需先处理前置条件'
  if (runFailed.value) return '可继续修复'
  if (lastComposerStatus.value === 'answered') return '已答复'
  if (lastComposerStatus.value === 'dispatched') return '已派发'
  if (lastComposerStatus.value === 'deferred') return '已暂存'
  if (lastComposerStatus.value === 'rejected') return '已拒绝'
  const st = String(effectiveStatus.value || '').toLowerCase()
  if (st === 'waiting_for_input') return '待补充信息'
  const labels: Record<string, string> = {
    idle: st === 'completed' ? '可输入指令' : '待输入',
    draft: '待发送',
    running: '执行中',
    failed: '失败',
    saved: '已接收',
  }
  return labels[composerState.value]
})

const elapsed = computed(() => {
  const started = snapshot.value?.run.started_at
  if (!started) return '0s'
  const startMs = new Date(started).getTime()
  if (Number.isNaN(startMs)) return '0s'
  const seconds = Math.max(0, Math.floor((now.value - startMs) / 1000))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes <= 0) return `${rest}s`
  return `${minutes}m ${rest}s`
})

watch(
  runId,
  async (value, previous) => {
    if (!value || value === previous) return
    await enterRun(value)
  },
)

watch(
  () => liveEventsForRun.value.length,
  (count, previous) => {
    if (count > previous && runId.value) {
      scheduleSnapshotRefresh()
      const latest = liveEventsForRun.value[liveEventsForRun.value.length - 1]
      if (latest) chat.handleExecutionEvent(latest)
    }
  },
)

onMounted(async () => {
  timer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
  if (runId.value) await enterRun(runId.value)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
  if (snapshotRefreshTimer) window.clearTimeout(snapshotRefreshTimer)
  if (snapshotPollTimer) window.clearInterval(snapshotPollTimer)
  if (fallbackAnswerTimer) window.clearTimeout(fallbackAnswerTimer)
  runStream.stop()
})

async function enterRun(id: string) {
  stopSnapshotPolling()
  if (fallbackAnswerTimer) { window.clearTimeout(fallbackAnswerTimer); fallbackAnswerTimer = undefined }
  runStream.stop()
  runStream.clear()
  chat.clear()
  await load(id)
  chat.loadFromSnapshot(snapshot.value)
  runStream.start(id)
  startSnapshotPolling()
}

async function refresh() {
  if (!runId.value) return
  await load(runId.value)
  chat.loadFromSnapshot(snapshot.value)
  runStream.start(runId.value)
}

async function cancelRun() {
  if (!runId.value || cancellingRun.value) return
  const confirmed = window.confirm('确定取消当前 Agent Run 吗？正在运行的后续派发会停止。')
  if (!confirmed) return
  cancellingRun.value = true
  composerError.value = ''
  try {
    await cancelAgentRun(runId.value)
    composerNotice.value = '已提交取消指令。'
    await refresh()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    composerError.value = typeof detail === 'string'
      ? detail
      : detail?.message || err?.message || '取消 Agent Run 失败'
  } finally {
    cancellingRun.value = false
  }
}

async function submitHumanInstruction() {
  const instruction = humanInstruction.value.trim()
  if (!runId.value || !instruction) return
  submittingInstruction.value = true
  composerError.value = ''
  composerNotice.value = ''
  lastComposerStatus.value = ''
  chat.addUserMessage(instruction)
  const assistantCountBeforeSubmit = chat.assistantMessageCount()
  try {
    const action = routedAction.value
    const payload: Record<string, unknown> = {
      instruction,
      goal: instruction,
      mode: 'step',
      human_intervention: true,
      source_run_id: runId.value,
      action_hint: action,
    }
    if (instructionAction.value) {
      payload.action = action
      payload.continue_action = action
      payload.force_manual_action = true
    }
    const { data } = await continueAgentRunStep(runId.value, payload)
    lastRoutingSummary.value = describeRoutingResult(data)
    lastComposerStatus.value = normalizeComposerStatus(String(data?.status || data?.result?.status || ''))
    humanInstruction.value = ''
    const fallbackAnswer = String(data?.answer || '')
    if (fallbackAnswer) {
      fallbackAnswerTimer = window.setTimeout(() => {
        fallbackAnswerTimer = undefined
        if (!chat.isStreaming.value && chat.assistantMessageCount() <= assistantCountBeforeSubmit) {
          chat.addAssistantMessage(fallbackAnswer)
        }
      }, 1800)
    }
    if (data?.status === 'deferred') {
      composerNotice.value = '指令已接收：当前还有任务运行，系统已写入时间线，完成后再按该路由继续处理。'
    } else if (lastRoutingSummary.value) {
      composerNotice.value = lastRoutingSummary.value
    }
    const nextRunId = String(data?.result?.run_id || data?.run_id || '')
    if (nextRunId && nextRunId !== runId.value) {
      await router.push(`/director/agent-run/${nextRunId}`)
      return
    }
    // Don't refresh immediately — let SSE streaming deliver the reply token-by-token.
    // Snapshot will be refreshed when llm_stream_end arrives or via scheduleSnapshotRefresh.
    scheduleDelayedRefresh()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    composerError.value = typeof detail === 'string'
      ? detail
      : detail?.message || err?.message || '人工指令提交失败'
  } finally {
    submittingInstruction.value = false
  }
}

function scheduleSnapshotRefresh() {
  if (snapshotRefreshTimer) return
  snapshotRefreshTimer = window.setTimeout(async () => {
    snapshotRefreshTimer = undefined
    if (runId.value) {
      try {
        await load(runId.value)
      } catch {
        // Snapshot refresh is secondary; the SSE stream remains the source of live events.
      }
    }
  }, 1500)
}

function scheduleDelayedRefresh() {
  // Wait for streaming to finish before refreshing snapshot.
  // If no streaming starts within 5s, refresh anyway (fallback).
  if (snapshotRefreshTimer) window.clearTimeout(snapshotRefreshTimer)
  snapshotRefreshTimer = window.setTimeout(async () => {
    snapshotRefreshTimer = undefined
    if (runId.value && !chat.isStreaming.value) {
      await load(runId.value)
      chat.loadFromSnapshot(snapshot.value)
    }
  }, 5000)
}

function startSnapshotPolling() {
  stopSnapshotPolling()
  snapshotPollTimer = window.setInterval(async () => {
    if (!runId.value || loading.value) return
    try {
      await load(runId.value)
    } catch {
      // Polling is only for keeping side panels current; visible errors stay on explicit loads.
    }
  }, 3500)
}

function stopSnapshotPolling() {
  if (!snapshotPollTimer) return
  window.clearInterval(snapshotPollTimer)
  snapshotPollTimer = undefined
}

function openExpert() {
  if (projectId.value) {
    window.location.href = `/director/produce/${projectId.value}`
  }
}

function goHome() {
  void router.push('/director/agent-run')
}

function describeRoutingResult(data: any) {
  const routing = data?.routing || data?.result?.routing || {}
  const action = String(routing.resolved_action || data?.followup_action || data?.result?.action || '').trim()
  const source = String(routing.routing_source || '').trim()
  const executor = String(data?.executor || data?.result?.executor || '').trim()
  const status = String(data?.status || data?.result?.status || '').trim()
  const actionText = actionLabel(action)
  const sourceText = routingSourceLabel(source)
  const statusText = responseStatusLabel(status)
  const parts = ['已接入中控']
  if (sourceText) parts.push(sourceText)
  if (actionText) parts.push(`路由到：${actionText}`)
  if (executor) parts.push(`执行器：${executorLabel(executor)}`)
  if (statusText) parts.push(statusText)
  return parts.join(' · ')
}

function normalizeComposerStatus(status: string) {
  const value = status.toLowerCase()
  if (['answered', 'dispatched', 'deferred', 'rejected'].includes(value)) return value
  return value === 'queued' || value === 'running' || value === 'dispatching' ? 'dispatched' : ''
}

function actionLabel(action: string) {
  const labels: Record<string, string> = {
    status_query: '状态查询',
    generate_story_plan: '剧本/分镜',
    plan_visual_assets: '参考图/视觉资产',
    generate_keyframes: '关键帧/出图',
    generate_videos: '视频生成',
    plan_final_edit: '剪辑/成片',
    brain_next: '项目大脑下一步',
  }
  return labels[action] || ''
}

function routingSourceLabel(source: string) {
  const labels: Record<string, string> = {
    manual_selector: '手动指定',
    status_query_rule: '状态规则命中',
    natural_language_rule: '关键词规则命中',
    brain_next_action: '交给项目大脑判断',
    llm_planner: 'DeepSeek 判断',
    control_tool: '中控工具判断',
    semantic_controller: '语义中控判断',
    pending_action_confirm: '确认暂存动作',
  }
  return labels[source] || ''
}

function responseStatusLabel(status: string) {
  const labels: Record<string, string> = {
    answered: '已答复',
    dispatched: '已派发',
    deferred: '已暂存',
    rejected: '已拒绝',
    blocked: '已阻断',
    queued: '已排队',
    running: '执行中',
    completed: '已完成',
    done: '已完成',
    failed: '失败',
  }
  return labels[status] || ''
}

function executorLabel(executor: string) {
  const labels: Record<string, string> = {
    DeepSeekConversation: 'DeepSeek 对话',
    RuntimeController: '运行时中控',
    ProjectBrainExecutor: '项目大脑',
    StatusQueryExecutor: '状态查询',
    OutputDiagnosticExecutor: '成果诊断',
    TaskDiagnosticExecutor: '任务诊断',
    ProviderWritebackDiagnosticExecutor: 'Provider 回写诊断',
    ScriptDiagnosticExecutor: '剧本诊断',
    KeyframePoolDiagnosticExecutor: '图片池诊断',
  }
  return labels[executor] || executor
}

function inferInstructionAction(value: string) {
  const text = value.toLowerCase()
  if (containsAny(text, ['到哪一步', '哪一步', '进度', '状态', '现在做什么', '谁在管', '谁负责', '怎么样了', '看到了吗', '看到了嗎', '没显示', '沒有顯示', '不显示', '不顯示', '显示不了', '破图', '破圖', '加载失败', 'not showing', 'not visible', 'broken image', 'status', 'progress'])) {
    return 'status_query'
  }
  if (containsAny(text, ['剧本', '脚本', '故事', '分镜', '台词', '对白', '修饰', '润色', '重写', '开头', '结尾', 'script', 'story'])) {
    return 'generate_story_plan'
  }
  if (containsAny(text, ['参考图', '参考图片', '视觉资产', '资产', '角色图', '场景图', '产品图', 'seedream', 'reference', 'asset'])) {
    return 'plan_visual_assets'
  }
  if (containsAny(text, ['关键帧', '出图', '图片不行', '画面不行', '首帧', '尾帧', 'keyframe', 'image'])) {
    return 'generate_keyframes'
  }
  if (containsAny(text, ['剪辑', '字幕', '配音', 'bgm', '音乐', '导出', '成片', 'final cut', 'export'])) {
    return 'plan_final_edit'
  }
  if (containsAny(text, ['视频', '成片片段', '运镜', '动作不行', 'seedance', 'kling', 'video'])) {
    return 'generate_videos'
  }
  return ''
}

function containsAny(text: string, keywords: string[]) {
  return keywords.some((keyword) => text.includes(keyword))
}
</script>

<style scoped>
/* === MT5-style grid layout: fixed panels, no page scroll === */
.observe-page {
  --agent-run-sidebar-width: 200px;
  display: grid;
  grid-template-columns: var(--agent-run-sidebar-width) minmax(360px, 1fr) minmax(0, 1.6fr);
  grid-template-rows: minmax(0, 1fr) 24px;
  height: 100dvh;
  overflow: hidden;
  background: #0d1117;
  color: #e6edf3;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
}

/* --- Left sidebar --- */
.grid-sidebar {
  grid-row: 1 / -1;
  grid-column: 1;
  min-height: 0;
  overflow-y: auto;
  border-right: 1px solid #30363d;
}

/* --- Center column: events + composer --- */
.grid-center {
  grid-row: 1;
  grid-column: 2;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-height: 0;
  overflow: hidden;
}

.center-workspace {
  display: grid;
  grid-template-rows: 36px minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
}

.workspace-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 16px;
  border-bottom: 1px solid #21262d;
  background: #0d1117;
}

.view-tabs {
  display: inline-flex;
  border: 1px solid #30363d;
  border-radius: 6px;
  overflow: hidden;
}

.view-tabs button {
  border: 0;
  background: transparent;
  color: #8b949e;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}

.view-tabs button.active {
  background: #1f6feb;
  color: #fff;
}

.toolbar-stats {
  color: #8b949e;
  font-size: 11px;
  margin-left: auto;
}

.center-flow {
  min-height: 0;
  overflow: hidden;
}

.center-flow :deep(.chat-stream),
.center-flow :deep(.timeline-shell) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

/* --- Composer (bottom of center, not fixed) --- */
.human-composer {
  border-top: 1px solid #30363d;
  background: #0d1117;
  padding: 10px 16px;
}

.composer-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px;
  align-items: end;
}

.composer-select {
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #161b22;
  color: #e6edf3;
  padding: 8px 8px;
  font-size: 12px;
}

.composer-row textarea {
  min-height: 36px;
  max-height: 100px;
  resize: vertical;
  border: 1px solid #30363d;
  border-radius: 10px;
  background: #090c10;
  color: #e6edf3;
  padding: 9px 12px;
  font: inherit;
  font-size: 13px;
  line-height: 1.4;
}

.composer-row textarea:focus,
.composer-select:focus {
  border-color: #58a6ff;
  outline: none;
  box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.12);
}

.composer-row button {
  height: 36px;
  border: 1px solid #58a6ff;
  border-radius: 8px;
  background: #1f6feb;
  color: #fff;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.composer-row button:disabled {
  border-color: #30363d;
  background: #21262d;
  color: #6e7681;
  cursor: not-allowed;
}

.composer-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 6px;
  font-size: 11px;
}

.routing-hint { color: #58a6ff; font-style: normal; }
.composer-error { color: #ffb3ad; }
.composer-notice { color: #8ddb8c; }

.composer-state {
  border: 1px solid #30363d;
  border-radius: 999px;
  padding: 2px 7px;
  color: #8b949e;
  font-size: 11px;
}
.state-draft { border-color: rgba(210,153,34,.42); color: #d29922; }
.state-running { border-color: rgba(88,166,255,.46); color: #58a6ff; }
.state-failed { border-color: rgba(248,81,73,.48); color: #ffb3ad; }
.state-saved, .state-answered, .state-dispatched, .state-deferred { border-color: rgba(63,185,80,.42); color: #8ddb8c; }
.state-rejected { border-color: rgba(248,81,73,.48); color: #ffb3ad; }

/* --- Right panel: output + evidence --- */
.grid-output {
  grid-row: 1;
  grid-column: 3;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-height: 0;
  overflow: hidden;
  border-left: 1px solid #30363d;
}

.grid-output :deep(.output-board) {
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  border: 0;
}

.evidence-fold {
  border-top: 1px solid #30363d;
  background: #0d1117;
  max-height: 260px;
  overflow-y: auto;
}

.evidence-fold summary {
  position: sticky;
  top: 0;
  padding: 8px 14px;
  font-size: 12px;
  color: #8b949e;
  cursor: pointer;
  background: #0d1117;
  border-bottom: 1px solid #21262d;
}

.evidence-fold :deep(.evidence-layers) {
  border: 0;
}

/* --- Bottom status bar --- */
.grid-statusbar {
  grid-row: 2;
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 0 14px;
  border-top: 1px solid #30363d;
  background: #010409;
  font-size: 11px;
  color: #8b949e;
}

.sse-ok { color: #3fb950; }
.sse-off { color: #f85149; }

/* --- Shared --- */
.state-box {
  margin: 20px;
  border: 1px solid #30363d;
  border-radius: 8px;
  background: #161b22;
  padding: 18px;
  color: #8b949e;
}
.state-box.error {
  border-color: rgba(248, 81, 73, 0.5);
  color: #ffb3ad;
}

/* --- Responsive: small screens --- */
@media (max-width: 1100px) {
  .observe-page {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(0, 1fr) 24px;
  }
  .grid-sidebar { display: none; }
  .grid-output { display: none; }
  .grid-center { grid-column: 1; }
  .grid-statusbar { grid-column: 1; }
}
</style>
