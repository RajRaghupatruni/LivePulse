export type PerformanceProfile = 'HIGH' | 'MEDIUM' | 'LOW'
export type EnvironmentFrameLoop = 'always' | 'demand'

export function environmentFrameLoop(reducedMotion: boolean, visible: boolean): EnvironmentFrameLoop {
  return reducedMotion || !visible ? 'demand' : 'always'
}

export function initialPerformanceProfile(devicePixelRatio: number, width: number, height: number): PerformanceProfile {
  if (width < 900 || height > width * 1.2 || devicePixelRatio > 2.25) return 'LOW'
  if (width < 1366 || devicePixelRatio > 1.65) return 'MEDIUM'
  return 'HIGH'
}

export function nextPerformanceProfile(current: PerformanceProfile, fps: number): PerformanceProfile {
  if (fps < 38) return 'LOW'
  if (fps < 51 && current === 'HIGH') return 'MEDIUM'
  if (fps < 43 && current === 'MEDIUM') return 'LOW'
  if (fps > 57 && current === 'LOW') return 'MEDIUM'
  if (fps > 59 && current === 'MEDIUM') return 'HIGH'
  return current
}

export function atmosphereBudget(profile: PerformanceProfile, portrait: boolean, reducedMotion = false) {
  const count = profile === 'HIGH' ? 68 : profile === 'MEDIUM' ? 42 : 22
  const dpr = profile === 'HIGH' ? 1.45 : profile === 'MEDIUM' ? 1.1 : 0.82
  return {
    particleCount: reducedMotion ? 8 : portrait ? Math.max(14, Math.round(count * 0.58)) : count,
    dpr: reducedMotion ? Math.min(dpr, 0.82) : dpr,
  }
}
