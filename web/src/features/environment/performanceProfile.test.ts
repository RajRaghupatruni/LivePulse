import { describe, expect, it } from 'vitest'
import { atmosphereBudget, environmentFrameLoop, initialPerformanceProfile, nextPerformanceProfile } from './performanceProfile'

describe('atmosphere performance profile', () => {
  it('starts conservatively for small, dense, and portrait displays', () => {
    expect(initialPerformanceProfile(1, 1920, 1080)).toBe('HIGH')
    expect(initialPerformanceProfile(2, 1600, 900)).toBe('MEDIUM')
    expect(initialPerformanceProfile(1, 900, 1600)).toBe('LOW')
    expect(atmosphereBudget('HIGH', true).particleCount).toBeLessThan(atmosphereBudget('HIGH', false).particleCount)
    expect(atmosphereBudget('HIGH', false, true)).toMatchObject({ particleCount: 8, dpr: 0.82 })
  })

  it('steps visual quality down quickly under frame pressure and recovers gradually', () => {
    expect(nextPerformanceProfile('HIGH', 47)).toBe('MEDIUM')
    expect(nextPerformanceProfile('MEDIUM', 40)).toBe('LOW')
    expect(nextPerformanceProfile('LOW', 58)).toBe('MEDIUM')
    expect(nextPerformanceProfile('MEDIUM', 60)).toBe('HIGH')
    expect(nextPerformanceProfile('HIGH', 55)).toBe('HIGH')
  })

  it('pauses continuous rendering for reduced motion or hidden windows', () => {
    expect(environmentFrameLoop(false, true)).toBe('always')
    expect(environmentFrameLoop(true, true)).toBe('demand')
    expect(environmentFrameLoop(false, false)).toBe('demand')
  })
})
