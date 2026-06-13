<script setup lang="ts">
import { computed, inject } from 'vue'
import type { ChatMessage, ProjectBrain, ProjectWorkspace, Shot } from '@/composables/useDirectorSession'

type TraceTone = 'done' | 'active' | 'warning' | 'blocked' | 'waiting'

interface TraceItem {
  key: string
  title: string
  detail: string
  meta: string
  tone: TraceTone
}

interface DebugRow {
  key: string
  step: string
  input: string
  decision: string
  output: string
  stop: string
}

const props = defineProps<{
  loadingWorkspace?: boolean
  loadingBrain?: boolean
}>()

const session = inject<any>('session')

const workspace = computed<ProjectWorkspace | null>(() => session?.projectWorkspace?.value || null)
const brain = computed<ProjectBrain | null>(() => session?.projectBrain?.value || null)
const shots = computed<Shot[]>(() => Array.isArray(session?.shots?.value) ? session.shots.value : [])
const messages = computed<ChatMessage[]>(() => Array.isArray(session?.chatMessages?.value) ? session.chatMessages.value : [])
const context = computed<Record<string, any>>(() => brain.value?.context || {})
const productionLedger = computed<Record<string, any>>(() => context.value.production_ledger || {})
const creativeLedger = computed<Record<string, any>>(() => context.value.creative_technique_ledger || {})
const continuityLedger = computed<Record<string, any>>(() => context.value.story_continuity_ledger || {})
const costLedger = computed<Record<string, any>>(() => context.value.cost_risk_ledger || {})
const qualityLedger = computed<Record<string, any>>(() => context.value.final_quality_ledger || {})
const contextCoverage = computed<any[]>(() => {
  if (Array.isArray(context.value.context_coverage)) return context.value.context_coverage
  if (Array.isArray(brain.value?.read_files)) return brain.value.read_files
  return []
})
const ledgerMergeAudit = computed<any[]>(() => Array.isArray(context.value.ledger_merge_audit) ? context.value.ledger_merge_audit : [])
const creativeLoweringAudit = computed<any[]>(() => Array.isArray(context.value.creative_lowering_audit) ? context.value.creative_lowering_audit : [])
const continuityHandoffAudit = computed<any[]>(() => Array.isArray(context.value.continuity_handoff_audit) ? context.value.continuity_handoff_audit : [])
const costControlAudit = computed<any[]>(() => Array.isArray(context.value.cost_control_audit) ? context.value.cost_control_audit : [])
const finalDeliveryAudit = computed<any[]>(() => Array.isArray(context.value.final_delivery_audit) ? context.value.final_delivery_audit : [])
const feedbackLoopAudit = computed<any[]>(() => Array.isArray(context.value.feedback_loop_audit) ? context.value.feedback_loop_audit : [])

const readyFiles = computed(() => {
  const files = Array.isArray(workspace.value?.files) ? workspace.value.files : []
  return {
    ready: files.filter((item) => item.exists).length,
    total: files.length,
  }
})

const shotStats = computed(() => {
  const total = shots.value.length
  const imageReady = shots.value.filter((shot) => Boolean(shot.selected_image)).length
  const videoReady = shots.value.filter((shot) => Boolean(shot.selected_video)).length
  const failed = shots.value.filter((shot) => shot.status === 'error' || Boolean(shot.last_error)).length
  return { total, imageReady, videoReady, failed }
})

const latestExecutionMessage = computed(() => {
  return [...messages.value].reverse().find((item) => {
    if (item.role !== 'system') return false
    const text = String(item.content || '')
    return text.includes('已推进') || text.includes('已规划') || text.includes('暂不支持自动执行') || text.includes('继续推进失败')
  })
})

const readFileRows = computed(() => {
  const files = contextCoverage.value.length
    ? contextCoverage.value
    : Array.isArray(workspace.value?.files) ? workspace.value.files : []
  return files.map((file) => ({
    path: file.path,
    state: file.exists ? '已读取' : '缺失',
    size: `${Number(file.size || 0)} B`,
    label: file.label || file.role || '',
    coverage: file.coverage || '',
    parsed: file.parsed,
    consumed: file.consumed,
    parse_status: file.parse_status || '',
    used_by: Array.isArray(file.used_by) ? file.used_by.join(' / ') : '',
    impact_if_missing: file.impact_if_missing || '',
  }))
})

