import { useEffect } from 'react'

const surfaceSelector = '.match-stage, .gmail-panel, .timeline-environment, .spotify-capsule, .quick-launch'

/** Pointer-only materials; no React renders are scheduled by pointer movement. */
export function usePhysicalSurfaces(reducedMotion: boolean) {
  useEffect(() => {
    if (reducedMotion || (window.matchMedia && !window.matchMedia('(pointer: fine)').matches)) return
    let active: HTMLElement | null = null
    let activeRoot: HTMLElement | null = null
    let originalTransform: string | null = null
    const clear = () => {
      if (active) {
        active.style.removeProperty('--surface-x')
        active.style.removeProperty('--surface-y')
        active.style.removeProperty('--tilt-x')
        active.style.removeProperty('--tilt-y')
        if (originalTransform !== null) {
          if (originalTransform) active.style.transform = originalTransform
          else active.style.removeProperty('transform')
        }
        active.dataset.pointerLit = 'false'
        active = null
        originalTransform = null
      }
      if (activeRoot) activeRoot.dataset.pointerActive = 'false'
      activeRoot = null
    }
    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType && event.pointerType !== 'mouse') return
      document.documentElement.removeAttribute('data-keyboard-navigation')
      const target = event.target instanceof Element ? event.target.closest<HTMLElement>(surfaceSelector) : null
      const root = target?.closest<HTMLElement>('.livepulse-app') ?? null
      if (!target || !root) { clear(); return }
      if (active !== target) {
        clear()
        active = target
        activeRoot = root
        originalTransform = target.style.transform
        target.dataset.pointerLit = 'true'
      }
      const bounds = target.getBoundingClientRect()
      if (!bounds.width || !bounds.height) return
      const x = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width))
      const y = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))
      const portrait = window.matchMedia?.('(orientation: portrait)').matches ?? false
      const maxTilt = portrait ? 0.35 : 1
      const tiltX = (0.5 - y) * maxTilt * 2
      const tiltY = (x - 0.5) * maxTilt * 2
      target.style.setProperty('--surface-x', `${(x * 100).toFixed(1)}%`)
      target.style.setProperty('--surface-y', `${(y * 100).toFixed(1)}%`)
      target.style.setProperty('--tilt-x', `${tiltX.toFixed(2)}deg`)
      target.style.setProperty('--tilt-y', `${tiltY.toFixed(2)}deg`)
      target.style.transform = `perspective(1100px) rotateX(${tiltX.toFixed(2)}deg) rotateY(${tiltY.toFixed(2)}deg) translateZ(${target.matches('.match-stage') ? '3px' : '1px'})`
      root.dataset.pointerActive = 'true'
    }
    const onKeyboard = (event: KeyboardEvent) => {
      if (event.key === 'Tab' || event.key.startsWith('Arrow') || event.key === 'Enter' || event.key === ' ') {
        document.documentElement.dataset.keyboardNavigation = 'true'
        clear()
      }
    }
    document.addEventListener('pointermove', onPointerMove, { passive: true })
    window.addEventListener('keydown', onKeyboard)
    return () => {
      clear()
      document.documentElement.removeAttribute('data-keyboard-navigation')
      document.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('keydown', onKeyboard)
    }
  }, [reducedMotion])
}
