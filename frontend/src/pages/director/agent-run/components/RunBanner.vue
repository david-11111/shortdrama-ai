<template>
  <section v-if="visible" class="banner" :class="`banner-${tone}`">
    <strong>{{ title }}</strong>
    <span>{{ detail }}</span>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import client from '@/api/client'
import type { AgentRunSnapshot } from '@/api/director'

interface SpendLimit {
  daily_credit_limit: number | null
  is_unlimited: boolean
  credits_remaining: number | null
}

const props = defineProps<{
  snapshot: AgentRunSnapshot | null
  elapsed: string
}>()

const spendLimit = ref<SpendLimit | null>(null)
const status = computed(() => props.snapshot?.run.status || '')
const failureText = computed(() =>
  [
    props.snapshot?.run.summary,
    props.snapshot?.run.final_decision,
    ...(props.snapshot?.stream || []).slice(-12).flatMap((item) => [item.title, item.detail, item.text, item.summary, item.reason]),
  ]
    .filter(Boolean)
    .join('\n'),
)
const creditLimitFailure = computed(() => {
  const text = failureText.value
  return (
    ['failed', 'blocked'].includes(status.value) &&
    (
      text.includes('User daily credit limit reached') ||
      text.includes('用户每日信用额度已达') ||
      text.includes('credits_to_reserve') ||
      text.includes('daily_credit_limit')
    )
  )
})
const creditsRequired = computed(() => extractCreditsToReserve(failureText.value))
const creditLimitRecovered = computed(() => {
  if (!creditLimitFailure.value || !spendLimit.value) return false
  if (spendLimit.value.is_unlimited) return true
  const remaining = Number(spendLimit.value.credits_remaining ?? 0)
  const required = Number(creditsRequired.value || 0)
  return required > 0 && remaining >= required
})
const visible = computed(() => {
  if (creditLimitRecovered.value) return false
  return ['completed', 'done', 'failed', 'blocked', 'paused', 'waiting_approval', 'provider_waiting', 'dispatching'].includes(status.value)
})
const tone = computed(() => {
  if (['failed', 'blocked'].includes(status.value)) return 'error'
  if (['paused', 'waiting_approval', 'provider_waiting', 'dispatching'].includes(status.value)) return 'warning'
  return hasMissingVideo.value || isStoryPlanComplete.value ? 'warning' : 'success'
})
const completedVideos = computed(() =>
  (props.snapshot?.tasks || []).filter((task) => task.task_type === 'video_gen' && ['done', 'completed'].includes(String(task.status))).length,
)
const outputVideos = computed(() => props.snapshot?.outputs?.videos?.length || 0)
const outputImages = computed(() => props.snapshot?.outputs?.images?.length || 0)
const outputShots = computed(() => props.snapshot?.outputs?.shots?.length || 0)
const requestedProduction = computed(() => props.snapshot?.run.current_phase === 'video_production' || Boolean(props.snapshot?.ledger?.target_duration_sec))
const hasMissingVideo = computed(() =>
  ['completed', 'done'].includes(status.value) && requestedProduction.value && Math.max(completedVideos.value, outputVideos.value) === 0,
)
const isStoryPlanComplete = computed(() =>
  ['completed', 'done'].includes(status.value) &&
  String(props.snapshot?.run.final_decision || '') === 'generate_story_plan' &&
  outputShots.value > 0 &&
  outputImages.value === 0 &&
  outputVideos.value === 0,
)
const title = computed(() => {
  if (tone.value === 'error') return creditLimitFailure.value ? '积分额度不足' : 'Run 失败'
  if (status.value === 'provider_waiting' || props.snapshot?.run.final_decision === 'provider_waiting') return '等待 provider 恢复'
  if (status.value === 'waiting_approval') return '等待确认'
  if (status.value === 'paused') return '已暂停'
  if (isStoryPlanComplete.value) return '需求理解完成，等待下一步'
  if (hasMissingVideo.value) return '关键帧阶段完成，视频未完成'
  return 'Run 完成'
})
const detail = computed(() => {
  const spent = props.snapshot?.budget.spent_credits || 0
  const summary = cleanSummary(props.snapshot?.run.summary || props.snapshot?.run.final_decision || '')
  const videoCount = Math.max(completedVideos.value, outputVideos.value)
  if (creditLimitFailure.value) return creditLimitDetail.value
  if (tone.value === 'error') return summary || '执行链路遇到阻断，请查看红色事件。'
  if (status.value === 'provider_waiting' || props.snapshot?.run.final_decision === 'provider_waiting') return summary || 'Provider 暂时饱和，剩余视频会在恢复后继续重试。'
  if (isStoryPlanComplete.value) return `已生成分镜 ${outputShots.value} 个，尚未生成图片/视频。耗时 ${props.elapsed} / 消耗 ${spent} 积分。`
  if (hasMissingVideo.value) return `已完成图片阶段，但还没有视频产物。耗时 ${props.elapsed} / 消耗 ${spent} 积分。`
  if (tone.value === 'success') return `生成 ${videoCount} 个视频 / 耗时 ${props.elapsed} / 消耗 ${spent} 积分`
  return summary || '等待你的下一步指令。'
})
const creditLimitDetail = computed(() => {
  const required = creditsRequired.value
  const remaining = spendLimit.value?.credits_remaining
  if (remaining != null && required > 0) {
    return `当时需要预留 ${required} 积分，当前今日剩余额度 ${remaining}。请刷新或继续派发。`
  }
  return '当时每日积分额度不足；充值或提额后请刷新或继续派发。'
})

watch(
  creditLimitFailure,
  async (active) => {
    if (!active || spendLimit.value) return
    try {
      const { data } = await client.get<SpendLimit>('/credits/spend-limit', { silent: true })
      spendLimit.value = data
    } catch {
      // If this check fails, keep the original failure banner visible.
    }
  },
  { immediate: true },
)

function extractCreditsToReserve(text: string): number {
  const patterns = [
    /credits_to_reserve['"]?\s*[:：]\s*(\d+)/i,
    /本次需要\s*(\d+)/,
    /需要预留\s*(\d+)/,
  ]
  for (const pattern of patterns) {
    const match = text.match(pattern)
    if (match?.[1]) return Number(match[1]) || 0
  }
  return 0
}

function cleanSummary(value: string): string {
  return value.replace(/^视频制作失败:\s*/i, '').trim()
}
</script>

<style scoped>
.banner {
  display: grid;
  gap: 4px;
  border-bottom: 1px solid #30363d;
  padding: 12px 18px;
}

.banner strong {
  font-size: 14px;
}

.banner span {
  color: #8b949e;
  font-size: 12px;
}

.banner-success {
  background: rgba(63, 185, 80, 0.12);
  color: #9be9a8;
}

.banner-error {
  background: rgba(248, 81, 73, 0.12);
  color: #ffb3ad;
}

.banner-warning {
  background: rgba(210, 153, 34, 0.13);
  color: #e3b341;
}
</style>