const actionPlan = computed(() => {
  const action = String(brain.value?.next_action || '').trim()
  const map: Record<string, { endpoint: string; operator: string; expected: string; stop: string }> = {
    plan_visual_assets: {
      endpoint: 'POST /projects/{project_id}/brain/continue',
      operator: '规划视觉资产，优先复用角色、场景、服装、道具和风格锚点',
      expected: '写入或绑定 planned_reference / reference assets',
      stop: '资产不足、预算风险过高或缺少可规划分镜时停止',
    },
    generate_keyframes: {
      endpoint: 'POST /projects/{project_id}/brain/continue',
      operator: '按风控策略派发少量关键帧任务',
      expected: '生成 image task，后台回写 selected_image / image_candidates',
      stop: '没有通过审查的镜头、缺参考资产或触发限流时停止',
    },
    generate_videos: {
      endpoint: 'POST /projects/{project_id}/brain/continue',
      operator: '从已选关键帧中挑选一个可执行镜头进入视频生成',
      expected: '生成 video task，后台回写 selected_video / video_variants',
      stop: '没有 selected_image、视频预算风险、正在排队或 provider 返回失败时停止',
    },
    plan_final_edit: {
      endpoint: 'POST /projects/{project_id}/brain/continue',
      operator: '把可用视频素材写入最终剪辑方案',
      expected: '生成 final_edit_plan，供剪辑台读取',
      stop: '视频素材不足、缺 BGM/声音策略或成片验收阻塞时停止',
    },
    open_final_cut: {
      endpoint: 'RouterLink /director/final-cut/{project_id}',
      operator: '进入最终成片台',
      expected: '用户看到已规划素材并可生成预览',
      stop: '没有可剪辑视频素材时停止',
    },
  }
  return map[action] || {
    endpoint: action ? 'POST /projects/{project_id}/brain/continue' : '等待 next_action',
    operator: action ? `执行 ${action}` : '等待大脑给出下一步动作',
    expected: action ? '等待后端返回 writes / queued_count / shot_rows' : '暂无产物',
    stop: '缺少项目、大脑不可继续或动作未支持时停止',
  }
})

