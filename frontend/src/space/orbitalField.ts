import {
  AdditiveBlending, BufferGeometry, Float32BufferAttribute, PerspectiveCamera,
  Points, Scene, ShaderMaterial, Vector2, WebGLRenderer,
} from 'three'

const vertexShader = `
  attribute float starSize;
  attribute vec3 starTint;
  uniform float pixelRatio;
  varying vec3 tint;
  void main() {
    tint = starTint;
    vec4 eye = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * eye;
    gl_PointSize = clamp(starSize * 20.0 / -eye.z, 1.0, 9.0) * pixelRatio;
  }
`

const fragmentShader = `
  varying vec3 tint;
  void main() {
    float radius = length(gl_PointCoord - vec2(0.5));
    float core = 1.0 - smoothstep(0.02, 0.21, radius);
    float halo = 1.0 - smoothstep(0.04, 0.5, radius);
    gl_FragColor = vec4(tint, core * 0.9 + halo * 0.24);
  }
`

function starGeometry() {
  const positions: number[] = []
  const sizes: number[] = []
  const tints: number[] = []
  let seed = 87931
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  for (let index = 0; index < 780; index++) {
    const x = (random() - 0.5) * 58
    const inBand = index > 460
    const y = inBand ? x * 0.33 + (random() - 0.5) * 8 : (random() - 0.5) * 30
    const warmth = random()
    positions.push(x, y, -24 + random() * 30)
    sizes.push(1.8 + random() ** 4 * (inBand ? 3.5 : 5.5))
    tints.push(warmth > 0.85 ? 1 : 0.54, warmth > 0.85 ? 0.78 : 0.81, warmth > 0.85 ? 0.57 : 1)
  }
  return new BufferGeometry()
    .setAttribute('position', new Float32BufferAttribute(positions, 3))
    .setAttribute('starSize', new Float32BufferAttribute(sizes, 1))
    .setAttribute('starTint', new Float32BufferAttribute(tints, 3))
}

export function mountOrbitalField(canvas: HTMLCanvasElement, context: WebGL2RenderingContext) {
  const renderer = new WebGLRenderer({ canvas, context, alpha: true, antialias: false })
  renderer.setClearColor(0x000000, 0)
  const scene = new Scene()
  const camera = new PerspectiveCamera(49, 1, 0.1, 65)
  camera.position.z = 19
  const geometry = starGeometry()
  const material = new ShaderMaterial({
    vertexShader, fragmentShader, uniforms: { pixelRatio: { value: 1 } },
    transparent: true, blending: AdditiveBlending, depthWrite: false,
  })
  const stars = new Points(geometry, material)
  scene.add(stars)
  const target = new Vector2()
  const offset = new Vector2()
  const artwork = document.querySelector<HTMLElement>('[data-orbital-art]')
  let frame = 0
  let lost = false

  const schedule = () => {
    if (!frame && !lost && !document.hidden) frame = requestAnimationFrame(render)
  }

  function render() {
    frame = 0
    offset.lerp(target, 0.14)
    if (offset.distanceToSquared(target) < 0.00001) offset.copy(target)
    camera.position.set(offset.x * 1.65, offset.y * 1.2, 19)
    camera.lookAt(offset.x * 0.3, offset.y * 0.3, 0)
    artwork?.style.setProperty('--orbit-x', `${offset.x * -16}px`)
    artwork?.style.setProperty('--orbit-y', `${offset.y * 12}px`)
    renderer.render(scene, camera)
    if (!offset.equals(target)) schedule()
  }

  const resize = () => {
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    if (!width || !height) return
    const ratio = Math.min(window.devicePixelRatio, 1.5)
    renderer.setPixelRatio(ratio)
    renderer.setSize(width, height, false)
    material.uniforms.pixelRatio.value = ratio
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    schedule()
  }

  const move = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return
    target.set(event.clientX / window.innerWidth * 2 - 1, 1 - event.clientY / window.innerHeight * 2)
    schedule()
  }
  const reset = () => { target.set(0, 0); schedule() }
  const contextLost = (event: Event) => {
    event.preventDefault()
    lost = true
    cancelAnimationFrame(frame)
    frame = 0
    delete canvas.dataset.orbitalActive
    artwork?.style.removeProperty('--orbit-x')
    artwork?.style.removeProperty('--orbit-y')
  }
  const contextRestored = () => { lost = false; canvas.dataset.orbitalActive = 'true'; resize() }
  canvas.addEventListener('webglcontextlost', contextLost)
  canvas.addEventListener('webglcontextrestored', contextRestored)
  window.addEventListener('pointermove', move, { passive: true })
  document.documentElement.addEventListener('pointerleave', reset)
  window.addEventListener('resize', resize)
  document.addEventListener('visibilitychange', schedule)
  canvas.dataset.orbitalActive = 'true'
  resize()

  return () => {
    cancelAnimationFrame(frame)
    window.removeEventListener('pointermove', move)
    document.documentElement.removeEventListener('pointerleave', reset)
    window.removeEventListener('resize', resize)
    document.removeEventListener('visibilitychange', schedule)
    canvas.removeEventListener('webglcontextlost', contextLost)
    canvas.removeEventListener('webglcontextrestored', contextRestored)
    delete canvas.dataset.orbitalActive
    artwork?.style.removeProperty('--orbit-x')
    artwork?.style.removeProperty('--orbit-y')
    geometry.dispose()
    material.dispose()
    renderer.dispose()
  }
}
