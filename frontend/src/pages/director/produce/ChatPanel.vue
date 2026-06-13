<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { directorChat, directorProduce, directorReferenceImages, directorScript } from '@/api/director'
import { createProject, getProjectBrain, getProjectWorkspace } from '@/api/workbench'
import { useTaskPoller } from '@/composables/useTaskPoller'
import type { ChatMessage } from '@/composables/useDirectorSession'

interface ChatItem extends ChatMessage {
  id?: string
  pending?: boolean
  animate?: boolean
}

interface TaskDonePayload {
  status: string
  result: any
  error: string
}

const session = inject<any>('session')
const poller = useTaskPoller()
const inputText = ref('')
const busy = ref(false)
const lastStageText = ref('')

const outputOptions = ref({
  need_advice: true,
  need_reference_images: true,
  need_storyboard: true,
  need_video: true,
})

const STAGES = ['整理需求', '提取设定', '生成分镜', '润色细节']
const POLL_TIMEOUT_MS = 10 * 60 * 1000
const MAX_CHAT_CONTEXT_MESSAGES = 12
const MAX_CHAT_MESSAGE_CHARS = 2000
const MAX_CHAT_CONTEXT_CHARS = 12000

const messages = computed(() => session.chatMessages.value as ChatItem[])
const stagePercent = computed(() => Math.max(0, Math.min(100, Number(poller.progress.value || 0))))
const activeStage = computed(() => {
  if (!poller.isPolling.value) return Math.min(session.directorStage.value, STAGES.length - 1)
  const p = stagePercent.value
  if (p >= 76) return 3
  if (p >= 51) return 2
  if (p >= 26) return 1
  return 0
})
const stageDetail = computed(() => {
  const text = String(poller.stageText.value || '').trim()
  return text || `当前步骤：${STAGES[activeStage.value] || '处理中'}`
})

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
}

function stringifyDetail(detail: any): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message) return detail.message
    if (typeof detail.error === 'string' && detail.error) {
      if (typeof detail.current === 'number' && typeof detail.limit === 'number') {
        return `${detail.error} (${detail.current}/${detail.limit})`
      }
      return detail.error
    }
    try {
      return JSON.stringify(detail)
    } catch {
      return String(detail)
    }
  }
  return String(detail || '')
}

function parseApiError(error: any): { status: number; message: string; retryAfter: number; concurrent: boolean } {
  const status = Number(error?.response?.status || 0)
  const detail = error?.response?.data?.detail
  const detailError = String(detail?.error || '').toLowerCase()
  const retrySource = detail?.retry_after ?? error?.response?.headers?.['retry-after'] ?? 0
  const retryAfter = Math.max(1, Number(retrySource))
  return {
    status,
    message: stringifyDetail(detail) || error?.message || 'unknown error',
    retryAfter,
    concurrent: detailError.includes('concurrent task limit exceeded'),
  }
}

function pushSystemMessage(content: string) {
  session.chatMessages.value.push({
    id: createId('sys'),
    role: 'system',
    content,
    timestamp: Date.now(),
    animate: true,
  } as ChatItem)
}

function updatePendingMessage(stageText: string, progressValue: number) {
  const pending = [...(session.chatMessages.value as ChatItem[])].reverse().find((x) => x.pending && x.role === 'assistant')
  if (!pending) return
  const stage = String(stageText || '').trim()
  const pct = Math.max(0, Math.min(100, Math.round(progressValue)))
  pending.content = stage ? `导演思考中...\n${stage}（${pct}%）` : '导演思考中...'
}

function replacePendingMessage(placeholderId: string, content: string, meta?: ChatItem['meta']) {
  const idx = messages.value.findIndex((m) => m.id === placeholderId)
  const item: ChatItem = {
    id: createId('assistant'),
    role: 'assistant',
    content,
    timestamp: Date.now(),
    animate: true,
    meta,
  }
  if (idx >= 0) session.chatMessages.value.splice(idx, 1, item)
  else session.chatMessages.value.push(item)
}

