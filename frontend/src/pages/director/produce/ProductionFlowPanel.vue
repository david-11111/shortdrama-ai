<script setup lang="ts">
import { computed, inject } from 'vue'
import type { ChatMessage, Shot } from '@/composables/useDirectorSession'
import { deriveProjectProductionState, deriveShotProductionState } from './productionState'

type StageStatus = 'done' | 'current' | 'blocked' | 'waiting'

interface StageItem {
  key: string
  title: string
  subtitle: string
  status: StageStatus
  metric: string
}

const session = inject<any>('session')

const shots = computed<Shot[]>(() => Array.isArray(session?.shots?.value) ? session.shots.value : [])
const messages = computed<ChatMessage[]>(() => Array.isArray(session?.chatMessages?.value) ? session.chatMessages.value : [])
const refImages = computed(() => Array.isArray(session?.refImages?.value) ? session.refImages.value : [])
const projectBrain = computed(() => session?.projectBrain?.value || null)
const activeTasks = computed(() => Number(session?.activeTaskCount?.value || 0))
const shotStates = computed(() => shots.value.map(deriveShotProductionState))
const projectState = computed(() => deriveProjectProductionState(shots.value))

const latestAssistantMeta = computed(() => {
  const latest = [...messages.value].reverse().find((item) => item.role === 'assistant' && item.meta)
  return latest?.meta || {}
})

const qualityGate = computed(() => latestAssistantMeta.value?.quality_gate || {})
const scoreTotal = computed(() => Number(latestAssistantMeta.value?.score?.total || 0))
const productionLedger = computed(() => projectBrain.value?.context?.production_ledger || null)
const brainContext = computed<Record<string, any>>(() => projectBrain.value?.context || {})
const ledgerScenes = computed(() => Array.isArray(productionLedger.value?.scenes) ? productionLedger.value.scenes : [])
const ledgerCurrentScene = computed(() => productionLedger.value?.current_scene || {})
const ledgerPreviousScene = computed(() => productionLedger.value?.previous_scene || {})
const ledgerNextScene = computed(() => productionLedger.value?.next_scene || {})
const ledgerAssetLocks = computed(() => productionLedger.value?.asset_locks || {})
const ledgerQuestions = computed(() => Array.isArray(productionLedger.value?.continuity_questions) ? productionLedger.value.continuity_questions : [])

const directorLedgerPanels = computed(() => [
  createDirectorLedgerPanel(
    'creative-technique',
    '创作技巧账本',
    brainContext.value.creative_technique_ledger,
    [
      { label: '技法覆盖', keys: ['technique_coverage_label', 'technique_coverage', 'coverage_label', 'coverage'] },
      { label: '风格一致', keys: ['style_consistency_label', 'style_consistency_score', 'style_consistency', 'consistency_score'] },
      { label: '镜头策略', keys: ['shot_strategy_label', 'shot_strategy', 'camera_strategy', 'visual_strategy'] },
      { label: '可复用锚点', keys: ['reusable_anchor_label', 'reusable_anchor_count', 'visual_anchor_count', 'anchor_count'] },
    ],
  ),
  createDirectorLedgerPanel(
    'story-continuity',
    '剧情连续账本',
    brainContext.value.story_continuity_ledger,
    [
      { label: '连续性', keys: ['continuity_score_label', 'continuity_score', 'continuity_status', 'score_label'] },
      { label: '角色一致', keys: ['character_consistency_label', 'character_consistency', 'character_lock_status'] },
      { label: '场景承接', keys: ['scene_bridge_label', 'scene_bridge_status', 'scene_bridge'] },
      { label: '待确认点', keys: ['open_question_count', 'continuity_question_count', 'open_questions', 'questions'] },
    ],
  ),
  createDirectorLedgerPanel(
    'cost-risk',
    '成本风控账本',
    brainContext.value.cost_risk_ledger,
    [
      { label: '预算状态', keys: ['budget_status_label', 'budget_status', 'cost_status'] },
      { label: '预估成本', keys: ['estimated_cost_label', 'estimated_cost', 'cost_label'] },
      { label: '重试风险', keys: ['retry_risk_label', 'retry_risk', 'retry_count'] },
      { label: '高危镜头', keys: ['high_risk_shot_label', 'high_risk_shot_count', 'risk_shot_count'] },
    ],
  ),
  createDirectorLedgerPanel(
    'final-quality',
    '成片验收账本',
    brainContext.value.final_quality_ledger,
    [
      { label: '验收状态', keys: ['acceptance_status_label', 'acceptance_status', 'final_status'] },
      { label: '质量评分', keys: ['quality_score_label', 'quality_score', 'score'] },
      { label: '通过率', keys: ['pass_rate_label', 'pass_rate', 'approved_rate'] },
      { label: '待验收', keys: ['pending_review_label', 'pending_review_count', 'pending_count'] },
    ],
  ),
])

