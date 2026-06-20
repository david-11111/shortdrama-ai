import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('OutputBoard agent-run action task tracking contract', () => {
  it('tracks task ids returned by keyframe batch and video-from-pool actions', () => {
    const source = readFileSync(
      resolve(__dirname, '../src/pages/director/agent-run/components/OutputBoard.vue'),
      'utf8',
    )

    expect(source).toContain("import { useTaskPoller } from '@/composables/useTaskPoller'")
    expect(source).toContain('function trackActionTasks')
    expect(source).toContain('data?.child_task_ids')
    expect(source).toContain('trackActionTasks(data)')
  })

  it('keeps generated videos visible before image-heavy output lists', () => {
    const source = readFileSync(
      resolve(__dirname, '../src/pages/director/agent-run/components/OutputBoard.vue'),
      'utf8',
    )

    expect(source.indexOf('output-videos')).toBeGreaterThan(-1)
    expect(source.indexOf('output-images')).toBeGreaterThan(-1)
    expect(source.indexOf('output-videos')).toBeLessThan(source.indexOf('output-images'))
    expect(source).toContain('items.find((shot) => shot.selected_video)')
    expect(source).toContain('v-if="shot.selected_video"')
  })

  it('promotes the final video and keeps reference images in a horizontal strip', () => {
    const source = readFileSync(
      resolve(__dirname, '../src/pages/director/agent-run/components/OutputBoard.vue'),
      'utf8',
    )

    expect(source).toContain('class="final-video-panel"')
    expect(source).toContain('v-if="finalVideoUrl"')
    expect(source).toContain('controls preload="metadata"')
    expect(source).toContain('const clipVideos = computed')
    expect(source).toContain('function isFinalVideo')
    expect(source).toContain('.output-images')
    expect(source).toContain('overflow-x: auto')
    expect(source).toContain('flex: 0 0 116px')
  })

  it('sends the selected long-form duration instead of a fixed 15 second value', () => {
    const source = readFileSync(
      resolve(__dirname, '../src/pages/director/agent-run/components/OutputBoard.vue'),
      'utf8',
    )

    expect(source).toContain('v-model.number="videoDuration"')
    expect(source).toContain("localStorage.getItem('agent-run:video-duration') || 60")
    expect(source).toContain('const duration = boundedVideoDuration(videoDuration.value)')
    expect(source).toContain('duration,')
    expect(source).not.toContain('duration: 15,')
  })
})