const debugRows = computed<DebugRow[]>(() => {
  const missing = normalizeList(brain.value?.missing)
  const risks = normalizeList(brain.value?.risks)
  const blockers = normalizeList(qualityLedger.value.blocking_items || qualityLedger.value.blockers)
  const guardrails = normalizeList(costLedger.value.guardrail_actions || costLedger.value.actions)
  const currentScene = productionLedger.value.current_scene || {}
  const sceneLabel = currentScene.title || productionLedger.value.current_scene_key || '未定位'
  const applied = Number(creativeLedger.value.applied_count || 0)
  const candidates = Number(creativeLedger.value.candidate_count || 0)
  const loweredCovered = creativeLoweringAudit.value.filter((item) => item.coverage === 'covered').length
  const loweredPartial = creativeLoweringAudit.value.filter((item) => item.coverage === 'partial').length
  const loweredMissing = creativeLoweringAudit.value.filter((item) => item.coverage === 'missing').length
  const loweringSummary = creativeLoweringAudit.value.length
    ? `covered=${loweredCovered}；partial=${loweredPartial}；missing=${loweredMissing}`
    : '等待创作技巧下沉审计'
  const coveredLedgerCount = ledgerMergeAudit.value.filter((item) => item.coverage === 'covered').length
  const partialLedgerCount = ledgerMergeAudit.value.filter((item) => item.coverage === 'partial').length
  const ledgerAuditSummary = ledgerMergeAudit.value.length
    ? `covered=${coveredLedgerCount}；partial=${partialLedgerCount}；total=${ledgerMergeAudit.value.length}`
    : '等待账本合并审计'
  const continuityCovered = continuityHandoffAudit.value.filter((item) => item.coverage === 'covered').length
  const continuityPartial = continuityHandoffAudit.value.filter((item) => item.coverage === 'partial').length
  const continuityMissing = continuityHandoffAudit.value.filter((item) => item.coverage === 'missing').length
  const continuityAuditSummary = continuityHandoffAudit.value.length
    ? `covered=${continuityCovered}；partial=${continuityPartial}；missing=${continuityMissing}`
    : '等待剧情承接审计'
  const costCovered = costControlAudit.value.filter((item) => item.coverage === 'covered').length
  const costPartial = costControlAudit.value.filter((item) => item.coverage === 'partial').length
  const costMissing = costControlAudit.value.filter((item) => item.coverage === 'missing').length
  const costAuditSummary = costControlAudit.value.length
    ? `covered=${costCovered}；partial=${costPartial}；missing=${costMissing}`
    : '等待成本风控审计'
  const deliveryCovered = finalDeliveryAudit.value.filter((item) => item.coverage === 'covered').length
  const deliveryPartial = finalDeliveryAudit.value.filter((item) => item.coverage === 'partial').length
  const deliveryMissing = finalDeliveryAudit.value.filter((item) => item.coverage === 'missing').length
  const deliveryAuditSummary = finalDeliveryAudit.value.length
    ? `covered=${deliveryCovered}；partial=${deliveryPartial}；missing=${deliveryMissing}`
    : '等待成片交付审计'
  const feedbackCovered = feedbackLoopAudit.value.filter((item) => item.coverage === 'covered').length
  const feedbackPartial = feedbackLoopAudit.value.filter((item) => item.coverage === 'partial').length
  const feedbackMissing = feedbackLoopAudit.value.filter((item) => item.coverage === 'missing').length
  const feedbackAuditSummary = feedbackLoopAudit.value.length
    ? `covered=${feedbackCovered}；partial=${feedbackPartial}；missing=${feedbackMissing}`
    : '等待回写复盘审计'

  return [
    {
      key: 'read',
      step: '1. 读取上下文',
      input: `project_id=${brain.value?.project_id || workspace.value?.project_id || session?.projectId?.value || '-'}；文件 ${readyFiles.value.ready}/${readyFiles.value.total} 就绪`,
      decision: workspace.value?.ready ? '项目工作区可作为大脑输入' : '缺少工作区文件，不能可靠推进',
      output: readFileRows.value.length
        ? readFileRows.value.map((item) => `${item.path}:${item.coverage || item.state}${item.consumed === false ? ':未参与判断' : ''}`).join(' / ')
        : '等待 PROJECT、memory、分镜、资产文件',
      stop: workspace.value?.ready ? '无' : '工作区未就绪',
    },
    {
      key: 'memory',
      step: '2. 合并记忆与账本',
      input: `production=${hasData(productionLedger.value)}；creative=${hasData(creativeLedger.value)}；continuity=${hasData(continuityLedger.value)}；cost=${hasData(costLedger.value)}；quality=${hasData(qualityLedger.value)}；${ledgerAuditSummary}`,
      decision: firstText([
        ledgerMergeAudit.value.find((item) => item.component === 'production_ledger')?.decision_effect,
        hasData(productionLedger.value) ? `定位到 ${sceneLabel}` : '',
      ], '尚未形成可用进度账本'),
      output: ledgerMergeAudit.value.length
        ? ledgerMergeAudit.value.map((item) => `${item.label || item.component}:${item.coverage}`).join(' / ')
        : `已生成 ${firstText([productionLedger.value.generated_video_label], '0 秒')}；剩余 ${firstText([productionLedger.value.remaining_label], '待计算')}`,
      stop: partialLedgerCount ? '存在 partial 账本，不能把页面显示当成真覆盖。' : '账本缺失时只允许提示补齐，不允许盲目烧图/烧视频',
    },
    {
      key: 'technique',
      step: '3. 映射创作技巧',
      input: `候选技法 ${candidates}；已应用 ${applied}；分镜 ${shotStats.value.total}；${loweringSummary}`,
      decision: firstText([
        creativeLoweringAudit.value.find((item) => item.coverage === 'partial')?.gap,
        creativeLedger.value.technique_coverage_label,
        creativeLedger.value.shot_strategy_label,
      ], '等待把剪辑技法下沉到分镜提示词'),
      output: creativeLoweringAudit.value.length
        ? creativeLoweringAudit.value.map((item) => `${item.label || item.component}:${item.coverage}->${item.execution_boundary || '-'}`).join(' / ')
        : firstText([creativeLedger.value.next_action_label, creativeLedger.value.summary], '需要继续补齐镜头运动、光影、情绪、配音或剪辑节奏策略'),
      stop: creativeLoweringAudit.value.some((item) => item.coverage !== 'covered')
        ? '存在 partial/missing 技巧，不能把页面显示当成真实下沉。'
        : '技法不能直接调用 ffmpeg，必须先变成分镜/素材/剪辑动作',
    },
    {
      key: 'continuity',
      step: '4. 检查剧情承接',
      input: `当前场 ${sceneLabel}；断点 ${Number(continuityLedger.value.gap_count || continuityLedger.value.open_question_count || 0)}；${continuityAuditSummary}`,
      decision: firstText([
        continuityHandoffAudit.value.find((item) => item.coverage === 'partial' || item.coverage === 'missing')?.gap,
        continuityLedger.value.scene_bridge_label,
        continuityLedger.value.continuity_score_label,
      ], '等待确认前后场承接'),
      output: continuityHandoffAudit.value.length
        ? continuityHandoffAudit.value.map((item) => `${item.label || item.component}:${item.coverage}->${Array.isArray(item.consumed_by) && item.consumed_by.length ? item.consumed_by.join('/') : '未进入判断'}`).join(' / ')
        : firstText([continuityLedger.value.next_action_label, continuityLedger.value.summary], '需要明确前一场讲到哪里、下一场接什么'),
      stop: continuityHandoffAudit.value.some((item) => item.coverage !== 'covered')
        ? '存在 partial/missing 承接项，不能证明大脑知道长片位置和前后场关系。'
        : '剧情断点未解时，不应继续生成大量后续镜头',
    },
    {
      key: 'risk',
      step: '5. 成本与风控',
      input: `风险=${firstText([costLedger.value.risk_level, costLedger.value.budget_status], '未评级')}；图片 ${shotStats.value.imageReady}/${shotStats.value.total}；视频 ${shotStats.value.videoReady}/${shotStats.value.total}；${costAuditSummary}`,
      decision: firstText([
        costControlAudit.value.find((item) => item.coverage === 'partial' || item.coverage === 'missing')?.gap,
        guardrails[0],
        costLedger.value.budget_status_label,
      ], '默认按小步推进，避免一次性烧完积分'),
      output: costControlAudit.value.length
        ? costControlAudit.value.map((item) => `${item.label || item.component}:${item.coverage}->${Array.isArray(item.enforced_by) && item.enforced_by.length ? item.enforced_by.join('/') : '未强制'}`).join(' / ')
        : firstText([costLedger.value.next_action_label, costLedger.value.summary], '优先复用资产，只派发必要任务'),
      stop: costControlAudit.value.some((item) => item.coverage !== 'covered')
        ? '存在 partial/missing 风控项，不能证明它会阻止一次性烧积分。'
        : '预算阻塞、缺少参考资产、任务正在执行或 provider 限流时停止',
    },
    {
      key: 'quality',
      step: '6. 成片可交付检查',
      input: `阻塞 ${blockers.length + missing.length + risks.length}；失败镜头 ${shotStats.value.failed}；${deliveryAuditSummary}`,
      decision: firstText([
        finalDeliveryAudit.value.find((item) => item.coverage === 'partial' || item.coverage === 'missing')?.gap,
        blockers[0],
        qualityLedger.value.acceptance_status_label,
      ], '等待成片验收账本'),
      output: finalDeliveryAudit.value.length
        ? finalDeliveryAudit.value.map((item) => `${item.label || item.component}:${item.coverage}->${Array.isArray(item.checked_by) && item.checked_by.length ? item.checked_by.join('/') : '未检查'}`).join(' / ')
        : firstText([qualityLedger.value.next_action_label, qualityLedger.value.summary], '检查视频、配乐、声音、字幕、剪辑方案是否齐全'),
      stop: finalDeliveryAudit.value.some((item) => item.coverage !== 'covered')
        ? '存在 partial/missing 交付项，不能证明视频/声音/BGM/字幕/剪辑方案齐全。'
        : blockers.length || missing.length || risks.length ? [...blockers, ...missing, ...risks].slice(0, 3).join(' / ') : '无',
    },
    {
      key: 'execute',
      step: '7. 发布执行指令',
      input: `next_action=${brain.value?.next_action || '-'}；can_continue=${Boolean(brain.value?.can_continue)}`,
      decision: actionPlan.value.operator,
      output: `${actionPlan.value.endpoint} -> ${actionPlan.value.expected}`,
      stop: actionPlan.value.stop,
    },
    {
      key: 'feedback',
      step: '8. 回写与复盘',
      input: `${latestExecutionMessage.value?.content || '尚未点击继续推进'}；${feedbackAuditSummary}`,
      decision: firstText([
        feedbackLoopAudit.value.find((item) => item.coverage === 'partial' || item.coverage === 'missing')?.gap,
        latestExecutionMessage.value ? '已收到一次执行反馈，页面会刷新 workspace / brain / shots' : '',
      ], '等待真实执行结果'),
      output: feedbackLoopAudit.value.length
        ? feedbackLoopAudit.value.map((item) => `${item.label || item.component}:${item.coverage}->${Array.isArray(item.read_next_by) && item.read_next_by.length ? item.read_next_by.join('/') : '下轮未读取'}`).join(' / ')
        : latestExecutionMessage.value ? '系统事件已写入对话流，并同步到执行轨迹' : '暂无写入',
      stop: feedbackLoopAudit.value.some((item) => item.coverage !== 'covered')
        ? '存在 partial/missing 回写项，不能证明下一轮大脑不会失忆。'
        : latestExecutionMessage.value?.content?.includes('失败') ? latestExecutionMessage.value.content : '无',
    },
  ]
})