function extractReply(result: any, status: string, error: string) {
  if (status === 'timeout') return error
  if (status === 'failed' || status === 'cancelled' || status === 'dead_letter') return `任务失败: ${error || status}`
  if (!result) return '导演暂时没有给出结果，请到任务列表查看详情。'
  if (typeof result === 'string') return result
  if (typeof result?.reply === 'string') return result.reply
  if (typeof result?.response === 'string') return result.response
  if (typeof result?.text === 'string') return result.text
  if (Array.isArray(result?.shot_rows)) return `脚本已生成 ${result.shot_rows.length} 个分镜，右侧分镜将自动刷新。`
  return JSON.stringify(result, null, 2)
}

function compactChatContent(content: unknown) {
  return String(content || '').replace(/\s+/g, ' ').trim().slice(0, MAX_CHAT_MESSAGE_CHARS)
}

function buildChatPayloadMessages() {
  const candidates = messages.value
    .filter((m) => !m.pending && (m.role === 'user' || m.role === 'assistant'))
    .map((m) => ({ role: m.role, content: compactChatContent(m.content) }))
    .filter((m) => m.content)

  const kept: Array<{ role: string; content: string }> = []
  let total = 0
  for (let i = candidates.length - 1; i >= 0; i -= 1) {
    const item = candidates[i]
    if (kept.length && total + item.content.length > MAX_CHAT_CONTEXT_CHARS) break
    kept.unshift(item)
    total += item.content.length
    if (kept.length >= MAX_CHAT_CONTEXT_MESSAGES) break
  }
  return kept
}

function buildProcessMeta(result: any) {
  if (!result || typeof result !== 'object') return undefined
  return {
    drafts: Array.isArray(result.drafts) ? result.drafts : [],
    score: result.score || undefined,
    quality_gate: result.quality_gate || undefined,
    process_trace: result.process_trace || undefined,
    workspace_writes: Array.isArray(result.workspace_writes) ? result.workspace_writes : [],
  }
}

async function refreshWorkspace() {
  if (!session?.projectId?.value) return
  try {
    const { data } = await getProjectWorkspace(session.projectId.value)
    session.projectWorkspace.value = data
    const brain = await getProjectBrain(session.projectId.value)
    session.projectBrain.value = brain.data
  } catch (error: any) {
    pushSystemMessage(`工作区刷新失败: ${parseApiError(error).message}`)
  }
}

