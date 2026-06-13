import { describe, expect, it } from 'vitest'

import {
  buildAgentRunTimelineEvents,
  mergeAgentRunTimelineEvents,
} from '../src/pages/director/agent-run/timelineEvents'

describe('mergeAgentRunTimelineEvents', () => {
  it('combines snapshot and live stream events in order without duplicates', () => {
    const events = mergeAgentRunTimelineEvents(
      [
        { id: 'a', time: '2026-05-27T00:00:00Z', title: 'read context' },
        { id: 'b', time: '2026-05-27T00:00:02Z', title: 'dispatch' },
      ],
      [
        { id: 'b', created_at: '2026-05-27T00:00:02Z', title: 'dispatch duplicate' },
        { id: 'c', created_at: '2026-05-27T00:00:01Z', title: 'planner' },
      ],
    )

    expect(events.map((event) => event.id)).toEqual(['a', 'c', 'b'])
  })
})

describe('buildAgentRunTimelineEvents', () => {
  it('keeps real run-chain phases visible with readable fallback labels', () => {
    const events = buildAgentRunTimelineEvents([
      {
        id: 'created',
        time: '2026-05-27T00:00:00Z',
        event_type: 'trace',
        phase: 'created',
        status: 'created',
        title: null as any,
        detail: null as any,
        meta: { mode: 'step' },
      },
      {
        id: 'read',
        time: '2026-05-27T00:00:01Z',
        event_type: 'trace',
        phase: 'read_context',
        status: 'done',
        title: null as any,
        detail: null as any,
        meta: {
          agent_event: {
            reason: 'files=8/8；consumed=8；识别项目文件、分镜、记忆和约束是否可用。',
          },
        },
      },
      {
        id: 'guard',
        time: '2026-05-27T00:00:02Z',
        event_type: 'decision',
        phase: 'cost_guard',
        status: 'done',
        title: null as any,
        detail: null as any,
        meta: {
          agent_event: {
            summary: '风控允许在当前模式下继续。',
          },
        },
      },
      {
        id: 'dispatch',
        time: '2026-05-27T00:00:03Z',
        event_type: 'decision',
        phase: 'dispatch_instruction',
        status: 'done',
        detail: 'next_action=fix_preflight_risks；can_continue=False；项目已读取，但有 1 个阻塞风险，需要先修复再继续生成。',
      },
    ])

    expect(events.map((event) => event.title)).toEqual([
      '创建 Agent Run',
      '读取上下文',
      '成本与风控',
      '发布执行指令 / 下一步判断',
    ])
    expect(events.at(-1)?.detail).toContain('阻塞风险')
  })

  it('does not hide planner/debug events in the execution-chain view', () => {
    const events = buildAgentRunTimelineEvents([
      {
        id: 'planner',
        created_at: '2026-05-27T00:00:00Z',
        event_type: 'decision',
        phase: 'llm_planner',
        source: 'deepseek',
        visibility: 'debug',
        meta: {
          planner: {
            reply: '我将检查当前关键帧输出状态。',
            action: 'status_query',
          },
        },
      },
    ])

    expect(events).toHaveLength(1)
    expect(events[0].title).toBe('DeepSeek 中控判断')
    expect(events[0].detail).toContain('检查当前关键帧')
  })
})