const traceItems = computed<TraceItem[]>(() => {
  const missing = Array.isArray(brain.value?.missing) ? brain.value.missing : []
  const risks = Array.isArray(brain.value?.risks) ? brain.value.risks : []
  const blockers = normalizeList(qualityLedger.value.blocking_items || qualityLedger.value.blockers)
  const guardrails = normalizeList(costLedger.value.guardrail_actions || costLedger.value.actions)
  const currentScene = productionLedger.value.current_scene || {}
  const currentSceneLabel = currentScene.title || productionLedger.value.current_scene_key || '未定位'
  const generated = firstText([
    productionLedger.value.generated_video_label,
    productionLedger.value.generated_duration_label,
    productionLedger.value.generated_label,
  ], '暂无生成时长')
  const remaining = firstText([
    productionLedger.value.remaining_label,
    productionLedger.value.remaining_duration_label,
  ], '等待目标总长')

  return [
    {
      key: 'workspace',
      title: '读取项目工作区',
      detail: workspace.value
        ? `项目文档 ${readyFiles.value.ready}/${readyFiles.value.total} 就绪，版本 ${workspace.value.workspace_version || '-'}`
        : '等待选择项目后读取 PROJECT、memory、分镜和资产文件。',
      meta: workspace.value?.ready ? '上下文可用' : props.loadingWorkspace ? '读取中' : '未就绪',
      tone: workspace.value?.ready ? 'done' : props.loadingWorkspace ? 'active' : 'waiting',
    },
    {
      key: 'brain',
      title: '项目大脑分析',
      detail: brain.value
        ? `${brain.value.phase || 'unknown'}：${brain.value.summary || '已完成一次项目状态分析。'}`
        : '等待后端项目大脑返回当前阶段、下一步和风险。',
      meta: brain.value?.analyzed_at ? formatDate(brain.value.analyzed_at) : props.loadingBrain ? '分析中' : '未分析',
      tone: brain.value ? 'done' : props.loadingBrain ? 'active' : 'waiting',
    },
    {
      key: 'progress',
      title: '读取进度账本',
      detail: `当前场：${currentSceneLabel}；已生成 ${generated}，还差 ${remaining}。`,
      meta: `分镜 ${shotStats.value.total} · 图片 ${shotStats.value.imageReady} · 视频 ${shotStats.value.videoReady}`,
      tone: productionLedger.value.current_scene || shotStats.value.total ? 'done' : 'waiting',
    },
    {
      key: 'technique',
      title: '检查创作技巧',
      detail: firstText([
        creativeLoweringAudit.value.find((item) => item.coverage === 'partial')?.gap,
        creativeLedger.value.summary,
        creativeLedger.value.technique_coverage_label,
        creativeLedger.value.shot_strategy_label,
        creativeLedger.value.next_action_label,
      ], '等待大脑把剪辑技巧、镜头运动、光影、情绪和配音规则映射到分镜。'),
      meta: creativeLoweringAudit.value.length
        ? `下沉 ${creativeLoweringAudit.value.filter((item) => item.coverage === 'covered').length}/${creativeLoweringAudit.value.length}`
        : metricPair('已用技法', creativeLedger.value.applied_count, creativeLedger.value.candidate_count),
      tone: creativeLoweringAudit.value.some((item) => item.coverage === 'missing') ? 'warning' : hasData(creativeLedger.value) ? 'done' : 'waiting',
    },
    {
      key: 'continuity',
      title: '检查剧情连续',
      detail: firstText([
        continuityHandoffAudit.value.find((item) => item.coverage === 'partial' || item.coverage === 'missing')?.gap,
        continuityLedger.value.summary,
        continuityLedger.value.current_segment_label,
        continuityLedger.value.scene_bridge_label,
        continuityLedger.value.next_action_label,
      ], '等待大脑确认前一场讲到哪里、当前场承接什么、下一场要埋什么。'),
      meta: continuityHandoffAudit.value.length
        ? `承接 ${continuityHandoffAudit.value.filter((item) => item.coverage === 'covered').length}/${continuityHandoffAudit.value.length}`
        : `断点 ${Number(continuityLedger.value.gap_count || continuityLedger.value.open_question_count || 0)}`,
      tone: continuityHandoffAudit.value.some((item) => item.coverage === 'missing') || Number(continuityLedger.value.gap_count || 0) > 0 ? 'warning' : hasData(continuityLedger.value) ? 'done' : 'waiting',
    },
    {
      key: 'cost',
      title: '检查成本风控',
      detail: firstText([
        costControlAudit.value.find((item) => item.coverage === 'partial' || item.coverage === 'missing')?.gap,
        costLedger.value.summary,
        costLedger.value.budget_status_label,
        guardrails[0],
        costLedger.value.next_action_label,
      ], '等待大脑计算可复用资产、生成优先级、重试风险和预算水位。'),
      meta: costControlAudit.value.length
        ? `风控 ${costControlAudit.value.filter((item) => item.coverage === 'covered').length}/${costControlAudit.value.length}`
        : firstText([costLedger.value.risk_level, costLedger.value.budget_status, costLedger.value.risk_label], '未评级'),
      tone: costControlAudit.value.some((item) => item.coverage === 'missing') ? 'warning' : costTone(costLedger.value),
    },
    {
      key: 'quality',
      title: '检查成片验收',
      detail: firstText([
        finalDeliveryAudit.value.find((item) => item.coverage === 'partial' || item.coverage === 'missing')?.gap,
        qualityLedger.value.summary,
        qualityLedger.value.acceptance_status_label,
        blockers[0],
        qualityLedger.value.next_action_label,
      ], '等待大脑检查视频、配乐、声音、剪辑方案和最终可交付状态。'),
      meta: finalDeliveryAudit.value.length
        ? `交付 ${finalDeliveryAudit.value.filter((item) => item.coverage === 'covered').length}/${finalDeliveryAudit.value.length}`
        : firstText([qualityLedger.value.ready_score_label, qualityLedger.value.quality_score_label, qualityLedger.value.ready_score], '未评分'),
      tone: finalDeliveryAudit.value.some((item) => item.coverage === 'missing') || blockers.length || missing.length || risks.length || shotStats.value.failed ? 'warning' : hasData(qualityLedger.value) ? 'done' : 'waiting',
    },
    {
      key: 'next',
      title: '发布下一步指令',
      detail: brain.value
        ? `${brain.value.next_action_label || brain.value.next_action || '等待动作'}。${brain.value.can_continue ? '可以由“继续推进”自动执行。' : '当前需要先补齐阻塞项。'}`
        : '等待项目大脑生成可执行动作。',
      meta: brain.value?.can_continue ? '可执行' : '不可执行',
      tone: brain.value?.can_continue ? 'active' : brain.value ? 'blocked' : 'waiting',
    },
    {
      key: 'result',
      title: '执行反馈',
      detail: latestExecutionMessage.value?.content || '点击“继续推进”后，这里会显示真实执行结果、派发数量或阻塞原因。',
      meta: latestExecutionMessage.value?.timestamp ? formatTime(latestExecutionMessage.value.timestamp) : '等待执行',
      tone: latestExecutionMessage.value ? executionTone(latestExecutionMessage.value.content) : 'waiting',
    },
  ]
})