function extractCharacterDescription(result: any, fallbackText: string) {
  const fromContinuity = String(result?.continuity?.character_continuity || '').trim()
  return fromContinuity || fallbackText.slice(0, 240)
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function dispatchWithRetry(label: string, dispatch: () => Promise<{ task_id: string }>, maxAttempts = 3) {
  let attempt = 0
  while (attempt < maxAttempts) {
    attempt += 1
    try {
      return await dispatch()
    } catch (error: any) {
      const parsed = parseApiError(error)
      if (parsed.status !== 429 || attempt >= maxAttempts) throw error
      let waitSeconds = parsed.retryAfter > 0 ? parsed.retryAfter : 5
      if (parsed.concurrent && waitSeconds < 8) waitSeconds = 8
      pushSystemMessage(`${label}触发限流，${waitSeconds} 秒后自动重试（${attempt}/${maxAttempts - 1}）`)
      await sleep(waitSeconds * 1000)
    }
  }
  throw new Error(`${label} retry exhausted`)
}

async function waitForTask(taskId: string) {
  poller.start(taskId)
  return await new Promise<TaskDonePayload>((resolve) => {
    const timeout = setTimeout(() => {
      poller.stop()
      clearInterval(timer)
      resolve({ status: 'timeout', result: null, error: '任务轮询超时，请到任务列表查看详情。' })
    }, POLL_TIMEOUT_MS)
    const timer = setInterval(() => {
      const stopped = !poller.isPolling.value
      const hasState = Boolean(poller.status.value || poller.result.value || poller.error.value)
      if (stopped && hasState) {
        clearTimeout(timeout)
        clearInterval(timer)
        resolve({ status: poller.status.value, result: poller.result.value, error: poller.error.value })
      }
    }, 120)
  })
}

async function triggerAutoBranches(done: TaskDonePayload, seedText: string) {
  const gate = done.result?.quality_gate || {}
  const options = outputOptions.value
  if (!session.projectId.value || done.status !== 'done') return

  if (options.need_reference_images) {
    if (gate.allow_reference_images === false) {
      pushSystemMessage(`参考图未自动触发：${gate.reason || '评分未达标'}`)
    } else {
      try {
        const characterDescription = extractCharacterDescription(done.result, seedText)
        const data = await dispatchWithRetry('参考图自动派发', async () => {
          const resp = await directorReferenceImages({
            project_id: session.projectId.value,
            character_description: characterDescription,
            views: ['front', 'side', 'expression_smile', 'full_body'],
          }, { silent: true })
          return resp.data
        }, 5)
        pushSystemMessage(`已自动派发参考图任务：${data.task_id}`)
      } catch (e: any) {
        pushSystemMessage(`参考图自动派发失败：${parseApiError(e).message}`)
      }
    }
  }

  if (options.need_video) {
    if (gate.allow_video_production === false) {
      pushSystemMessage(`视频未自动触发：${gate.reason || '评分未达标'}`)
    } else {
      try {
        const data = await dispatchWithRetry('视频自动派发', async () => {
          const resp = await directorProduce({
            project_id: session.projectId.value,
            provider: 'seedance',
          }, { silent: true })
          return resp.data
        }, 15)
        pushSystemMessage(`已自动派发视频任务：${data.task_id}`)
      } catch (e: any) {
        pushSystemMessage(`视频自动派发失败：${parseApiError(e).message}`)
      }
    }
  }
}

async function runTaskWithPlaceholder(taskId: string, placeholderId: string, seedText: string) {
  session.beginTask()
  try {
    const done = await waitForTask(taskId)
    session.directorStage.value = Math.min(activeStage.value + 1, STAGES.length - 1)
    replacePendingMessage(placeholderId, extractReply(done.result, done.status, done.error), buildProcessMeta(done.result))
    if (done.status === 'done' && done.result?.workspace_writes?.length) {
      const paths = done.result.workspace_writes.map((item: any) => item.path).filter(Boolean).join(' / ')
      pushSystemMessage(`项目文档已更新：${paths}`)
      await refreshWorkspace()
    }
    void triggerAutoBranches(done, seedText)
  } finally {
    session.endTask()
  }
}

watch(() => poller.isPolling.value, (polling) => {
  if (!polling) lastStageText.value = ''
})

watch(
  () => [poller.stageText.value, poller.progress.value, poller.isPolling.value] as const,
  ([stageText, progressValue, polling]) => {
    if (!polling) return
    updatePendingMessage(stageText, Number(progressValue || 0))
    const stage = String(stageText || '').trim()
    if (!stage || stage === lastStageText.value) return
    lastStageText.value = stage
    const pct = Math.max(0, Math.min(100, Math.round(Number(progressValue || 0))))
    pushSystemMessage(`进度：${stage}（${pct}%）`)
  },
)

async function ensureProject(hint: string) {
  if (session.projectId.value) return
  try {
    const { data } = await createProject({ name: hint.slice(0, 10) || '新项目' })
    session.projectId.value = data.project_id
  } catch (e: any) {
    pushSystemMessage(`创建项目失败: ${parseApiError(e).message}`)
    throw e
  }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || busy.value) return
  await ensureProject(text)

  const placeholderId = createId('pending')
  session.chatMessages.value.push({ id: createId('user'), role: 'user', content: text, timestamp: Date.now() } as ChatItem)
  session.chatMessages.value.push({
    id: placeholderId,
    role: 'assistant',
    content: '导演思考中...',
    timestamp: Date.now(),
    pending: true,
  } as ChatItem)

  inputText.value = ''
  busy.value = true
  try {
    const payloadMessages = buildChatPayloadMessages()
    const { data } = await directorChat({
      project_id: session.projectId.value,
      messages: payloadMessages,
      output_options: { ...outputOptions.value },
    })
    await runTaskWithPlaceholder(data.task_id, placeholderId, text)
  } catch (e: any) {
    replacePendingMessage(placeholderId, `错误: ${parseApiError(e).message || '请求失败'}`)
  } finally {
    busy.value = false
  }
}