const shotStats = computed(() => {
  const total = shots.value.length
  const imageDone = shotStates.value.filter((state) => !['can_generate_image', 'needs_assets', 'needs_rewrite', 'blocked'].includes(state.next_action)).length
  const videoDone = shotStates.value.filter((state) => ['can_edit', 'done'].includes(state.next_action)).length
  const errors = shots.value.filter((shot) => shot.status === 'error' || shot.last_error).length
  const blocked = projectState.value.blocked_count
  const warning = projectState.value.needs_review_count + shotStates.value.filter((state) => state.next_action === 'needs_assets').length
  const refsBound = shots.value.filter((shot) => {
    return Boolean(
      shot.character_refs?.length
      || shot.scene_refs?.length
      || shot.prop_refs?.length
      || shot.costume_refs?.length
      || shot.style_refs?.length,
    )
  }).length
  return { total, imageDone, videoDone, errors, refsBound, blocked, warning }
})

const hasProject = computed(() => Boolean(String(session?.projectId?.value || '').trim()))
const hasBrief = computed(() =>
  messages.value.some((item) => item.role === 'user' && item.content.trim()) ||
  Boolean(projectBrain.value?.goal)
)
const hasStoryboard = computed(() => shotStats.value.total > 0)
const hasRefs = computed(() => refImages.value.some((item: any) => !item.pending && item.url) || shotStats.value.refsBound > 0)
const hasImages = computed(() => shotStats.value.imageDone > 0)
const hasVideos = computed(() => shotStats.value.videoDone > 0)
const hasFinalReady = computed(() => shotStats.value.videoDone >= Math.max(1, Math.ceil(shotStats.value.total * 0.6)))

const stages = computed<StageItem[]>(() => {
  const items: StageItem[] = [
    {
      key: 'brief',
      title: '需求理解',
      subtitle: hasBrief.value ? '已接收创作目标' : '先说明要拍什么、给谁看',
      status: hasBrief.value ? 'done' : 'current',
      metric: hasBrief.value ? '已开始' : '待输入',
    },
    {
      key: 'storyboard',
      title: '导演拆镜',
      subtitle: hasStoryboard.value ? '已有可推进分镜' : '需要生成剧本和镜头结构',
      status: hasStoryboard.value ? 'done' : hasBrief.value ? 'current' : 'waiting',
      metric: `${shotStats.value.total} 镜`,
    },
    {
      key: 'assets',
      title: '视觉资产',
      subtitle: hasRefs.value ? '已有参考图或绑定资产' : '需要角色、场景、道具、风格锚点',
      status: hasRefs.value ? 'done' : hasStoryboard.value ? 'current' : 'waiting',
      metric: hasRefs.value ? `${refImages.value.length + shotStats.value.refsBound} 项` : '待补齐',
    },
    {
      key: 'preflight',
      title: '生成前审查',
      subtitle: preflightSubtitle(),
      status: preflightStatus(),
      metric: shotStats.value.blocked ? `${shotStats.value.blocked} 高危` : scoreTotal.value ? `${scoreTotal.value} 分` : '待审查',
    },
    {
      key: 'image',
      title: '图片生产',
      subtitle: hasImages.value ? '已有可选关键帧' : '通过审查后生成参考图或关键帧',
      status: hasImages.value ? 'done' : canGenerateImages() ? 'current' : 'waiting',
      metric: `${shotStats.value.imageDone}/${shotStats.value.total || 0}`,
    },
    {
      key: 'video',
      title: '视频生产',
      subtitle: hasVideos.value ? '已有视频素材' : '选择关键帧后再生成视频',
      status: hasVideos.value ? 'done' : hasImages.value ? 'current' : 'waiting',
      metric: `${shotStats.value.videoDone}/${shotStats.value.total || 0}`,
    },
    {
      key: 'final',
      title: '剪辑成片',
      subtitle: hasFinalReady.value ? '可以进入最终成片台' : '等待足够可用视频素材',
      status: hasFinalReady.value ? 'current' : 'waiting',
      metric: hasFinalReady.value ? '可剪辑' : '未就绪',
    },
  ]
  return items
})

