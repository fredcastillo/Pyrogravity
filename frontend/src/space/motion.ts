import { animate } from 'animejs/animation'

export function reveal(elements: Iterable<Element>) {
  const targets = Array.from(elements)
  if (!targets.length || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const animation = animate(targets, {
    opacity: { from: 0.84, to: 1 },
    y: { from: 8, to: 0 },
    delay: (_target: unknown, index = 0) => index * 42,
    duration: 360,
    ease: 'outCubic',
    onComplete: () => {
      // Release animation styles so sticky and focus styles continue to work.
      animation.revert()
    },
  })
  return () => { animation.revert() }
}

export function enableOrbitalField(canvas: HTMLCanvasElement) {
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
  const pointer = window.matchMedia('(any-pointer: fine)')
  let stopped = false
  let starting = false
  let dispose: (() => void) | undefined
  let context: WebGL2RenderingContext | null = null
  let ready = false
  let frame = 0
  const allowed = () => !stopped && !motion.matches && pointer.matches
  const synchronize = () => {
    if (!allowed()) {
      dispose?.()
      dispose = undefined
      return
    }
    if (!ready || starting || dispose) return
    context ??= canvas.getContext('webgl2', { alpha: true, antialias: false, powerPreference: 'low-power' })
    if (!context) return
    starting = true
    void import('./orbitalField').then(({ mountOrbitalField }) => {
      if (allowed() && context) dispose = mountOrbitalField(canvas, context)
    }).catch(() => {
      // The static backdrop remains available if the GPU or module fails.
    }).finally(() => { starting = false })
  }
  motion.addEventListener('change', synchronize)
  pointer.addEventListener('change', synchronize)
  // Let the browser paint the page and its photograph before initializing WebGL.
  const afterLoad = () => {
    frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(() => {
        ready = true
        synchronize()
      })
    })
  }
  if (document.readyState === 'complete') afterLoad()
  else window.addEventListener('load', afterLoad, { once: true })
  return () => {
    stopped = true
    window.removeEventListener('load', afterLoad)
    window.cancelAnimationFrame(frame)
    motion.removeEventListener('change', synchronize)
    pointer.removeEventListener('change', synchronize)
    dispose?.()
  }
}
