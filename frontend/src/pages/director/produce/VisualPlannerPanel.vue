<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { applyVisualPlanAction, getVisualPlan, updateShotRow } from '@/api/workbench'

type RiskLevel = 'ready' | 'warning' | 'blocked'
type ActionType = 'bind_existing' | 'generate_reference'

interface RecommendedRef {
  asset_id: string
  asset_kind: string
  entity_name: string
  file_url: string
  match_score: number
}

interface AssetAction {
  id: string
  shot_index: number
  kind: string
  label: string
  title: string
  description: string
  action_type: ActionType
  status: string
  target_ref_field: string
  prompt_seed: string
  recommended_asset_ids: string[]
  blocked_reason?: string
}

interface VisualShotPlan {
  shot_index: number
  prompt: string
  required_kinds: string[]
  current_refs: Record<string, string[]>
  missing_kinds: string[]
  qa_score: number
  risk_level: RiskLevel
  suggestions: string[]
  action_items: AssetAction[]
  recommended_refs: Record<string, RecommendedRef[]>
}

const session = inject<any>('session')
const loading = ref(false)
const error = ref('')
const assetSummary = ref<Record<string, { label: string; count: number; ready: number }>>({})
const shotPlans = ref<VisualShotPlan[]>([])
const riskCount = ref(0)
const readyCount = ref(0)
const actionCount = ref(0)
const applyingActionId = ref('')

const orderedSummary = computed(() => {
  const order = ['character', 'scene', 'prop', 'costume', 'style', 'shot_keyframe', 'video_clip']
  return order
    .map((key) => ({ key, ...(assetSummary.value[key] || { label: kindLabel(key), count: 0, ready: 0 }) }))
    .filter((item) => item.count > 0 || ['character', 'scene', 'prop', 'style', 'shot_keyframe'].includes(item.key))
})

async function loadPlan() {
  if (!session?.projectId?.value) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await getVisualPlan(session.projectId.value)
    assetSummary.value = data?.asset_summary || {}
    shotPlans.value = data?.shot_plans || []
    riskCount.value = Number(data?.risk_count || 0)
    readyCount.value = Number(data?.ready_count || 0)
    actionCount.value = Number(data?.action_count || 0)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '视觉规划加载失败'
  } finally {
    loading.value = false
  }
}

function riskLabel(level: RiskLevel) {
  if (level === 'ready') return '可生产'
  if (level === 'warning') return '待补强'
  return '阻塞'
}

function kindLabel(kind: string) {
  const map: Record<string, string> = {
    character: '角色',
    scene: '场景',
    prop: '道具',
    costume: '服化道',
    style: '风格',
    shot_keyframe: '关键帧',
    video_clip: '视频',
  }
  return map[kind] || kind
}

function fieldForKind(kind: string) {
  const map: Record<string, string> = {
    character: 'character_refs',
    scene: 'scene_refs',
    prop: 'prop_refs',
    costume: 'costume_refs',
    style: 'style_refs',
  }
  return map[kind] || ''
}

function recommendedForAction(plan: VisualShotPlan, action: AssetAction) {
  const refs = plan.recommended_refs?.[action.kind] || []
  if (!action.recommended_asset_ids?.length) return refs
  const ids = new Set(action.recommended_asset_ids)
  return refs.filter((item) => ids.has(item.asset_id))
}

async function bindRecommended(plan: VisualShotPlan, kind: string, assetId: string) {
  if (!session?.projectId?.value) return
  const field = fieldForKind(kind)
  if (!field) return
  const current = Array.isArray(plan.current_refs?.[kind]) ? plan.current_refs[kind] : []
  const next = Array.from(new Set([...current, assetId]))
  await updateShotRow(session.projectId.value, Number(plan.shot_index), { [field]: next })
  session.shots.value = (session.shots.value || []).map((shot: any) => {
    if (Number(shot.index) !== Number(plan.shot_index)) return shot
    return { ...shot, [field]: next }
  })
  await loadPlan()
}

async function applyAction(plan: VisualShotPlan, action: AssetAction, assetId?: string) {
  if (!session?.projectId?.value || applyingActionId.value) return
  applyingActionId.value = action.id
  error.value = ''
  try {
    const { data } = await applyVisualPlanAction(session.projectId.value, action.id, assetId ? { asset_id: assetId } : undefined)
    const field = data?.field || fieldForKind(action.kind)
    const refs = Array.isArray(data?.refs) ? data.refs : []
    if (field && refs.length) {
      session.shots.value = (session.shots.value || []).map((shot: any) => {
        if (Number(shot.index) !== Number(plan.shot_index)) return shot
        return { ...shot, [field]: refs }
      })
    }
    await loadPlan()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '资产规划动作执行失败'
  } finally {
    applyingActionId.value = ''
  }
}

onMounted(loadPlan)

watch(
  () => [session?.projectId?.value, session?.shots?.value, session?.refImages?.value],
  () => void loadPlan(),
  { deep: true },
)
</script>