const currentStage = computed(() => stages.value.find((item) => item.status === 'current') || stages.value[0])

const legacyDirectorSummary = computed(() => {
  if (!hasProject.value) return '先选择或输入项目，AI 导演才能读取上下文并推进生产。'
  if (!hasBrief.value) return '先把拍摄目标说清楚，系统会从需求理解开始组织流程。'
  if (!hasStoryboard.value) return '下一步是让导演拆分镜，把一句需求变成可生成的镜头。'
  if (shotStats.value.errors) return `有 ${shotStats.value.errors} 个镜头失败，需要先查看错误并返修。`
  if (shotStats.value.blocked) return `导演审查发现 ${shotStats.value.blocked} 个高风险分镜，先修正人群、远景看脸或主体不清问题。`
  if (shotStats.value.warning) return `有 ${shotStats.value.warning} 个分镜需要补资产或收紧提示词，再进入批量生成更稳。`
  if (!hasRefs.value) return '下一步补齐视觉锚点，优先角色正脸、主场景、关键道具和风格参考。'
  if (preflightStatus() === 'blocked') return '质量门未通过，先修分镜和资产，不建议直接生成。'
  if (!hasImages.value) return '可以先生成关键帧，优先选择主体明确、人数可控的镜头。'
  if (!hasVideos.value) return '选择满意关键帧后进入图生视频，避免直接把风险镜头送进视频模型。'
  if (!hasFinalReady.value) return '继续补齐视频素材，达到大部分镜头可用后再剪辑成片。'
  return '当前素材已经可以进入剪辑成片阶段。'
})

const directorSummary = computed(() => {
  if (projectBrain.value?.summary) return projectBrain.value.summary
  if (!hasProject.value || !hasBrief.value || !hasStoryboard.value) return legacyDirectorSummary.value
  if (shotStats.value.errors) return legacyDirectorSummary.value
  return projectState.value.summary || legacyDirectorSummary.value
})

const legacyNextAction = computed(() => {
  if (!hasProject.value) return '选择项目'
  if (!hasBrief.value) return '输入拍摄需求'
  if (!hasStoryboard.value) return '生成导演分镜'
  if (shotStats.value.blocked) return '修正高风险分镜'
  if (!hasRefs.value) return '补齐视觉资产'
  if (preflightStatus() === 'blocked') return '修正高风险分镜'
  if (!hasImages.value) return '生成关键帧'
  if (!hasVideos.value) return '生成视频'
  return '进入成片台'
})

const nextAction = computed(() => {
  if (projectBrain.value?.next_action_label) return projectBrain.value.next_action_label
  if (!hasProject.value || !hasBrief.value || !hasStoryboard.value) return legacyNextAction.value
  const primary = shotStates.value.find((item) => item.next_action === projectState.value.primary_next_action)
  return primary?.primary_action_label || legacyNextAction.value
})

function canGenerateImages() {
  return hasStoryboard.value && preflightStatus() !== 'blocked'
}