const ledgerCards = computed(() => [
  {
    key: 'progress',
    label: '进度',
    value: `${productionLedger.value.completion_percent || 0}%`,
    detail: `${firstText([productionLedger.value.current_scene?.title, productionLedger.value.current_scene_key], '未定位')} · ${firstText([productionLedger.value.remaining_label], '待计算')}`,
  },
  {
    key: 'assets',
    label: '复用资产',
    value: String(productionLedger.value.asset_locks?.reusable_total || costLedger.value.reusable_asset_count || 0),
    detail: firstText([costLedger.value.asset_reuse_label, creativeLedger.value.reusable_anchor_label], '等待资产复用策略'),
  },
  {
    key: 'risk',
    label: '风险',
    value: firstText([costLedger.value.risk_level, qualityLedger.value.acceptance_status, brain.value?.risks?.length], '0'),
    detail: firstText([costLedger.value.primary_risk, qualityLedger.value.primary_blocker, brain.value?.risks?.[0]?.title], '暂无高危项'),
  },
  {
    key: 'next',
    label: '下一步',
    value: brain.value?.next_action_label || brain.value?.next_action || '等待',
    detail: brain.value?.can_continue ? '可自动推进一小步' : firstText([brain.value?.missing?.[0]?.label], '等待补齐条件'),
  },
])

