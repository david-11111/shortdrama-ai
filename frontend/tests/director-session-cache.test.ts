import { describe, expect, it } from 'vitest'

import { useDirectorSession } from '../src/composables/useDirectorSession'

describe('useDirectorSession cache restore', () => {
  it('does not restore stale server-derived project brain from localStorage', () => {
    localStorage.setItem(
      'director_session',
      JSON.stringify({
        projectId: 'project-1',
        projectBrain: {
          project_id: 'project-1',
          phase: 'asset_locking',
          next_action: 'plan_visual_assets',
          can_continue: true,
        },
        shots: [{ index: 1, prompt: 'shot', duration: 5, status: 'draft' }],
      }),
    )

    const session = useDirectorSession()
    session.restore()

    expect(session.projectId.value).toBe('project-1')
    expect(session.shots.value).toHaveLength(1)
    expect(session.projectBrain.value).toBeNull()
  })
})