function preflightStatus(): StageStatus {
  if (!hasStoryboard.value) return 'waiting'
  if (shotStats.value.blocked) return 'blocked'
  if (shotStats.value.warning) return 'current'
  if (qualityGate.value?.allow_video_production || qualityGate.value?.allow_reference_images) return 'done'
  if (qualityGate.value?.reason && qualityGate.value.reason !== '质量门通过') return 'blocked'
  if (scoreTotal.value >= 70) return 'done'
  return 'current'
}

function preflightSubtitle() {
  if (shotStats.value.blocked) return `发现 ${shotStats.value.blocked} 个高风险分镜，暂不建议直接生成`
  if (shotStats.value.warning) return `${shotStats.value.warning} 个分镜需要补资产或改写`
  return qualityGate.value?.reason || '检查脸部、人数、主体、资产和可执行性'
}

function createDirectorLedgerPanel(
  key: string,
  title: string,
  ledger: Record<string, any> | null | undefined,
  metrics: Array<{ label: string; keys: string[] }>,
) {
  const data = isPlainObject(ledger) ? ledger : {}
  const hasData = Object.keys(data).length > 0
  return {
    key,
    title,
    status: hasData ? '已分析' : '等待大脑分析',
    metrics: metrics.map((item) => ({
      label: item.label,
      value: formatLedgerValue(pickLedgerValue(data, item.keys)),
    })),
    action: formatLedgerValue(pickLedgerValue(data, ['next_action_label', 'next_action', 'action', 'recommendation'])),
    risk: formatLedgerValue(pickLedgerValue(data, ['risk_label', 'risk', 'primary_risk', 'risks', 'warnings'])),
  }
}

function pickLedgerValue(source: Record<string, any>, keys: string[]) {
  for (const key of keys) {
    const value = source[key]
    if (hasLedgerValue(value)) return value
  }
  return null
}

function hasLedgerValue(value: any) {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'string') return value.trim().length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}

function isPlainObject(value: any): value is Record<string, any> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function formatLedgerValue(value: any) {
  if (!hasLedgerValue(value)) return '等待大脑分析'
  if (Array.isArray(value)) return value.map((item) => String(item)).slice(0, 2).join(' / ')
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '等待大脑分析'
  if (typeof value === 'boolean') return value ? '已通过' : '未通过'
  if (typeof value === 'object') return String(value.label || value.title || value.summary || '已记录')
  return String(value)
}
</script>