function hasData(value: Record<string, any>) {
  return Boolean(value && Object.keys(value).length)
}

function normalizeList(value: any): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (typeof item === 'string') return item
    return String(item?.title || item?.label || item?.code || item?.summary || '').trim()
  }).filter(Boolean)
}

function firstText(values: any[], fallback: string) {
  for (const value of values) {
    if (value === null || value === undefined) continue
    if (Array.isArray(value) && value.length) return firstText([value[0]], fallback)
    if (typeof value === 'object') {
      const text = value.label || value.title || value.summary || value.code
      if (text) return String(text)
      continue
    }
    const text = String(value).trim()
    if (text) return text
  }
  return fallback
}

function metricPair(label: string, done: any, total: any) {
  const doneCount = Number(done || 0)
  const totalCount = Number(total || 0)
  if (!doneCount && !totalCount) return '等待统计'
  return totalCount ? `${label} ${doneCount}/${totalCount}` : `${label} ${doneCount}`
}

function costTone(ledger: Record<string, any>): TraceTone {
  const risk = String(ledger.risk_level || ledger.budget_status || ledger.risk_label || '').toLowerCase()
  if (risk.includes('block') || risk.includes('danger') || risk.includes('高')) return 'blocked'
  if (risk.includes('watch') || risk.includes('warn') || risk.includes('中')) return 'warning'
  if (hasData(ledger)) return 'done'
  return 'waiting'
}

function executionTone(content = ''): TraceTone {
  if (content.includes('失败')) return 'blocked'
  if (content.includes('暂不支持')) return 'warning'
  return 'done'
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatTime(value: number) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  return date.toLocaleTimeString()
}
</script>

