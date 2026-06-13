import type { MediaCandidate, MediaReview, Shot } from '@/composables/useDirectorSession'

export type ShotNextAction =
  | 'needs_rewrite'
  | 'needs_assets'
  | 'can_generate_image'
  | 'needs_image_review'
  | 'can_generate_video'
  | 'needs_video_review'
  | 'can_edit'
  | 'done'
  | 'blocked'

export type ProductionPhase = 'rewrite' | 'assets' | 'image' | 'image_review' | 'video' | 'video_review' | 'edit' | 'done' | 'blocked'
export type ProductionSeverity = 'info' | 'warning' | 'danger' | 'ready' | 'done'

export interface ShotProductionState {
  next_action: ShotNextAction
  phase: ProductionPhase
  severity: ProductionSeverity
  title: string
  reason: string
  primary_action_label: string
  can_auto_continue: boolean
  blocking_refs: string[]
  review_status: string
}

export interface ProjectProductionState {
  current_phase: ProductionPhase | 'empty'
  primary_next_action: ShotNextAction | 'none'
  blocked_count: number
  ready_count: number
  needs_review_count: number
  can_continue: boolean
  summary: string
}

const ACTION_PRIORITY: ShotNextAction[] = [
  'needs_rewrite',
  'blocked',
  'needs_assets',
  'can_generate_image',
  'needs_image_review',
  'can_generate_video',
  'needs_video_review',
  'can_edit',
  'done',
]

export function deriveShotProductionState(shot: Shot): ShotProductionState {
  const preflight = shot.director_preflight
  const safePrompt = String(preflight?.safe_prompt || '').trim()
  const prompt = String(shot.prompt || '').trim()
  const missingRefs = Array.isArray(preflight?.missing_refs) ? preflight.missing_refs.filter(Boolean) : []
  const imageReview = selectedReview(shot.image_candidates, shot.selected_image)
  const videoReview = selectedReview(shot.video_variants, shot.selected_video)
  const imageReviewStatus = String(imageReview?.status || '').trim()
  const videoReviewStatus = String(videoReview?.status || '').trim()

  if (isFinalDone(shot)) {
    return state('done', 'done', 'done', '已完成', '该分镜已进入成片或完成状态。', '完成', false, missingRefs, videoReviewStatus || imageReviewStatus)
  }
  if (preflight?.risk_level === 'blocked' && safePrompt && safePrompt !== prompt) {
    return state('needs_rewrite', 'rewrite', 'danger', '需要安全改写', '导演前置审查发现高风险，且存在可应用的安全改写版本。', '应用安全改写', false, missingRefs, imageReviewStatus)
  }
  if (preflight?.risk_level === 'blocked') {
    return state('blocked', 'blocked', 'danger', '高风险阻塞', '导演前置审查未通过，当前没有可直接应用的安全改写。', '手动修正', false, missingRefs, imageReviewStatus)
  }
  if (missingRefs.length) {
    return state('needs_assets', 'assets', 'warning', '需要补齐参考资产', `缺少 ${missingRefs.join(', ')} 参考资产。`, '补齐资产', false, missingRefs, imageReviewStatus)
  }
  if (!shot.selected_image) {
    return state('can_generate_image', 'image', 'ready', '可以生成关键帧', '分镜已通过基础检查，但还没有选定关键帧。', '生成关键帧', true, [], imageReviewStatus)
  }
  if (isReviewBlocking(imageReviewStatus)) {
    return state('needs_image_review', 'image_review', 'warning', '需要处理图片审片', `图片审片状态为 ${imageReviewStatus}。`, '处理图片审片', false, [], imageReviewStatus)
  }
  if (!shot.selected_video) {
    return state('can_generate_video', 'video', 'ready', '可以生成视频', '已选定关键帧，可以进入图生视频。', '生成视频', true, [], imageReviewStatus)
  }
  if (isReviewBlocking(videoReviewStatus)) {
    return state('needs_video_review', 'video_review', 'warning', '需要处理视频审片', `视频审片状态为 ${videoReviewStatus}。`, '处理视频审片', false, [], videoReviewStatus)
  }
  return state('can_edit', 'edit', 'ready', '可以进入剪辑', '已有可用于剪辑的视频素材。', '进入成片', true, [], videoReviewStatus || imageReviewStatus)
}