<template>
  <section class="flow-panel">
    <div class="flow-brief">
      <div>
        <p class="eyebrow">AI Director Workflow</p>
        <h3>{{ currentStage.title }}</h3>
        <p>{{ directorSummary }}</p>
      </div>
      <div class="next-action">
        <span>下一步</span>
        <strong>{{ nextAction }}</strong>
        <small v-if="activeTasks">执行中 {{ activeTasks }} 个任务</small>
      </div>
    </div>

    <div class="stage-rail" aria-label="项目生产流程">
      <div v-for="stage in stages" :key="stage.key" class="stage-node" :class="stage.status">
        <div class="stage-top">
          <span class="status-dot"></span>
          <strong>{{ stage.title }}</strong>
          <em>{{ stage.metric }}</em>
        </div>
        <p>{{ stage.subtitle }}</p>
      </div>
    </div>

    <div v-if="productionLedger" class="ledger-panel">
      <div class="ledger-head">
        <div>
          <p class="eyebrow">Production Ledger</p>
          <h4>进度账本</h4>
        </div>
        <strong>{{ productionLedger.completion_percent || 0 }}%</strong>
      </div>
      <div class="ledger-grid">
        <div>
          <span>目标总长</span>
          <strong>{{ productionLedger.target_total_label }}</strong>
        </div>
        <div>
          <span>已生成</span>
          <strong>{{ productionLedger.generated_video_label }}</strong>
        </div>
        <div>
          <span>还差</span>
          <strong>{{ productionLedger.remaining_label }}</strong>
        </div>
        <div>
          <span>当前分钟</span>
          <strong>第 {{ productionLedger.current_minute_start || 0 }}-{{ productionLedger.current_minute_end || 0 }} 分钟</strong>
        </div>
      </div>
      <div class="ledger-scenes">
        <article>
          <span>上一场</span>
          <strong>{{ ledgerPreviousScene.title || '暂无' }}</strong>
          <p>{{ ledgerPreviousScene.summary || '还没有可承接的上一场。' }}</p>
        </article>
        <article class="current">
          <span>当前场</span>
          <strong>{{ ledgerCurrentScene.title || '未定位' }}</strong>
          <p>
            {{ ledgerCurrentScene.summary || '等待分镜生成。' }}
            <em v-if="ledgerCurrentScene.shot_count">
              {{ ledgerCurrentScene.video_done_count }}/{{ ledgerCurrentScene.shot_count }} 视频
            </em>
          </p>
        </article>
        <article>
          <span>下一场</span>
          <strong>{{ ledgerNextScene.title || '待规划' }}</strong>
          <p>{{ ledgerNextScene.summary || '下一场承接点还未形成。' }}</p>
        </article>
      </div>
      <div class="ledger-bottom">
        <div>
          <span>复用锚点</span>
          <strong>{{ ledgerAssetLocks.reusable_total || 0 }}</strong>
          <small>角色/场景/服装/道具/风格</small>
        </div>
        <div>
          <span>场次数</span>
          <strong>{{ ledgerScenes.length }}</strong>
          <small>按第几集第几场聚合</small>
        </div>
        <ul>
          <li v-for="item in ledgerQuestions.slice(0, 4)" :key="item">{{ item }}</li>
        </ul>
      </div>
    </div>

    <div class="director-ledgers" aria-label="总导演账本">
      <article v-for="panel in directorLedgerPanels" :key="panel.key" class="director-ledger">
        <div class="director-ledger-head">
          <h4>{{ panel.title }}</h4>
          <span>{{ panel.status }}</span>
        </div>
        <dl>
          <div v-for="metric in panel.metrics" :key="metric.label">
            <dt>{{ metric.label }}</dt>
            <dd>{{ metric.value }}</dd>
          </div>
        </dl>
        <div class="director-ledger-foot">
          <p>
            <span>下一步</span>
            <strong>{{ panel.action }}</strong>
          </p>
          <p>
            <span>风险</span>
            <strong>{{ panel.risk }}</strong>
          </p>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.flow-panel {
  margin-bottom: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.flow-brief {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  border-bottom: 1px solid var(--color-border);
}

.eyebrow {
  margin: 0 0 0.25rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-primary);
}

.flow-brief h3 {
  margin: 0;
  font-size: 1.05rem;
}

.flow-brief p {
  margin: 0.35rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.55;
}

.next-action {
  min-width: 180px;
  align-self: stretch;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.25rem;
  padding-left: 1rem;
  border-left: 1px solid var(--color-border);
}

.next-action span,
.next-action small {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.next-action strong {
  color: var(--color-text);
  font-size: 1rem;
}

.stage-rail {
  display: grid;
  grid-template-columns: repeat(7, minmax(120px, 1fr));
  gap: 0;
  overflow-x: auto;
}

.stage-node {
  min-height: 112px;
  padding: 0.85rem;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
}

.stage-node:last-child {
  border-right: none;
}

.stage-top {
  display: grid;
  grid-template-columns: 10px 1fr auto;
  align-items: center;
  gap: 0.45rem;
}

.status-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--color-text-secondary);
}

.stage-top strong {
  font-size: 0.82rem;
  color: var(--color-text);
}