<template>
  <section class="brain-trace" aria-label="项目大脑执行轨迹">
    <div class="trace-head">
      <div>
        <p class="eyebrow">Brain Execution Trace</p>
        <h3>大脑执行轨迹</h3>
        <p>把自动化过程拆开显示：读取、分析、查账、风控、决策和执行反馈。</p>
      </div>
      <div class="trace-state" :class="{ ready: brain?.can_continue }">
        <span>{{ brain?.phase || 'waiting' }}</span>
        <strong>{{ brain?.next_action_label || brain?.next_action || '等待项目大脑' }}</strong>
      </div>
    </div>

    <div class="ledger-strip">
      <article v-for="card in ledgerCards" :key="card.key">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <p>{{ card.detail }}</p>
      </article>
    </div>

    <ol class="trace-list">
      <li v-for="item in traceItems" :key="item.key" :class="item.tone">
        <span class="trace-dot"></span>
        <div class="trace-body">
          <div class="trace-row">
            <strong>{{ item.title }}</strong>
            <em>{{ item.meta }}</em>
          </div>
          <p>{{ item.detail }}</p>
        </div>
      </li>
    </ol>

    <div class="debug-panel">
      <div class="debug-head">
        <div>
          <p class="eyebrow">Verbose Debug Flow</p>
          <h4>详细流程账本</h4>
        </div>
        <span>调试期默认展开</span>
      </div>

      <div class="debug-grid">
        <article v-for="row in debugRows" :key="row.key" class="debug-row">
          <div class="debug-title">
            <strong>{{ row.step }}</strong>
          </div>
          <dl>
            <div>
              <dt>输入依据</dt>
              <dd>{{ row.input }}</dd>
            </div>
            <div>
              <dt>判断逻辑</dt>
              <dd>{{ row.decision }}</dd>
            </div>
            <div>
              <dt>产物/调用</dt>
              <dd>{{ row.output }}</dd>
            </div>
            <div>
              <dt>停止条件</dt>
              <dd>{{ row.stop }}</dd>
            </div>
          </dl>
        </article>
      </div>

      <details class="raw-evidence">
        <summary>展开原始读取清单</summary>
        <div v-if="readFileRows.length" class="file-list">
          <div v-for="file in readFileRows" :key="file.path">
            <span>{{ file.state }}</span>
            <strong>{{ file.path }}</strong>
            <em>{{ file.size }}</em>
            <small>
              {{ file.label || 'context' }} · {{ file.coverage || 'unknown' }} ·
              parsed={{ file.parsed === undefined ? '-' : file.parsed ? 'yes' : 'no' }} ·
              consumed={{ file.consumed === undefined ? '-' : file.consumed ? 'yes' : 'no' }}
              <template v-if="file.used_by"> · used_by={{ file.used_by }}</template>
              <template v-if="file.impact_if_missing"> · 缺失影响：{{ file.impact_if_missing }}</template>
            </small>
          </div>
        </div>
        <p v-else>当前还没有工作区文件清单。</p>
      </details>

      <details class="raw-evidence">
        <summary>展开账本合并审计</summary>
        <div v-if="ledgerMergeAudit.length" class="audit-list">
          <article v-for="item in ledgerMergeAudit" :key="item.component" :class="item.coverage">
            <div>
              <strong>{{ item.label || item.component }}</strong>
              <span>{{ item.coverage }}</span>
            </div>
            <p>{{ item.evidence }}</p>
            <p>{{ item.decision_effect }}</p>
            <small>
              signals={{ Array.isArray(item.signals_used) ? item.signals_used.join(' / ') : '-' }}
              · consumed_by={{ Array.isArray(item.consumed_by) && item.consumed_by.length ? item.consumed_by.join(' / ') : '未进入决策' }}
            </small>
          </article>
        </div>
        <p v-else>当前后端还没有返回账本合并审计。</p>
      </details>

      <details class="raw-evidence">
        <summary>展开创作技巧下沉审计</summary>
        <div v-if="creativeLoweringAudit.length" class="audit-list">
          <article v-for="item in creativeLoweringAudit" :key="item.component" :class="item.coverage">
            <div>
              <strong>{{ item.label || item.component }}</strong>
              <span>{{ item.coverage }}</span>
            </div>
            <p>{{ item.evidence }}</p>
            <p>下沉到：{{ Array.isArray(item.lowered_to) ? item.lowered_to.join(' / ') : '-' }}</p>
            <p>执行边界：{{ item.execution_boundary || '-' }}</p>
            <small>
              candidate={{ item.candidate_count }} · applied={{ item.applied_count }}
              <template v-if="item.code_boundary"> · 代码边界已接入</template>
              <template v-if="item.gap"> · 缺口：{{ item.gap }}</template>
            </small>
            <small v-if="Array.isArray(item.examples) && item.examples.length">
              examples={{ item.examples.join(' / ') }}
            </small>
          </article>
        </div>
        <p v-else>当前后端还没有返回创作技巧下沉审计。</p>
      </details>

      <details class="raw-evidence">
        <summary>展开剧情承接审计</summary>
        <div v-if="continuityHandoffAudit.length" class="audit-list">
          <article v-for="item in continuityHandoffAudit" :key="item.component" :class="item.coverage">
            <div>
              <strong>{{ item.label || item.component }}</strong>
              <span>{{ item.coverage }}</span>
            </div>
            <p>{{ item.evidence }}</p>
            <p>{{ item.decision_effect }}</p>
            <small>
              consumed_by={{ Array.isArray(item.consumed_by) && item.consumed_by.length ? item.consumed_by.join(' / ') : '未进入判断' }}
              <template v-if="item.gap"> · 缺口：{{ item.gap }}</template>
            </small>
          </article>
        </div>
        <p v-else>当前后端还没有返回剧情承接审计。</p>
      </details>

      <details class="raw-evidence">
        <summary>展开成本风控审计</summary>
        <div v-if="costControlAudit.length" class="audit-list">
          <article v-for="item in costControlAudit" :key="item.component" :class="item.coverage">
            <div>
              <strong>{{ item.label || item.component }}</strong>
              <span>{{ item.coverage }}</span>
            </div>
            <p>{{ item.evidence }}</p>
            <p>{{ item.decision_effect }}</p>
            <small>
              enforced_by={{ Array.isArray(item.enforced_by) && item.enforced_by.length ? item.enforced_by.join(' / ') : '未强制' }}
              <template v-if="item.gap"> · 缺口：{{ item.gap }}</template>
            </small>
          </article>
        </div>
        <p v-else>当前后端还没有返回成本风控审计。</p>
      </details>

      <details class="raw-evidence">
        <summary>展开成片交付审计</summary>
        <div v-if="finalDeliveryAudit.length" class="audit-list">
          <article v-for="item in finalDeliveryAudit" :key="item.component" :class="item.coverage">
            <div>
              <strong>{{ item.label || item.component }}</strong>
              <span>{{ item.coverage }}</span>
            </div>
            <p>{{ item.evidence }}</p>
            <p>{{ item.decision_effect }}</p>
            <small>
              required={{ item.required ? 'yes' : 'no' }} ·
              checked_by={{ Array.isArray(item.checked_by) && item.checked_by.length ? item.checked_by.join(' / ') : '未检查' }}
              <template v-if="item.gap"> · 缺口：{{ item.gap }}</template>
            </small>
          </article>
        </div>
        <p v-else>当前后端还没有返回成片交付审计。</p>
      </details>

      <details class="raw-evidence">
        <summary>展开回写复盘审计</summary>
        <div v-if="feedbackLoopAudit.length" class="audit-list">
          <article v-for="item in feedbackLoopAudit" :key="item.component" :class="item.coverage">
            <div>
              <strong>{{ item.label || item.component }}</strong>
              <span>{{ item.coverage }}</span>
            </div>
            <p>{{ item.evidence }}</p>
            <p>{{ item.decision_effect }}</p>
            <small>
              read_next_by={{ Array.isArray(item.read_next_by) && item.read_next_by.length ? item.read_next_by.join(' / ') : '下轮未读取' }}
              <template v-if="item.gap"> · 缺口：{{ item.gap }}</template>
            </small>
          </article>
        </div>
        <p v-else>当前后端还没有返回回写复盘审计。</p>
      </details>
    </div>
  </section>
</template>