export function deriveProjectProductionState(shots: Shot[]): ProjectProductionState {
  const states = (Array.isArray(shots) ? shots : []).map(deriveShotProductionState)
  if (!states.length) {
    return {
      current_phase: 'empty',
      primary_next_action: 'none',
      blocked_count: 0,
      ready_count: 0,
      needs_review_count: 0,
      can_continue: false,
      summary: '暂无分镜，先生成导演分镜。',
    }
  }

  const primary = [...states].sort((a, b) => ACTION_PRIORITY.indexOf(a.next_action) - ACTION_PRIORITY.indexOf(b.next_action))[0]
  const blockedCount = states.filter((item) => item.severity === 'danger' || item.next_action === 'blocked' || item.next_action === 'needs_rewrite').length
  const readyCount = states.filter((item) => item.can_auto_continue).length
  const needsReviewCount = states.filter((item) => item.next_action === 'needs_image_review' || item.next_action === 'needs_video_review').length

  return {
    current_phase: primary.phase,
    primary_next_action: primary.next_action,
    blocked_count: blockedCount,
    ready_count: readyCount,
    needs_review_count: needsReviewCount,
    can_continue: blockedCount === 0 && readyCount > 0,
    summary: buildProjectSummary(primary, states.length, blockedCount, readyCount, needsReviewCount),
  }
}

function state(
  nextAction: ShotNextAction,
  phase: ProductionPhase,
  severity: ProductionSeverity,
  title: string,
  reason: string,
  primaryActionLabel: string,
  canAutoContinue: boolean,
  blockingRefs: string[],
  reviewStatus: string,
): ShotProductionState {
  return {
    next_action: nextAction,
    phase,
    severity,
    title,
    reason,
    primary_action_label: primaryActionLabel,
    can_auto_continue: canAutoContinue,
    blocking_refs: blockingRefs,
    review_status: reviewStatus || '',
  }
}

function selectedReview(items: Array<string | MediaCandidate> = [], selected: string | null): MediaReview | null {
  const candidate = findCandidate(items, selected)
  if (!candidate) return null
  if (candidate.review) return candidate.review
  const status = String(candidate.review_status || '').trim()
  if (!status && candidate.review_score === undefined) return null
  return { status: status || 'needs_review', score: Number(candidate.review_score || 0), notes: [], actions: [] }
}

function findCandidate(items: Array<string | MediaCandidate> = [], selected: string | null): MediaCandidate | null {
  if (!selected) return null
  for (const item of items) {
    const url = typeof item === 'string' ? item.trim() : String(item?.url || '').trim()
    if (url !== selected) continue
    return typeof item === 'string' ? { url } : item
  }
  return null
}

function isReviewBlocking(status: string) {
  return status === 'regenerate' || status === 'needs_review'
}

function isFinalDone(shot: Shot) {
  const status = String(shot.status || '').toLowerCase()
  return ['done', 'final_done', 'final_exported', 'exported'].includes(status)
}

function buildProjectSummary(primary: ShotProductionState, total: number, blocked: number, ready: number, review: number) {
  if (blocked) return `${blocked}/${total} 个分镜被高风险或安全改写阻塞，下一步：${primary.primary_action_label}。`
  if (review) return `${review}/${total} 个分镜需要审片处理，下一步：${primary.primary_action_label}。`
  if (ready) return `${ready}/${total} 个分镜可以继续自动推进，下一步：${primary.primary_action_label}。`
  return `当前 ${total} 个分镜处于 ${primary.title} 阶段。`
}