.stage-top em {
  font-style: normal;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.stage-node p {
  margin: 0.55rem 0 0 1.45rem;
  color: var(--color-text-secondary);
  font-size: 0.73rem;
  line-height: 1.45;
}

.stage-node.done .status-dot {
  background: var(--color-success);
}

.stage-node.current {
  background: color-mix(in srgb, var(--color-primary) 10%, var(--color-bg-secondary));
  box-shadow: inset 0 3px 0 var(--color-primary);
}

.stage-node.current .status-dot {
  background: var(--color-primary);
}

.stage-node.blocked {
  background: color-mix(in srgb, var(--color-error) 10%, var(--color-bg-secondary));
  box-shadow: inset 0 3px 0 var(--color-error);
}

.stage-node.blocked .status-dot {
  background: var(--color-error);
}

.stage-node.waiting {
  opacity: 0.72;
}

.ledger-panel {
  border-top: 1px solid var(--color-border);
  padding: 1rem;
  background: var(--color-bg);
}

.ledger-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.8rem;
}

.ledger-head h4 {
  margin: 0;
  font-size: 0.98rem;
}

.ledger-head > strong {
  font-size: 1.2rem;
  color: var(--color-primary);
}

.ledger-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.ledger-grid div,
.ledger-bottom > div {
  padding: 0.75rem;
  background: var(--color-bg-secondary);
}

.ledger-grid span,
.ledger-scenes span,
.ledger-bottom span,
.ledger-bottom small {
  display: block;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.ledger-grid strong,
.ledger-bottom strong {
  display: block;
  margin-top: 0.25rem;
  color: var(--color-text);
  font-size: 0.94rem;
}

.ledger-scenes {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-top: 0.8rem;
}

.ledger-scenes article {
  min-height: 104px;
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
}

.ledger-scenes article.current {
  border-color: color-mix(in srgb, var(--color-primary) 45%, var(--color-border));
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-bg-secondary));
}

.ledger-scenes strong {
  display: block;
  margin-top: 0.25rem;
  color: var(--color-text);
  font-size: 0.88rem;
}

.ledger-scenes p {
  margin: 0.45rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.74rem;
  line-height: 1.45;
}

.ledger-scenes em {
  display: block;
  margin-top: 0.35rem;
  font-style: normal;
  color: var(--color-primary);
}

.ledger-bottom {
  display: grid;
  grid-template-columns: 140px 140px minmax(0, 1fr);
  gap: 0.75rem;
  margin-top: 0.8rem;
}

.ledger-bottom ul {
  margin: 0;
  padding: 0.75rem 0.75rem 0.75rem 1.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  font-size: 0.74rem;
  line-height: 1.5;
}

.director-ledgers {
  display: grid;
  grid-template-columns: repeat(4, minmax(180px, 1fr));
  gap: 1px;
  border-top: 1px solid var(--color-border);
  background: var(--color-border);
}

.director-ledger {
  min-width: 0;
  padding: 0.85rem;
  background: var(--color-bg-secondary);
}

.director-ledger-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.7rem;
}

.director-ledger-head h4 {
  margin: 0;
  color: var(--color-text);
  font-size: 0.88rem;
}

.director-ledger-head span {
  flex: 0 0 auto;
  color: var(--color-text-secondary);
  font-size: 0.68rem;
}

.director-ledger dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.7rem;
  margin: 0;
}

.director-ledger dt,
.director-ledger-foot span {
  color: var(--color-text-secondary);
  font-size: 0.68rem;
}

.director-ledger dd {
  margin: 0.16rem 0 0;
  color: var(--color-text);
  font-size: 0.8rem;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.director-ledger-foot {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.45rem;
  margin-top: 0.75rem;
  padding-top: 0.65rem;
  border-top: 1px solid var(--color-border);
}

.director-ledger-foot p {
  display: grid;
  grid-template-columns: 3.2rem minmax(0, 1fr);
  gap: 0.45rem;
  margin: 0;
  align-items: start;
}

.director-ledger-foot strong {
  color: var(--color-text);
  font-size: 0.76rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .flow-brief {
    flex-direction: column;
  }

  .next-action {
    border-left: none;
    border-top: 1px solid var(--color-border);
    padding: 0.75rem 0 0;
  }

  .ledger-grid,
  .ledger-scenes,
  .ledger-bottom {
    grid-template-columns: 1fr;
  }

  .director-ledgers {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .director-ledgers {
    grid-template-columns: 1fr;
  }
}
</style>