<style scoped>
.brain-trace {
  margin-bottom: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.trace-head {
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

.trace-head h3 {
  margin: 0;
  font-size: 1.05rem;
}

.trace-head p,
.ledger-strip p,
.trace-body p {
  margin: 0.35rem 0 0;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  line-height: 1.5;
}

.trace-state {
  min-width: 220px;
  align-self: stretch;
  padding-left: 1rem;
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.25rem;
}

.trace-state span {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  text-transform: uppercase;
}

.trace-state strong {
  color: var(--color-text);
  font-size: 0.96rem;
}

.trace-state.ready strong {
  color: var(--color-primary);
}

.ledger-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  border-bottom: 1px solid var(--color-border);
}

.ledger-strip article {
  min-height: 112px;
  padding: 0.85rem;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
}

.ledger-strip article:last-child {
  border-right: none;
}

.ledger-strip span {
  display: block;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  margin-bottom: 0.3rem;
}

.ledger-strip strong {
  display: block;
  color: var(--color-text);
  font-size: 1rem;
  line-height: 1.3;
}

.trace-list {
  list-style: none;
  margin: 0;
  padding: 0.35rem 1rem 1rem;
}

.trace-list li {
  position: relative;
  display: grid;
  grid-template-columns: 18px 1fr;
  gap: 0.65rem;
  padding: 0.65rem 0;
}

.trace-list li::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 1.35rem;
  bottom: -0.65rem;
  width: 1px;
  background: var(--color-border);
}

.trace-list li:last-child::before {
  display: none;
}

.trace-dot {
  width: 11px;
  height: 11px;
  margin-top: 0.28rem;
  border-radius: 999px;
  background: var(--color-text-secondary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-text-secondary) 16%, transparent);
}

.trace-row {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: baseline;
}

.trace-row strong {
  font-size: 0.86rem;
  color: var(--color-text);
}

.trace-row em {
  flex: none;
  font-style: normal;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.trace-list li.done .trace-dot {
  background: var(--color-success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-success) 18%, transparent);
}

.trace-list li.active .trace-dot {
  background: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 20%, transparent);
}

.trace-list li.warning .trace-dot {
  background: var(--color-warning);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-warning) 20%, transparent);
}

.trace-list li.blocked .trace-dot {
  background: var(--color-error);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-error) 20%, transparent);
}

.trace-list li.waiting {
  opacity: 0.72;
}

.debug-panel {
  border-top: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-bg-secondary) 76%, var(--color-bg));
  padding: 1rem;
}

.debug-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  margin-bottom: 0.8rem;
}

.debug-head h4 {
  margin: 0;
  font-size: 0.98rem;
}

.debug-head span {
  color: var(--color-primary);
  font-size: 0.76rem;
}

.debug-grid {
  display: grid;
  gap: 0.65rem;
}

.debug-row {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  overflow: hidden;
}

.debug-title {
  padding: 0.7rem 0.8rem;
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-primary) 8%, transparent);
}

.debug-title strong {
  color: var(--color-text);
  font-size: 0.84rem;
}

.debug-row dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
}

.debug-row dl > div {
  min-height: 96px;
  padding: 0.75rem;
  border-right: 1px solid var(--color-border);
}

.debug-row dl > div:last-child {
  border-right: none;
}

.debug-row dt {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  margin-bottom: 0.35rem;
}

.debug-row dd {
  margin: 0;
  color: var(--color-text);
  font-size: 0.78rem;
  line-height: 1.55;
  word-break: break-word;
}

.raw-evidence {
  margin-top: 0.8rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  overflow: hidden;
}

.raw-evidence summary {
  cursor: pointer;
  padding: 0.75rem 0.85rem;
  color: var(--color-text);
  font-size: 0.82rem;
  border-bottom: 1px solid var(--color-border);
}

.raw-evidence p {
  margin: 0;
  padding: 0.75rem 0.85rem;
  color: var(--color-text-secondary);
  font-size: 0.78rem;
}

.file-list {
  display: grid;
  gap: 1px;
  background: var(--color-border);
}

.file-list div {
  display: grid;
  grid-template-columns: 70px 1fr 90px;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  background: var(--color-bg);
  align-items: center;
}

.file-list span,
.file-list em {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  font-style: normal;
}

.file-list strong {
  color: var(--color-text);
  font-size: 0.76rem;
  word-break: break-all;
}

.file-list small {
  grid-column: 2 / 4;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  line-height: 1.45;
}

.audit-list {
  display: grid;
  gap: 1px;
  background: var(--color-border);
}

.audit-list article {
  padding: 0.72rem 0.85rem;
  background: var(--color-bg);
}

.audit-list article > div {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
}

.audit-list strong {
  color: var(--color-text);
  font-size: 0.82rem;
}

.audit-list span {
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.audit-list article.covered span {
  color: var(--color-success);
}

.audit-list article.partial span {
  color: var(--color-warning);
}

.audit-list article.missing span {
  color: var(--color-error);
}

.audit-list p {
  padding: 0;
  margin: 0.35rem 0 0;
  line-height: 1.45;
}

.audit-list small {
  display: block;
  margin-top: 0.35rem;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
  line-height: 1.45;
}

@media (max-width: 900px) {
  .trace-head {
    flex-direction: column;
  }

  .trace-state {
    min-width: 0;
    padding-left: 0;
    padding-top: 0.75rem;
    border-left: none;
    border-top: 1px solid var(--color-border);
  }

  .ledger-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ledger-strip article:nth-child(2n) {
    border-right: none;
  }

  .debug-row dl {
    grid-template-columns: 1fr;
  }

  .debug-row dl > div {
    border-right: none;
    border-bottom: 1px solid var(--color-border);
  }

  .debug-row dl > div:last-child {
    border-bottom: none;
  }

  .file-list div {
    grid-template-columns: 64px 1fr;
  }

  .file-list em {
    grid-column: 2;
  }

  .file-list small {
    grid-column: 2;
  }
}
</style>