async function generateScript() {
  if (busy.value) return
  const currentText = inputText.value.trim()
  const historyTopic = messages.value.filter((m) => m.role === 'user').map((m) => m.content).join(' ').trim()
  const topic = currentText || historyTopic || '默认主题'
  await ensureProject(topic)

  if (currentText) {
    session.chatMessages.value.push({
      id: createId('user-script'),
      role: 'user',
      content: currentText,
      timestamp: Date.now(),
    } as ChatItem)
    inputText.value = ''
  }

  const placeholderId = createId('pending-script')
  session.chatMessages.value.push({
    id: placeholderId,
    role: 'assistant',
    content: '导演思考中...',
    timestamp: Date.now(),
    pending: true,
  } as ChatItem)

  busy.value = true
  try {
    const { data } = await directorScript({
      project_id: session.projectId.value,
      topic,
      shot_count: 6,
    })
    session.directorStage.value = 2
    await runTaskWithPlaceholder(data.task_id, placeholderId, topic)
  } catch (e: any) {
    replacePendingMessage(placeholderId, `错误: ${parseApiError(e).message || '脚本生成失败'}`)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="chat-panel card">
    <div class="panel-head">
      <h3>导演对话</h3>
      <span v-if="poller.isPolling.value" class="polling-state">{{ stageDetail }} · {{ stagePercent }}%</span>
    </div>

    <div class="stage-bar">
      <div
        v-for="(stage, idx) in STAGES"
        :key="stage"
        class="stage-step transition-all"
        :class="{ done: idx < activeStage, active: idx === activeStage }"
      >
        <span class="dot" :class="{ 'animate-pulse-glow': idx === activeStage && poller.isPolling.value }"></span>
        <strong>{{ stage }}</strong>
      </div>
    </div>
    <p v-if="poller.isPolling.value" class="stage-detail">当前进度：{{ stageDetail }}</p>

    <div class="messages">
      <div
        v-for="msg in messages"
        :key="msg.id || msg.timestamp"
        class="msg"
        :class="[msg.role, { pending: msg.pending, 'animate-fade-in': msg.animate }]"
      >
        <span class="msg-role">{{ msg.role === 'user' ? '你' : msg.role === 'assistant' ? '导演' : '系统' }}</span>
        <p>{{ msg.content }}</p>

        <div v-if="msg.meta?.score" class="score-card">
          <div class="score-head">
            <strong>导演建议评分</strong>
            <b>{{ msg.meta.score.total }}</b>
          </div>
          <div class="score-items">
            <span>库命中: {{ msg.meta.score.items?.library_hit_quality ?? '-' }}</span>
            <span>连续性: {{ msg.meta.score.items?.continuity_stability ?? '-' }}</span>
            <span>可执行: {{ msg.meta.score.items?.executability ?? '-' }}</span>
            <span>风格贴合: {{ msg.meta.score.items?.style_fit ?? '-' }}</span>
          </div>
          <p v-if="msg.meta.quality_gate?.reason" class="quality-reason">{{ msg.meta.quality_gate.reason }}</p>
        </div>

        <div v-if="msg.meta?.drafts?.length" class="drafts-card">
          <details v-for="draft in msg.meta.drafts" :key="draft.version">
            <summary>{{ draft.title }}</summary>
            <pre>{{ draft.content }}</pre>
          </details>
        </div>

        <div v-if="msg.meta?.workspace_writes?.length" class="workspace-write-card">
          <strong>已写入项目文档</strong>
          <ul>
            <li v-for="item in msg.meta.workspace_writes" :key="`${item.path}-${item.mode}`">
              {{ item.path }} · {{ item.mode || 'append' }} · {{ item.decision_recorded ? '已记忆' : '未记忆' }}
            </li>
          </ul>
        </div>
      </div>
      <div v-if="messages.length === 0" class="empty">输入你的创意需求，先对话再生产。</div>
    </div>

    <div class="options-row">
      <label><input v-model="outputOptions.need_advice" type="checkbox" /> 导演建议</label>
      <label><input v-model="outputOptions.need_storyboard" type="checkbox" /> 分镜</label>
      <label><input v-model="outputOptions.need_reference_images" type="checkbox" /> 参考图</label>
      <label><input v-model="outputOptions.need_video" type="checkbox" /> 视频</label>
    </div>

    <div class="input-row">
      <textarea v-model="inputText" rows="2" placeholder="描述你的创意..." @keydown.ctrl.enter.prevent="sendMessage"></textarea>
      <div class="input-actions">
        <button class="btn-primary transition-all" :disabled="busy" type="button" @click="sendMessage">发送</button>
        <button class="btn-secondary transition-all" :disabled="busy" type="button" @click="generateScript">生成脚本</button>
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

.chat-panel {
  padding: 1rem;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.9rem;
}

h3 {
  margin: 0;
  font-size: 0.96rem;
}

.polling-state,
.stage-detail {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}

.stage-detail {
  margin: -0.1rem 0 0.6rem;
}

.stage-bar {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.4rem;
  margin-bottom: 0.9rem;
}

.stage-step {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.35rem 0.55rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  background: var(--color-bg-secondary);
}

.stage-step .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--color-text-secondary) 40%, transparent);
}

