import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('ShotCards production routing contract', () => {
  it('does not call direct batch generation APIs from director production page', () => {
    const source = readFileSync(
      resolve(__dirname, '../src/pages/director/produce/ShotCards.vue'),
      'utf8',
    )

    expect(source).not.toContain('batchGenerateImages')
    expect(source).not.toContain('batchGenerateVideos')
  })

  it('limits single-shot keyframe generation to the clicked shot', () => {
    const source = readFileSync(
      resolve(__dirname, '../src/pages/director/produce/ShotCards.vue'),
      'utf8',
    )
    const [, produceOneImage] = source.match(/(async function produceOneImage[\s\S]*?)async function batchVideos/) || []

    expect(produceOneImage).toContain('shot_indices: [shot.index]')
  })

  it('tracks continue task ids from all compatible response fields', () => {
    const source = readFileSync(
      resolve(__dirname, '../src/pages/director/produce/ShotCards.vue'),
      'utf8',
    )

    expect(source).toContain('data?.child_task_ids')
    expect(source).toContain('data?.task_ids')
    expect(source).toContain('data?.task_id')
  })
})