<template>
  <section class="visual-planner">
    <div class="planner-head">
      <div>
        <h3>视觉资产规划</h3>
        <p>按角色、场景、道具、服化道、风格和关键帧检查每个分镜的参考包完整度</p>
      </div>
      <button class="btn-secondary" type="button" :disabled="loading" @click="loadPlan">
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <p v-if="error" class="error-tip">{{ error }}</p>

    <div class="summary-grid">
      <div v-for="item in orderedSummary" :key="item.key" class="summary-item">
        <span>{{ item.label }}</span>
        <strong>{{ item.ready }}/{{ item.count }}</strong>
      </div>
      <div class="summary-item risk">
        <span>风险分镜</span>
        <strong>{{ riskCount }}</strong>
      </div>
      <div class="summary-item action">
        <span>待补资产</span>
        <strong>{{ actionCount }}</strong>
      </div>
      <div class="summary-item ready">
        <span>可生产</span>
        <strong>{{ readyCount }}</strong>
      </div>
    </div>

    <div v-if="!shotPlans.length" class="empty">暂无分镜数据，生成脚本后这里会自动规划视觉参考。</div>

    <div v-else class="shot-plan-list">
      <article v-for="plan in shotPlans" :key="plan.shot_index" class="shot-plan" :class="plan.risk_level">
        <div class="shot-plan-head">
          <strong>#{{ plan.shot_index }}</strong>
          <span>{{ riskLabel(plan.risk_level) }} / {{ plan.qa_score }}</span>
        </div>
        <p class="prompt">{{ plan.prompt }}</p>
        <div class="kind-row">
          <span v-for="kind in plan.required_kinds" :key="kind" :class="{ missing: plan.missing_kinds.includes(kind) }">
            {{ kindLabel(kind) }}
          </span>
        </div>

        <div v-if="plan.action_items?.length" class="action-list">
          <div v-for="action in plan.action_items" :key="action.id" class="action-card">
            <div class="action-head">
              <span>{{ action.label }}</span>
              <strong>{{ action.title }}</strong>
            </div>
            <p>{{ action.description }}</p>
            <p v-if="action.blocked_reason" class="reason">{{ action.blocked_reason }}</p>
            <code v-if="action.prompt_seed">{{ action.prompt_seed }}</code>
            <div v-if="recommendedForAction(plan, action).length" class="recommend-row">
              <button
                v-for="asset in recommendedForAction(plan, action)"
                :key="asset.asset_id"
                class="recommend-btn"
                type="button"
                @click="bindRecommended(plan, action.kind, asset.asset_id)"
              >
                <img v-if="asset.file_url" :src="asset.file_url" :alt="asset.entity_name || asset.asset_id" />
                <small>{{ asset.entity_name || asset.asset_id }}</small>
              </button>
            </div>
            <button
              v-else
              class="btn-ghost btn-ghost--active"
              type="button"
              :disabled="applyingActionId === action.id"
              @click="applyAction(plan, action)"
            >
              {{ applyingActionId === action.id ? '补资产中...' : '自动补资产' }}
            </button>
          </div>
        </div>

        <ul v-else class="suggestions">
          <li v-for="item in plan.suggestions" :key="item">{{ item }}</li>
        </ul>
      </article>
    </div>
  </section>
</template>

<style scoped>
.visual-planner {
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
}

.planner-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

h3 {
  margin: 0;
  font-size: 0.96rem;
}

.planner-head p {
  margin: 0.25rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.74rem;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
  gap: 0.45rem;
  margin-bottom: 0.75rem;
}

.summary-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  padding: 0.45rem;
}

.summary-item span {
  display: block;
  color: var(--color-text-secondary);
  font-size: 0.68rem;
}

.summary-item strong {
  display: block;
  margin-top: 0.15rem;
  color: var(--color-text);
  font-size: 0.92rem;
}

.summary-item.risk strong {
  color: var(--color-error);
}

.summary-item.action strong {
  color: #d97706;
}

.summary-item.ready strong {
  color: var(--color-success);
}

.shot-plan-list {
  display: grid;
  gap: 0.55rem;
}

.shot-plan {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 0.6rem;
  background: var(--color-bg-secondary);
}

.shot-plan.blocked {
  border-color: color-mix(in srgb, var(--color-error) 55%, var(--color-border));
}

.shot-plan.warning {
  border-color: color-mix(in srgb, #f59e0b 55%, var(--color-border));
}

.shot-plan.ready {
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
}

.shot-plan-head,
.action-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.82rem;
}

.shot-plan-head span,
.action-head span {
  color: var(--color-text-secondary);
}

.prompt {
  margin: 0.35rem 0;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  line-height: 1.45;
}

.kind-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.kind-row span {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 0.12rem 0.35rem;
  font-size: 0.68rem;
  color: var(--color-text);
}

.kind-row .missing {
  color: #fff;
  border-color: color-mix(in srgb, var(--color-error) 55%, var(--color-border));
  background: color-mix(in srgb, var(--color-error) 24%, transparent);
}

.action-list {
  display: grid;
  gap: 0.45rem;
  margin-top: 0.55rem;
}

.action-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg);
  padding: 0.55rem;
}

.action-card p {
  margin: 0.35rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.7rem;
  line-height: 1.45;
}

.action-card .reason {
  color: var(--color-error);
}

.action-card code {
  display: block;
  margin-top: 0.4rem;
  padding: 0.35rem;
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  font-size: 0.68rem;
  line-height: 1.45;
  white-space: normal;
}

.suggestions {
  margin: 0.45rem 0 0;
  padding-left: 1rem;
  color: var(--color-text-secondary);
  font-size: 0.7rem;
}

.recommend-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-top: 0.45rem;
  color: var(--color-text-secondary);
  font-size: 0.68rem;
}

.recommend-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  max-width: 170px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  padding: 0.18rem 0.35rem;
  cursor: pointer;
}

.recommend-btn:hover {
  border-color: color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
}

.recommend-btn img {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  object-fit: cover;
}

.recommend-btn small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-secondary,
.btn-ghost {
  height: 30px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  padding: 0 0.65rem;
}

.btn-secondary {
  cursor: pointer;
}

.btn-ghost {
  margin-top: 0.45rem;
  color: var(--color-text-secondary);
  cursor: default;
}

.btn-ghost--active {
  color: var(--color-text);
  cursor: pointer;
}

.btn-ghost--active:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
}

.error-tip,
.empty {
  color: var(--color-text-secondary);
  font-size: 0.78rem;
}

.error-tip {
  color: var(--color-error);
}
</style>