.stage-step strong {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.stage-step.done {
  border-color: color-mix(in srgb, var(--color-success) 55%, var(--color-border));
}

.stage-step.done .dot {
  background: var(--color-success);
}

.stage-step.done strong,
.stage-step.active strong {
  color: var(--color-text);
}

.stage-step.active {
  border-color: color-mix(in srgb, var(--color-primary) 62%, var(--color-border));
  box-shadow: 0 0 10px color-mix(in srgb, var(--color-primary) 28%, transparent);
}

.stage-step.active .dot {
  background: var(--color-primary);
}

.messages {
  min-height: 200px;
  max-height: 60vh;
  overflow: auto;
  margin-bottom: 0.8rem;
  display: grid;
  gap: 0.55rem;
  align-content: start;
}

.msg {
  padding: 0.65rem 0.7rem;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-bg-secondary);
}

.msg.user {
  border-color: color-mix(in srgb, var(--color-primary) 40%, var(--color-border));
}

.msg.system {
  border-color: color-mix(in srgb, var(--color-warning) 35%, var(--color-border));
}

.msg-role {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
}

.msg p {
  margin: 0.2rem 0 0;
  white-space: pre-wrap;
  line-height: 1.5;
}

.score-card,
.drafts-card,
.workspace-write-card {
  margin-top: 0.55rem;
  border-top: 1px dashed var(--color-border);
  padding-top: 0.45rem;
}

.score-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.score-items {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.2rem 0.5rem;
  margin-top: 0.3rem;
  font-size: 0.75rem;
}

.quality-reason {
  margin: 0.35rem 0 0;
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}

.drafts-card pre {
  margin: 0.4rem 0 0;
  white-space: pre-wrap;
  font-size: 0.75rem;
  line-height: 1.45;
}

.workspace-write-card {
  font-size: 0.76rem;
}

.workspace-write-card ul {
  margin: 0.35rem 0 0;
  padding-left: 1rem;
}

.workspace-write-card li {
  margin: 0.16rem 0;
  color: var(--color-text-secondary);
}

.empty {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.options-row {
  display: flex;
  gap: 0.8rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
  font-size: 0.82rem;
}

.input-row textarea {
  width: 100%;
  resize: vertical;
  min-height: 66px;
  background: var(--color-bg-secondary);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 0.55rem 0.65rem;
}

.input-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.55rem;
}

.input-actions button {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 0.42rem 0.85rem;
  color: var(--color-text);
  background: var(--color-bg-secondary);
  cursor: pointer;
}

.input-actions button:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--color-primary) 45%, var(--color-border));
}

.input-actions button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-primary {
  background: color-mix(in srgb, var(--color-primary) 24%, var(--color-bg-secondary));
}
</style>
